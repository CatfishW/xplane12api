from __future__ import annotations

import io
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass

from PIL import Image


class CaptureUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class CropSpec:
    left: float
    top: float
    width: float
    height: float

    def to_box(self, image_width: int, image_height: int) -> tuple[int, int, int, int]:
        if max(self.left, self.top, self.width, self.height) <= 1.0:
            left = int(round(image_width * self.left))
            top = int(round(image_height * self.top))
            width = int(round(image_width * self.width))
            height = int(round(image_height * self.height))
        else:
            left = int(round(self.left))
            top = int(round(self.top))
            width = int(round(self.width))
            height = int(round(self.height))
        right = max(left + 1, min(image_width, left + width))
        lower = max(top + 1, min(image_height, top + height))
        left = max(0, min(left, image_width - 1))
        top = max(0, min(top, image_height - 1))
        return left, top, right, lower


@dataclass(frozen=True)
class WindowGeometry:
    window_id: str
    x: int
    y: int
    width: int
    height: int


DEFAULT_CROPS: dict[str, CropSpec] = {
    # Current cockpit defaults: center MFD, right MFD, and full instrument panel.
    "weather": CropSpec(0.427, 0.389, 0.163, 0.479),
    "traffic": CropSpec(0.677, 0.389, 0.163, 0.479),
    "gauges": CropSpec(0.122, 0.125, 0.872, 0.764),
}


def _parse_crop_spec(name: str, default: CropSpec) -> CropSpec:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        parts = [float(part.strip()) for part in raw_value.split(",")]
    except ValueError:
        return default
    if len(parts) != 4:
        return default
    return CropSpec(*parts)


class XPlaneWindowCapture:
    def __init__(self, *, refresh_seconds: float = 1.0) -> None:
        self._refresh_seconds = refresh_seconds
        self._lock = threading.Lock()
        self._latest_image: Image.Image | None = None
        self._latest_capture_ts = 0.0
        self._window_id: str | None = os.getenv("XPLANE_CAPTURE_WINDOW_ID")
        self._window_geometry: WindowGeometry | None = None
        self._crop_specs = {
            key: _parse_crop_spec(f"XPLANE_CAPTURE_{key.upper()}_BOX", spec)
            for key, spec in DEFAULT_CROPS.items()
        }

    def render_png(self, crop_name: str) -> bytes:
        crop_spec = self._crop_specs.get(crop_name)
        if crop_spec is None:
            raise CaptureUnavailable(f"unknown_crop:{crop_name}")
        image = self._ensure_latest_image()
        left, top, right, lower = crop_spec.to_box(image.width, image.height)
        cropped = image.crop((left, top, right, lower))
        buffer = io.BytesIO()
        cropped.save(buffer, format="PNG")
        return buffer.getvalue()

    def _ensure_latest_image(self) -> Image.Image:
        with self._lock:
            now = time.time()
            if self._latest_image is not None and (now - self._latest_capture_ts) < self._refresh_seconds:
                return self._latest_image.copy()

            image = self._capture_window()
            self._latest_image = image
            self._latest_capture_ts = now
            return image.copy()

    def _capture_window(self) -> Image.Image:
        errors: list[str] = []
        for _ in range(2):
            geometry = self._discover_window_geometry()
            try:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                    temp_path = temp_file.name
                result = subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        "-f",
                        "x11grab",
                        "-video_size",
                        f"{geometry.width}x{geometry.height}",
                        "-i",
                        self._build_display_source(geometry),
                        "-frames:v",
                        "1",
                        temp_path,
                    ],
                    check=True,
                    capture_output=True,
                    timeout=12,
                )
                with Image.open(temp_path) as image:
                    return image.convert("RGB")
            except Exception as error:
                errors.append(str(error))
                self._window_id = None
                self._window_geometry = None
            finally:
                if 'temp_path' in locals() and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
        raise CaptureUnavailable("capture_failed:" + " | ".join(errors))

    def _discover_window_geometry(self) -> WindowGeometry:
        if self._window_geometry is not None:
            return self._window_geometry
        if self._window_id:
            geometry = self._read_window_geometry(self._window_id)
            if geometry is not None:
                self._window_geometry = geometry
                return geometry
        candidates = []
        for pattern in ("^X-Plane$", "X-Plane"):
            result = subprocess.run(
                ["xdotool", "search", "--onlyvisible", "--name", pattern],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                candidates.extend(candidate.strip() for candidate in result.stdout.splitlines() if candidate.strip())
        for candidate in candidates:
            geometry = self._read_window_geometry(candidate)
            if geometry is None:
                continue
            self._window_id = candidate
            self._window_geometry = geometry
            return geometry
        raise CaptureUnavailable("xplane_window_not_found")

    def _read_window_geometry(self, window_id: str) -> WindowGeometry | None:
        result = subprocess.run(
            ["xwininfo", "-id", window_id],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        output = result.stdout
        width = self._extract_dimension(output, "Width:")
        height = self._extract_dimension(output, "Height:")
        x = self._extract_dimension(output, "Absolute upper-left X:")
        y = self._extract_dimension(output, "Absolute upper-left Y:")
        if width >= 1000 and height >= 600 and "Map State: IsViewable" in output:
            return WindowGeometry(window_id=window_id, x=x, y=y, width=width, height=height)
        return None

    def _build_display_source(self, geometry: WindowGeometry) -> str:
        display = os.getenv("DISPLAY", ":1").strip() or ":1"
        if "+" in display:
            return display
        if "." not in display:
            display = f"{display}.0"
        return f"{display}+{geometry.x},{geometry.y}"

    @staticmethod
    def _extract_dimension(output: str, prefix: str) -> int:
        for line in output.splitlines():
            if prefix not in line:
                continue
            try:
                return int(line.split(prefix, 1)[1].strip())
            except ValueError:
                return 0
        return 0
