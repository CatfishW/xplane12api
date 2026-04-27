from __future__ import annotations

import io
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


class ArtifactUnavailable(RuntimeError):
    pass


GAUGE_DEVICE_ORDER = [
    "gns530_1",
    "gns530_2",
    "gns430_1",
    "gns430_2",
    "primus_pfd_1",
    "primus_mfd_1",
    "primus_mfd_3",
    "primus_mfd_2",
    "primus_pfd_2",
]

PRIMARY_ARTIFACTS = {
    "weather": ["weather_radar_pilot", "gns530_1", "gns430_1", "primus_mfd_1", "primus_mfd_3"],
    "traffic": ["gns530_1", "gns430_1", "primus_mfd_2", "primus_mfd_3", "primus_mfd_1"],
}


@dataclass(frozen=True)
class ArtifactInfo:
    slug: str
    path: Path
    width: int
    height: int
    updated_at: float


class PluginArtifactStore:
    def __init__(self, *, freshness_seconds: float = 15.0) -> None:
        default_dir = Path(__file__).resolve().parents[2] / ".runtime" / "xplane12_images"
        self._base_dir = Path(os.getenv("XPLANE_IMAGE_EXPORT_DIR", str(default_dir))).expanduser()
        self._freshness_seconds = freshness_seconds
        self._png_cache: dict[tuple[str, int, int], bytes] = {}
        self._collage_cache: dict[tuple[tuple[str, float], ...], bytes] = {}

    def render_png(self, key: str) -> bytes:
        if key == "gauges":
            return self._render_gauges_collage()
        slug = self._resolve_slug(key)
        info = self._artifact_info(slug)
        cache_key = (slug, info.path.stat().st_mtime_ns, info.width * info.height)
        cached = self._png_cache.get(cache_key)
        if cached is not None:
            return cached
        with Image.open(info.path) as image:
            payload = self._encode_png(image.convert("RGB"))
        self._png_cache = {cache_key: payload}
        return payload

    def list_gauges(self) -> list[dict[str, object]]:
        gauges: list[dict[str, object]] = []
        for slug in GAUGE_DEVICE_ORDER:
            try:
                info = self._artifact_info(slug)
            except ArtifactUnavailable:
                continue
            gauges.append(
                {
                    "slug": slug,
                    "path": f"/v1/render/gauges/{slug}.png",
                    "width": info.width,
                    "height": info.height,
                    "updated_at": info.updated_at,
                }
            )
        return gauges

    def artifact_manifest(self) -> dict[str, object]:
        weather_slug = self._try_resolve_slug("weather")
        traffic_slug = self._try_resolve_slug("traffic")
        return {
            "weather": weather_slug,
            "traffic": traffic_slug,
            "gauges": self.list_gauges(),
        }

    def _render_gauges_collage(self) -> bytes:
        images: list[tuple[str, ArtifactInfo, Image.Image]] = []
        signature: list[tuple[str, float]] = []
        for slug in GAUGE_DEVICE_ORDER:
            try:
                info = self._artifact_info(slug)
            except ArtifactUnavailable:
                continue
            with Image.open(info.path) as image:
                images.append((slug, info, image.convert("RGB")))
            signature.append((slug, info.updated_at))
        if not images:
            raise ArtifactUnavailable("gauges_unavailable")
        cache_key = tuple(signature)
        cached = self._collage_cache.get(cache_key)
        if cached is not None:
            return cached

        columns = 3
        tile_width = 520
        tile_height = 520
        gap = 18
        rows = math.ceil(len(images) / columns)
        canvas = Image.new(
            "RGB",
            (
                columns * tile_width + (columns + 1) * gap,
                rows * tile_height + (rows + 1) * gap,
            ),
            "#04070c",
        )

        for index, (_slug, _info, image) in enumerate(images):
            col = index % columns
            row = index // columns
            cell = image.copy()
            cell.thumbnail((tile_width, tile_height))
            x = gap + col * (tile_width + gap) + (tile_width - cell.width) // 2
            y = gap + row * (tile_height + gap) + (tile_height - cell.height) // 2
            canvas.paste(cell, (x, y))

        payload = self._encode_png(canvas)
        self._collage_cache = {cache_key: payload}
        return payload

    def _resolve_slug(self, key: str) -> str:
        if key in GAUGE_DEVICE_ORDER or key.startswith("weather_radar_"):
            _ = self._artifact_info(key)
            return key
        candidates = PRIMARY_ARTIFACTS.get(key)
        if candidates is None:
            raise ArtifactUnavailable(f"unknown_artifact:{key}")
        for slug in candidates:
            try:
                _ = self._artifact_info(slug)
                return slug
            except ArtifactUnavailable:
                continue
        raise ArtifactUnavailable(f"artifact_unavailable:{key}")

    def _try_resolve_slug(self, key: str) -> str | None:
        try:
            return self._resolve_slug(key)
        except ArtifactUnavailable:
            return None

    def _artifact_info(self, slug: str) -> ArtifactInfo:
        path = self._base_dir / f"{slug}.ppm"
        try:
            stat = path.stat()
        except FileNotFoundError as error:
            raise ArtifactUnavailable(f"missing_artifact:{slug}") from error
        age_seconds = max(0.0, time.time() - stat.st_mtime)
        if age_seconds > self._freshness_seconds:
            raise ArtifactUnavailable(f"stale_artifact:{slug}")
        with Image.open(path) as image:
            width, height = image.size
        return ArtifactInfo(slug=slug, path=path, width=width, height=height, updated_at=stat.st_mtime)

    @staticmethod
    def _encode_png(image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
