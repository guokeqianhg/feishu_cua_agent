from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageStat

from core.schemas import BoundingBox, Observation
from tools.vision.lark_locator import detect_lark_window
from tools.vision.ocr_client import ocr_image


@dataclass(frozen=True)
class CalendarScreenState:
    wrong_state: str | None
    normalized_text: str
    normalized_title_region: str = ""
    foreground_window_wrong: bool = False
    create_editor_visible: bool = False
    event_detail_visible: bool = False
    attendee_dialog_visible: bool = False
    create_confirmation_visible: bool = False
    create_editor_loading: bool = False
    title_placeholder_visible: bool = False
    expected_title_visible: bool = False
    time_axis_state: str | None = None
    target_event_block_clipped: bool = False
    busy_free_contact_selected: bool = False
    busy_free_overlay_visible: bool = False

    @property
    def is_blocking_error(self) -> bool:
        return self.wrong_state in {
            "not_calendar_screen",
            "create_editor_not_open",
            "event_detail_card_open",
            "add_participant_dialog_open",
            "create_confirmation_open",
            "title_not_entered",
            "time_axis_target_below_readable_area",
            "time_axis_target_above_readable_area",
            "target_event_block_clipped",
            "foreground_window_wrong",
        }


def analyze_calendar_screen(
    observation: Observation | None,
    *,
    expected_title: str | None = None,
    expect_create_editor: bool = False,
) -> CalendarScreenState | None:
    if observation is None:
        return None

    text = _visible_calendar_text(observation)
    normalized = _normalize_text(text)
    lark_window_visible = detect_lark_window(observation.screenshot_path) is not None
    foreground_window_wrong = _looks_like_wrong_foreground(
        observation.window_title or "",
        normalized,
        lark_window_visible,
    )
    title_region_text = _calendar_region_text(observation.screenshot_path, "title")
    normalized_title_region = _normalize_text(title_region_text)

    title_placeholder_visible = any(
        token in normalized_title_region
        for token in ("添加主题", "请输入主题", "subject", "title")
    )
    normalized_expected_title = _normalize_text(expected_title or "")
    expected_title_visible = bool(
        normalized_expected_title
        and (
            normalized_expected_title in normalized_title_region
            or normalized_expected_title in normalized
            or (len(normalized_expected_title) >= 8 and normalized_expected_title[:8] in normalized_title_region)
        )
    )

    create_editor_visible = _looks_like_create_editor(normalized)
    event_detail_visible = _looks_like_event_detail(normalized)
    attendee_dialog_visible = _looks_like_attendee_dialog(normalized)
    create_confirmation_visible = _looks_like_create_confirmation(normalized)
    create_editor_loading = _looks_like_create_editor_loading(observation.screenshot_path, normalized)
    target_event_block_clipped = _calendar_target_event_block_clipped(observation.screenshot_path)

    wrong_state = _first_wrong_state(
        normalized,
        expect_create_editor=expect_create_editor,
        create_editor_visible=create_editor_visible,
        event_detail_visible=event_detail_visible,
        attendee_dialog_visible=attendee_dialog_visible,
        create_confirmation_visible=create_confirmation_visible,
        create_editor_loading=create_editor_loading,
        foreground_window_wrong=foreground_window_wrong,
        target_event_block_clipped=target_event_block_clipped,
        title_placeholder_visible=title_placeholder_visible,
        expected_title_visible=expected_title_visible,
        expected_title=expected_title,
    )
    return CalendarScreenState(
        wrong_state=wrong_state,
        normalized_text=normalized,
        normalized_title_region=normalized_title_region,
        foreground_window_wrong=foreground_window_wrong,
        create_editor_visible=create_editor_visible,
        event_detail_visible=event_detail_visible,
        attendee_dialog_visible=attendee_dialog_visible,
        create_confirmation_visible=create_confirmation_visible,
        create_editor_loading=create_editor_loading,
        target_event_block_clipped=target_event_block_clipped,
        title_placeholder_visible=title_placeholder_visible,
        expected_title_visible=expected_title_visible,
    )


def _visible_calendar_text(observation: Observation) -> str:
    pieces: list[str] = []
    if observation.window_title:
        pieces.append(observation.window_title)
    pieces.extend(observation.ocr_lines or [])

    window = detect_lark_window(observation.screenshot_path)
    roi = None
    if window is not None:
        roi = BoundingBox(x1=window.x1, y1=window.y1, x2=window.x2, y2=window.y2)
    pieces.extend(text for _bbox, text, _confidence in ocr_image(observation.screenshot_path, roi))
    return " ".join(pieces)


def _calendar_region_text(screenshot_path: str, region: str) -> str:
    window = detect_lark_window(screenshot_path)
    roi = _calendar_region_roi(window, region)
    return " ".join(text for _bbox, text, _confidence in ocr_image(screenshot_path, roi))


