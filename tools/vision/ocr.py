from __future__ import annotations

from PIL import Image


class OCRClient:
    def extract_text(self, image: Image.Image) -> list[str]:
        # 首版先占位，后续接 RapidOCR / PaddleOCR
        return []