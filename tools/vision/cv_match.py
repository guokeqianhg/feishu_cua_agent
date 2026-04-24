from __future__ import annotations

from PIL import Image


class CVMatcher:
    def match_templates(self, image: Image.Image) -> list[dict]:
        # 首版占位：后续可加入发送按钮、关闭按钮等模板匹配
        return []