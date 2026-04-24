from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

import pyautogui
from PIL import ImageDraw

from app.config import settings
from tools.capture.mss_backend import MSSCaptureBackend


def inspect_screen(grid_size: int = 100) -> dict:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(settings.artifact_root) / "diagnostics" / f"inspect_{stamp}_{uuid4().hex[:8]}"
    out_dir.mkdir(parents=True, exist_ok=True)

    image = MSSCaptureBackend(settings.monitor_index).capture()
    draw = ImageDraw.Draw(image)
    width, height = image.size

    for x in range(0, width, grid_size):
        draw.line((x, 0, x, height), fill=(255, 0, 0), width=1)
        draw.text((x + 3, 3), str(x), fill=(255, 0, 0))
    for y in range(0, height, grid_size):
        draw.line((0, y, width, y), fill=(255, 0, 0), width=1)
        draw.text((3, y + 3), str(y), fill=(255, 0, 0))

    mouse = pyautogui.position()
    mx, my = int(mouse.x), int(mouse.y)
    draw.ellipse((mx - 8, my - 8, mx + 8, my + 8), outline=(0, 255, 0), width=3)
    draw.text((mx + 10, my + 10), f"mouse=({mx},{my})", fill=(0, 160, 0))

    path = out_dir / "screen_grid.png"
    image.save(path)

    return {
        "monitor_index": settings.monitor_index,
        "screen_width": width,
        "screen_height": height,
        "mouse_position": [mx, my],
        "grid_size": grid_size,
        "path": str(path),
        "artifacts_dir": str(out_dir),
    }

