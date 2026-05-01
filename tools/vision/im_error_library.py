from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from core.schemas import BoundingBox, Observation
from tools.vision.lark_locator import detect_lark_window
from tools.vision.ocr_client import ocr_image
from PIL import Image


@dataclass(frozen=True)
class ImScreenState:
    target: str
    target_visible: bool
    wrong_state: str | None
    reference_match: str | None
    reference_similarity: float
    normalized_text: str

    @property
    def is_target_chat(self) -> bool:
        return self.target_visible and self.wrong_state is None and self.reference_match is None


WRONG_CHAT_PATTERNS: dict[str, tuple[str, ...]] = {
    "knowledge_qa": ("知识问答", "知识库问答", "智能问答", "问答", "知识库"),
    "bot_or_ai": ("机器人", "Bot", "AI助手", "智能助手"),
}


def analyze_im_screen(observation: Observation | None, target: str | None = None) -> ImScreenState | None:
    if observation is None:
        return None
    target = (target or "").strip()
    if not target:
        return None

    text = _visible_im_text(observation)
    normalized = _normalize_text(text)
    target_visible = _normalize_text(target) in normalized
    wrong_state = _first_wrong_state(normalized)
    reference_match, reference_similarity = match_im_error_reference(observation.screenshot_path)
    return ImScreenState(
        target=target,
        target_visible=target_visible,
        wrong_state=wrong_state,
        reference_match=reference_match,
        reference_similarity=reference_similarity,
        normalized_text=normalized,
    )


def match_im_error_reference(screenshot_path: str, threshold: float = 0.88) -> tuple[str | None, float]:
    current_hash = _right_pane_hash(screenshot_path)
    if current_hash is None:
        return None, 0.0
    best_name = None
    best_similarity = 0.0
    for name, ref_hash in _reference_hashes().items():
        similarity = _hash_similarity(current_hash, ref_hash)
        if similarity > best_similarity:
            best_name = name
            best_similarity = similarity
    if best_name and best_similarity >= threshold:
        return best_name, best_similarity
    return None, best_similarity


def _visible_im_text(observation: Observation) -> str:
    pieces: list[str] = []
    if observation.window_title:
        pieces.append(observation.window_title)

    window = detect_lark_window(observation.screenshot_path)
    if window is not None:
        # Only inspect the active conversation pane. The left search-result
        # list can contain the correct target even when the right pane is a
        # wrong chat such as Knowledge Q&A.
        roi = BoundingBox(
            x1=window.x1 + int(window.width * 0.33),
            y1=window.y1,
            x2=window.x2,
            y2=window.y2,
        )
    else:
        roi = None
        pieces.extend(observation.ocr_lines or [])
    pieces.extend(text for _bbox, text, _confidence in ocr_image(observation.screenshot_path, roi))
    return " ".join(pieces)


def _first_wrong_state(normalized_text: str) -> str | None:
    for name, patterns in WRONG_CHAT_PATTERNS.items():
        if any(_normalize_text(pattern) in normalized_text for pattern in patterns):
            return name
    return None


@lru_cache(maxsize=1)
def _reference_hashes() -> dict[str, tuple[int, ...]]:
    refs_dir = Path(__file__).resolve().parent / "im_error_refs"
    hashes: dict[str, tuple[int, ...]] = {}
    for path in sorted(refs_dir.glob("*.png")):
        image_hash = _right_pane_hash(str(path))
        if image_hash is not None:
            hashes[path.stem] = image_hash
    return hashes


def _right_pane_hash(path: str) -> tuple[int, ...] | None:
    if not Path(path).exists():
        return None
    window = detect_lark_window(path)
    image = Image.open(path).convert("L")
    try:
        width, height = image.size
        if window is not None:
            crop_box = (
                window.x1 + int(window.width * 0.33),
                window.y1,
                window.x2,
                window.y2,
            )
        else:
            crop_box = (int(width * 0.33), 0, width, height)
        crop = image.crop(crop_box).resize((16, 16))
        pixels = list(crop.getdata())
        mean = sum(pixels) / max(len(pixels), 1)
        return tuple(1 if pixel >= mean else 0 for pixel in pixels)
    finally:
        image.close()


def _hash_similarity(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    length = min(len(left), len(right))
    if length <= 0:
        return 0.0
    matches = sum(1 for index in range(length) if left[index] == right[index])
    return matches / length


def _normalize_text(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
