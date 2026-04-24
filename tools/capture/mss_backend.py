from __future__ import annotations

from mss import mss
from PIL import Image, ImageDraw, ImageGrab

from app.config import settings
from tools.capture.base import ScreenCaptureBackend
from tools.capture.diagnostics import analyze_pil_image


class ScreenshotCaptureError(RuntimeError):
    pass


class MSSCaptureBackend(ScreenCaptureBackend):
    def __init__(self, monitor_index: int | None = None):
        self.monitor_index = settings.monitor_index if monitor_index is None else monitor_index
        self.last_backend = "mss"
        self.last_monitor_index = self.monitor_index
        self.last_warning: str | None = None

    def capture(self) -> Image.Image:
        warnings: list[str] = []

        try:
            image = self._capture_mss_monitor(self.monitor_index)
            analysis = analyze_pil_image(image, "memory", self.monitor_index)
            if not analysis.is_suspicious:
                self._mark("mss", self.monitor_index, None)
                return image
            warnings.append(f"mss monitor {self.monitor_index}: {analysis.warning}")

            fallback = self._capture_first_healthy_mss_monitor(exclude={self.monitor_index})
            if fallback is not None:
                return fallback
        except Exception as exc:
            warnings.append(f"mss monitor {self.monitor_index}: capture failed: {exc}")

        fallback = self._capture_imagegrab(warnings)
        if fallback is not None:
            return fallback

        warning = "; ".join(warnings) or "screen capture failed"
        self.last_warning = warning
        if not settings.allow_placeholder_screenshot:
            raise ScreenshotCaptureError(warning)
        return self._placeholder(warning)

    def _capture_first_healthy_mss_monitor(self, exclude: set[int]) -> Image.Image | None:
        if not settings.auto_select_healthy_monitor:
            return None
        with mss() as sct:
            for index, _monitor in enumerate(sct.monitors):
                if index in exclude:
                    continue
                try:
                    image = self._capture_mss_monitor(index)
                    analysis = analyze_pil_image(image, "memory", index)
                    if not analysis.is_suspicious:
                        self._mark("mss_auto_monitor", index, None)
                        return image
                except Exception:
                    continue
        return None

    @staticmethod
    def _capture_mss_monitor(index: int) -> Image.Image:
        with mss() as sct:
            if index < 0 or index >= len(sct.monitors):
                raise ScreenshotCaptureError(f"Monitor index {index} is not available.")
            monitor = sct.monitors[index]
            shot = sct.grab(monitor)
            return Image.frombytes("RGB", shot.size, shot.rgb)

    def _capture_imagegrab(self, warnings: list[str]) -> Image.Image | None:
        for label, kwargs in (
            ("pil_imagegrab_all_screens", {"all_screens": True}),
            ("pil_imagegrab_primary", {}),
        ):
            try:
                image = ImageGrab.grab(**kwargs)
                analysis = analyze_pil_image(image, "memory", -1)
                if not analysis.is_suspicious:
                    self._mark(label, -1, None)
                    return image.convert("RGB")
                warnings.append(f"{label}: {analysis.warning}")
            except Exception as exc:
                warnings.append(f"{label}: capture failed: {exc}")
        return None

    def _placeholder(self, warning: str) -> Image.Image:
        self._mark("placeholder", self.monitor_index, warning)
        image = Image.new("RGB", (1280, 800), color=(245, 247, 250))
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, 1260, 780), outline=(210, 216, 226), width=2)
        draw.text((48, 48), "CUA-Lark placeholder screenshot", fill=(40, 48, 60))
        draw.text((48, 84), "Real screen capture is unavailable or suspicious.", fill=(80, 88, 100))
        draw.text((48, 120), warning[:150], fill=(160, 55, 45))
        return image

    def _mark(self, backend: str, monitor_index: int, warning: str | None) -> None:
        self.last_backend = backend
        self.last_monitor_index = monitor_index
        self.last_warning = warning
