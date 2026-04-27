#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image


SAFE_MODE_MARKERS = (
    "x-plane crashed on its last flight",
    "would you like to use safe mode",
)
WINDOW_NAME = "X-Plane"


def run_command(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=check,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )


def latest_window_id() -> str | None:
    try:
        result = run_command("xdotool", "search", "--name", WINDOW_NAME)
    except subprocess.CalledProcessError:
        return None
    window_ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return window_ids[-1] if window_ids else None


def capture_window(window_id: str, path: Path) -> bool:
    try:
        run_command("import", "-window", window_id, str(path))
    except subprocess.CalledProcessError:
        return False
    return path.is_file()


def detect_dialog_bbox(image: Image.Image, threshold: int = 25) -> tuple[int, int, int, int] | None:
    grayscale = image.convert("L")
    width, height = grayscale.size
    xs: list[int] = []
    ys: list[int] = []
    for y in range(height):
        for x in range(width):
            if grayscale.getpixel((x, y)) > threshold:
                xs.append(x)
                ys.append(y)
    if not xs or not ys:
        return None

    left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
    if right - left < 300 or bottom - top < 200:
        return None
    return left, top, right, bottom


def ocr_text(image: Image.Image, tmpdir: Path) -> str:
    target = tmpdir / "ocr.png"
    image.save(target)
    try:
        result = run_command("tesseract", str(target), "stdout", check=False)
    except FileNotFoundError:
        return ""
    return result.stdout.casefold()


def is_safe_mode_dialog(image: Image.Image, tmpdir: Path) -> bool:
    text = ocr_text(image, tmpdir)
    return all(marker in text for marker in SAFE_MODE_MARKERS)


def click_no_thanks(window_id: str, dialog_bbox: tuple[int, int, int, int]) -> None:
    left, top, right, bottom = dialog_bbox
    width = right - left
    height = bottom - top
    target_x = left + int(width * 0.78)
    target_y = top + int(height * 0.93)
    run_command("xdotool", "mousemove", "--window", window_id, str(target_x), str(target_y))
    run_command("xdotool", "click", "1")


def wait_for_safe_mode(timeout_seconds: float, poll_seconds: float) -> int:
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    with tempfile.TemporaryDirectory(prefix="xplane12-safe-mode-") as temp_dir:
        tmpdir = Path(temp_dir)
        while time.monotonic() < deadline:
            window_id = latest_window_id()
            if not window_id:
                time.sleep(poll_seconds)
                continue

            capture_path = tmpdir / "window.png"
            if not capture_window(window_id, capture_path):
                time.sleep(poll_seconds)
                continue

            with Image.open(capture_path) as image:
                dialog_bbox = detect_dialog_bbox(image)
                if dialog_bbox is None:
                    time.sleep(poll_seconds)
                    continue

                dialog_image = image.crop(dialog_bbox)
                if not is_safe_mode_dialog(dialog_image, tmpdir):
                    time.sleep(poll_seconds)
                    continue

            print("[xplane12_safe_mode_watchdog] dismissing safe mode dialog", flush=True)
            click_no_thanks(window_id, dialog_bbox)
            return 0

            time.sleep(poll_seconds)

    print("[xplane12_safe_mode_watchdog] timeout without safe mode dialog", flush=True)
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dismiss the X-Plane safe mode dialog by clicking 'No Thanks'"
    )
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    return parser


def main() -> int:
    if not os.environ.get("DISPLAY") or not os.environ.get("XAUTHORITY"):
        print("[xplane12_safe_mode_watchdog] DISPLAY/XAUTHORITY not set; skipping", flush=True)
        return 0
    for tool_name in ("xdotool", "import", "tesseract"):
        if not shutil_which(tool_name):
            print(f"[xplane12_safe_mode_watchdog] missing dependency: {tool_name}", flush=True)
            return 0
    args = build_arg_parser().parse_args()
    return wait_for_safe_mode(args.timeout_seconds, args.poll_seconds)


def shutil_which(name: str) -> str | None:
    from shutil import which

    return which(name)


if __name__ == "__main__":
    sys.exit(main())
