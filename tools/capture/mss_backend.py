from __future__ import annotations

from mss import mss
from PIL import Image, ImageDraw

from app.config import settings
from tools.capture.base import ScreenCaptureBackend


class MSSCaptureBackend(ScreenCaptureBackend):
    def __init__(self, monitor_index: int = 1):
        self.monitor_index = monitor_index

    def capture(self) -> Image.Image:
        try:
            with mss() as sct:
                monitor = sct.monitors[self.monitor_index]
                shot = sct.grab(monitor)
                return Image.frombytes("RGB", shot.size, shot.rgb)
        except Exception:
            if not settings.allow_placeholder_screenshot:
                raise
            image = Image.new("RGB", (1280, 800), color=(245, 247, 250))
            draw = ImageDraw.Draw(image)
            draw.rectangle((20, 20, 1260, 780), outline=(210, 216, 226), width=2)
            draw.text((48, 48), "CUA-Lark placeholder screenshot", fill=(40, 48, 60))
            draw.text((48, 84), "Screen capture is unavailable in this environment.", fill=(80, 88, 100))
            return image
