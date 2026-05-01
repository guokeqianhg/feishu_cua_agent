from __future__ import annotations

from dataclasses import dataclass

from core.schemas import BoundingBox, Observation
from tools.vision.lark_locator import detect_lark_window
from tools.vision.ocr_client import ocr_image


@dataclass(frozen=True)
class DocsScreenState:
    wrong_state: str | None
    normalized_text: str
    normalized_title_region: str = ""
    normalized_body_region: str = ""
    title_placeholder_visible: bool = False
    untitled_marker_visible: bool = False
    expected_title_visible: bool = False
    expected_body_visible: bool = False

    @property
    def is_blocking_error(self) -> bool:
        return self.wrong_state in {
            "access_denied",
            "not_docs_screen",
            "editor_not_ready",
            "share_target_not_confirmed",
            "title_not_entered",
            "title_entered_in_body",
            "body_not_entered",
        }


def analyze_docs_screen(
    observation: Observation | None,
    expected_recipient: str | None = None,
    expected_title: str | None = None,
    expected_body: str | None = None,
) -> DocsScreenState | None:
    if observation is None:
        return None
    text = _visible_docs_text(observation)
    normalized = _normalize_text(text)
    title_region_text = _docs_region_text(observation.screenshot_path, "title")
    body_region_text = _docs_region_text(observation.screenshot_path, "body")
    normalized_title_region = _normalize_text(title_region_text)
    normalized_body_region = _normalize_text(body_region_text)
    title_placeholder_visible = any(token in normalized_title_region for token in ("请输入标题", "输入标题", "title"))
    untitled_marker_visible = any(token in normalized for token in ("未命名文档", "无标题", "untitled"))
    normalized_title = _normalize_text(expected_title or "")
    normalized_body = _normalize_text(expected_body or "")
    expected_title_visible = bool(
        normalized_title
        and (
            normalized_title in normalized_title_region
            or (len(normalized_title) >= 8 and normalized_title[:8] in normalized_title_region)
        )
    )
    expected_body_visible = bool(
        normalized_body
        and (
            normalized_body in normalized_body_region
            or (len(normalized_body) >= 10 and normalized_body[:10] in normalized_body_region)
        )
    )
    wrong_state = _first_wrong_state(
        normalized,
        expected_recipient,
        expected_title,
        expected_body,
        title_placeholder_visible=title_placeholder_visible,
        untitled_marker_visible=untitled_marker_visible,
        expected_title_visible=expected_title_visible,
        expected_body_visible=expected_body_visible,
    )
    return DocsScreenState(
        wrong_state=wrong_state,
        normalized_text=normalized,
        normalized_title_region=normalized_title_region,
        normalized_body_region=normalized_body_region,
        title_placeholder_visible=title_placeholder_visible,
        untitled_marker_visible=untitled_marker_visible,
        expected_title_visible=expected_title_visible,
        expected_body_visible=expected_body_visible,
    )


def _visible_docs_text(observation: Observation) -> str:
    pieces: list[str] = []
    if observation.window_title:
        pieces.append(observation.window_title)
    pieces.extend(observation.ocr_lines or [])
    pieces.extend(text for _bbox, text, _confidence in ocr_image(observation.screenshot_path))
    return " ".join(pieces)


def _docs_region_text(screenshot_path: str, region: str) -> str:
    window = detect_lark_window(screenshot_path)
    roi = _docs_region_roi(window, region)
    return " ".join(text for _bbox, text, _confidence in ocr_image(screenshot_path, roi))


def _docs_region_roi(window, region: str) -> BoundingBox | None:
    if window is None:
        return None
    if region == "title":
        return BoundingBox(
            x1=window.x1 + int(window.width * 0.06),
            y1=window.y1 + int(window.height * 0.15),
            x2=window.x1 + int(window.width * 0.58),
            y2=window.y1 + int(window.height * 0.34),
        )
    if region == "body":
        return BoundingBox(
            x1=window.x1 + int(window.width * 0.08),
            y1=window.y1 + int(window.height * 0.31),
            x2=window.x1 + int(window.width * 0.80),
            y2=window.y1 + int(window.height * 0.72),
        )
    return None


def _first_wrong_state(
    normalized: str,
    expected_recipient: str | None,
    expected_title: str | None,
    expected_body: str | None,
    *,
    title_placeholder_visible: bool,
    untitled_marker_visible: bool,
    expected_title_visible: bool,
    expected_body_visible: bool,
) -> str | None:
    if any(item in normalized for item in ("没有权限访问", "无权限访问", "暂无权限", "accessdenied", "nopermission")):
        return "access_denied"
    docs_hit = any(item in normalized for item in ("飞书云文档", "云文档", "docs", "doc", "wiki", "未命名文档", "请输入标题"))
    lark_hit = any(item in normalized for item in ("飞书", "feishu", "lark"))
    if lark_hit and not docs_hit:
        return "not_docs_screen"
    editor_marker = any(item in normalized for item in ("请输入标题", "未命名文档", "分享", "正文", "插入"))
    loading_marker = any(item in normalized for item in ("加载中", "正在加载", "loading"))
    if loading_marker and not editor_marker:
        return "editor_not_ready"
    if expected_title:
        if expected_title_visible and title_placeholder_visible:
            return "title_entered_in_body"
        if not expected_title_visible and (title_placeholder_visible or untitled_marker_visible):
            return "title_not_entered"
    if expected_body and not expected_body_visible:
        return "body_not_entered"
    if expected_recipient:
        recipient = _normalize_text(expected_recipient)
        share_hit = any(item in normalized for item in ("分享", "共享", "邀请", "协作者", "share", "invite"))
        search_hit = any(item in normalized for item in ("搜索", "联系人", "邮箱", "search", "user", "email"))
        if share_hit and search_hit and recipient and recipient not in normalized:
            return "share_target_not_confirmed"
    return None


def _normalize_text(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