def _calendar_region_roi(window, region: str) -> BoundingBox | None:
    if window is None:
        return None
    if region == "title":
        return BoundingBox(
            x1=window.x1 + int(window.width * 0.12),
            y1=window.y1 + int(window.height * 0.06),
            x2=window.x1 + int(window.width * 0.56),
            y2=window.y1 + int(window.height * 0.18),
        )
    return None


def _looks_like_create_editor(normalized: str) -> bool:
    markers = (
        "添加主题",
        "添加联系人群或邮箱",
        "参与者权限",
        "飞书视频会议",
        "添加会议室",
        "无需签到",
        "允许创建会议群",
        "保存",
    )
    hits = sum(1 for item in markers if item in normalized)
    return hits >= 3


def _looks_like_event_detail(normalized: str) -> bool:
    markers = (
        "日历助手",
        "发起视频会议",
        "创建会议纪要",
        "提前5分钟",
    )
    return any(item in normalized for item in markers)


def _looks_like_attendee_dialog(normalized: str) -> bool:
    markers = (
        "添加参与者",
        "批量添加",
        "ctrlenter",
        "参与者",
    )
    return sum(1 for item in markers if item in normalized) >= 2 and "保存" not in normalized


def _looks_like_create_confirmation(normalized: str) -> bool:
    return "确定创建日程吗" in normalized or "创建日程吗" in normalized


def _looks_like_create_editor_loading(screenshot_path: str, normalized: str) -> bool:
    if len(normalized) > 8:
        return False
    window = detect_lark_window(screenshot_path)
    if window is None:
        return False
    image = Image.open(screenshot_path).convert("L")
    try:
        crop = image.crop((window.x1, window.y1, window.x2, window.y2))
        stat = ImageStat.Stat(crop)
        return stat.mean[0] >= 238 and stat.stddev[0] <= 38
    finally:
        image.close()


def _first_wrong_state(
    normalized: str,
    *,
    expect_create_editor: bool,
    create_editor_visible: bool,
    event_detail_visible: bool,
    attendee_dialog_visible: bool,
    create_confirmation_visible: bool,
    create_editor_loading: bool,
    foreground_window_wrong: bool,
    target_event_block_clipped: bool,
    title_placeholder_visible: bool,
    expected_title_visible: bool,
    expected_title: str | None,
) -> str | None:
    if foreground_window_wrong:
        return "foreground_window_wrong"
    calendar_hit = any(item in normalized for item in ("日历", "会议室", "预约活动", "创建日程", "calendar"))
    lark_hit = any(item in normalized for item in ("飞书", "feishu", "lark"))
    if lark_hit and not calendar_hit and not create_editor_visible and not event_detail_visible:
        return "not_calendar_screen"
    if event_detail_visible:
        return "event_detail_card_open"
    if attendee_dialog_visible:
        return "add_participant_dialog_open"
    if create_confirmation_visible:
        return "create_confirmation_open"
    if target_event_block_clipped and not expect_create_editor:
        return "target_event_block_clipped"
    if expect_create_editor and create_editor_loading:
        return "create_editor_loading"
    if expect_create_editor and not create_editor_visible:
        return "create_editor_not_open"
    if expect_create_editor and expected_title and not expected_title_visible and title_placeholder_visible:
        return "title_not_entered"
    return None


def _normalize_text(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _looks_like_wrong_foreground(window_title: str, normalized_text: str, lark_window_visible: bool) -> bool:
    title = (window_title or "").lower()
    foreground_markers = (
        "visual studio code",
        "visualstudiocode",
        "vscode",
        "powershell",
        "terminal",
        "codex",
    )
    if any(item in title for item in foreground_markers) or any(item in normalized_text for item in foreground_markers):
        return True
    if any(item in title for item in ("lark",)) or "椋炰功" in title:
        return False
    return not lark_window_visible


def _calendar_target_event_block_clipped(screenshot_path: str) -> bool:
    window = detect_lark_window(screenshot_path)
    if window is None:
        return False
    image = Image.open(screenshot_path).convert("RGB")
    try:
        x1 = max(window.x1, window.x2 - 90)
        x2 = window.x2 - 4
        y1 = window.y1 + int(window.height * 0.35)
        y2 = min(window.y2 - 80, window.y1 + int(window.height * 0.74))
        if x2 <= x1 or y2 <= y1:
            return False
        colored = 0
        for y in range(y1, y2, 3):
            for x in range(x1, x2, 3):
                red, green, blue = image.getpixel((x, y))
                blue_event = blue >= 145 and blue - red >= 45 and blue - green >= 20
                green_busy = green >= 135 and green - red >= 24 and green - blue >= 12
                if blue_event or green_busy:
                    colored += 1
        return colored >= 12
    finally:
        image.close()
