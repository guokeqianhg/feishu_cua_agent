from __future__ import annotations

from abc import ABC, abstractmethod
from PIL import Image


class ScreenCaptureBackend(ABC):
    @abstractmethod
    def capture(self) -> Image.Image:
        raise NotImplementedError