from __future__ import annotations

from dataclasses import dataclass
import re

from PIL import Image

from core.schemas import BoundingBox, Observation
from tools.vision.ocr_client import ocr_image
from tools.vision.vc_locator import detect_vc_meeting_window, detect_vc_window, vc_strategy_bbox_from_screenshot


@dataclass(frozen=True)
class VCScreenState:
    wrong_state: str | None
    normalized_text: str
    vc_visible: bool = False
    prejoin_visible: bool = False
    in_meeting_visible: bool = False
    permission_prompt_visible: bool = False
    device_controls_visible: bool = False
    join_dialog_visible: bool = False
    vc_home_visible: bool = False
    join_button_disabled: bool = False
    meeting_id_not_resolved: bool = False
    meeting_id_not_entered: bool = False
    camera_off: bool | None = None
    mic_muted: bool | None = None

    @property
    def is_blocking_error(self) -> bool:
        return self.wrong_state in {
            "not_vc_screen",
            "vc_home_not_join_dialog",
            "permission_popup",
            "prejoin_not_in_meeting",
            "meeting_id_not_entered",
            "join_button_disabled",
            "meeting_window_not_foreground",
            "meeting_not_joined",
            "device_controls_missing",
            "account_switch_modal",
        }


def analyze_vc_screen(observation: Observation | None) -> VCScreenState | None:
    if observation is None:
        return None
    normalized = _normalize_text(_visible_vc_text(observation))
    title_normalized = _normalize_text(observation.window_title or "")
    meeting_child_window = _looks_like_meeting_child_window(title_normalized) or _looks_like_meeting_child_window(normalized)
    mini_meeting_visible = _mini_meeting_bar_visible(observation, normalized)
    vc_visible = _looks_like_vc(normalized)
    prejoin_visible = _looks_like_prejoin(normalized, meeting_child_window=meeting_child_window)
    in_meeting_visible = _looks_like_in_meeting(normalized) or mini_meeting_visible
    vc_home_visible = _looks_like_vc_home(normalized, meeting_child_window=meeting_child_window)
    join_dialog_visible = _looks_like_join_dialog(normalized, meeting_child_window=meeting_child_window)
    meeting_id_not_resolved = _looks_like_meeting_id_not_resolved(normalized, meeting_child_window=meeting_child_window)
    join_button_disabled = join_dialog_visible and _join_button_disabled(observation)
    meeting_id_not_entered = join_dialog_visible and not _meeting_id_in_input_roi(observation)
    permission_prompt_visible = _looks_like_permission_prompt(normalized)
    device_controls_visible = _device_controls_visible(normalized) or mini_meeting_visible
    camera_off = _camera_off(normalized)
    mic_muted = _mic_muted(normalized)
    if camera_off is None:
        camera_off = _device_off_from_button_roi(observation, "vc_camera_button")
    if mic_muted is None:
        mic_muted = _device_off_from_button_roi(observation, "vc_microphone_button")
    main_camera_states = [
        item
        for item in (
            _main_meeting_device_off(observation, "vc_start_camera_button"),
            _main_meeting_device_off(observation, "vc_join_camera_button"),
        )
        if item is not None
    ]
    if main_camera_states:
        camera_off = any(main_camera_states)
    main_mic_states = [
        item
        for item in (
            _main_meeting_device_off(observation, "vc_start_microphone_button"),
            _main_meeting_device_off(observation, "vc_join_microphone_button"),
        )
        if item is not None
    ]
    if main_mic_states:
        mic_muted = any(main_mic_states)
    wrong_state = _first_wrong_state(
        normalized,
        vc_visible=vc_visible,
        prejoin_visible=prejoin_visible,
        in_meeting_visible=in_meeting_visible,
        vc_home_visible=vc_home_visible,
        permission_prompt_visible=permission_prompt_visible,
        device_controls_visible=device_controls_visible,
        join_dialog_visible=join_dialog_visible,
        join_button_disabled=join_button_disabled,
        meeting_id_not_entered=meeting_id_not_entered,
    )
    return VCScreenState(
        wrong_state=wrong_state,
        normalized_text=normalized,
        vc_visible=vc_visible,
        prejoin_visible=prejoin_visible,
        in_meeting_visible=in_meeting_visible,
        permission_prompt_visible=permission_prompt_visible,
        device_controls_visible=device_controls_visible,
        join_dialog_visible=join_dialog_visible,
        vc_home_visible=vc_home_visible,
        join_button_disabled=join_button_disabled,
        meeting_id_not_resolved=meeting_id_not_resolved,
        meeting_id_not_entered=meeting_id_not_entered,
        camera_off=camera_off,
        mic_muted=mic_muted,
    )


def analyze_vc_device_state(observation: Observation | None, *, scope: str | None = None) -> tuple[bool | None, bool | None]:
    if observation is None:
        return None, None
    if scope == "toggle":
        return (
            _device_off_from_button_roi(observation, "vc_toggle_camera_button"),
            _device_off_from_button_roi(observation, "vc_toggle_microphone_button"),
        )
    state = analyze_vc_screen(observation)
    if state is None:
        return None, None
    return state.camera_off, state.mic_muted


def _visible_vc_text(observation: Observation) -> str:
    pieces: list[str] = []
    if observation.window_title:
        pieces.append(observation.window_title)
    meeting_window = detect_vc_meeting_window()
    if meeting_window is not None:
        meeting_roi = BoundingBox(x1=meeting_window.x1, y1=meeting_window.y1, x2=meeting_window.x2, y2=meeting_window.y2)
        pieces.extend(text for _bbox, text, _confidence in ocr_image(observation.screenshot_path, meeting_roi))
    window = detect_vc_window(observation.screenshot_path)
    roi = BoundingBox(x1=window.x1, y1=window.y1, x2=window.x2, y2=window.y2) if window else None
    pieces.extend(text for _bbox, text, _confidence in ocr_image(observation.screenshot_path, roi))
    return " ".join(pieces)


def _normalize_text(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _looks_like_vc(normalized: str) -> bool:
    markers = (
        "视频会议",
        "视频",
        "会议",
        "发起会议",
        "加入会议",
        "meeting",
        "video",
        "vc",
        "麦克风",
        "摄像头",
    )
    return any(item in normalized for item in markers)


def _looks_like_prejoin(normalized: str, *, meeting_child_window: bool = False) -> bool:
    if _looks_like_start_dialog(normalized, meeting_child_window=meeting_child_window):
        return True
    if _looks_like_vc_home(normalized, meeting_child_window=meeting_child_window):
        return False
    if "\u5f00\u59cb\u4f1a\u8bae" in normalized and any(item in normalized for item in ("\u9ea6\u514b\u98ce", "\u6444\u50cf\u5934")):
        return True
    if "startmeeting" in normalized and any(item in normalized for item in ("microphone", "camera")):
        return True
    if "\u5f00\u59cb\u4f1a\u8bae" in normalized:
        return True
    markers = ("加入会议", "入会", "加入", "会议号", "会议id", "joinmeeting", "join")
    return sum(1 for item in markers if item in normalized) >= 1 and not _looks_like_in_meeting(normalized)


def _looks_like_join_dialog(normalized: str, *, meeting_child_window: bool = False) -> bool:
    has_input_prompt = any(item in normalized for item in ("会议id", "会议号", "输入会议", "meetingid"))
    if not has_input_prompt:
        return False
    if meeting_child_window:
        return True
    return not all(item in normalized for item in ("发起会议", "预约会议", "网络研讨会"))


def _looks_like_meeting_id_not_resolved(normalized: str, *, meeting_child_window: bool = False) -> bool:
    if meeting_child_window:
        return False
    return all(item in normalized for item in ("发起会议", "加入会议", "预约会议", "网络研讨会")) and "会议id" not in normalized


def _looks_like_vc_home(normalized: str, *, meeting_child_window: bool = False) -> bool:
    if meeting_child_window:
        return False
    mojibake_home = "鍙戣捣浼氳" in normalized and "鍔犲叆浼氳" in normalized
    unicode_home = "视频会议" in normalized and "发起会议" in normalized and "加入会议" in normalized
    return mojibake_home or unicode_home


def _looks_like_meeting_child_window(normalized: str) -> bool:
    return any(item in normalized for item in ("飞书会议", "feishumeeting", "larkmeeting"))


def _looks_like_start_dialog(normalized: str, *, meeting_child_window: bool = False) -> bool:
    if not meeting_child_window:
        return False
    if _looks_like_in_meeting(normalized):
        return False
    markers = (
        "的视频会议",
        "发起会议",
        "开始会议",
        "新会议",
        "会议主题",
        "会议名称",
        "麦克风",
        "摄像头",
        "startmeeting",
        "newmeeting",
    )
    return any(item in normalized for item in markers)


def _contains_meeting_id(normalized: str) -> bool:
    return bool(re.search(r"\d{6,}", normalized))


def _meeting_id_in_input_roi(observation: Observation) -> bool:
    window = detect_vc_window(observation.screenshot_path)
    if window is None:
        return False
    roi = _meeting_id_input_roi(window)
    text = _normalize_text(" ".join(item[1] for item in ocr_image(observation.screenshot_path, roi)))
    return _contains_meeting_id(text)


def _meeting_id_input_roi(window) -> BoundingBox:
    return BoundingBox(
        x1=window.x1 + int(window.width * 0.38),
        y1=window.y1 + int(window.height * 0.08),
        x2=window.x1 + int(window.width * 0.86),
        y2=window.y1 + int(window.height * 0.24),
    )


def _join_button_disabled(observation: Observation) -> bool:
    window = detect_vc_window(observation.screenshot_path)
    if window is None:
        return False
    image = Image.open(observation.screenshot_path).convert("RGB")
    try:
        roi = BoundingBox(
            x1=window.x1 + int(window.width * 0.76),
            y1=window.y2 - 130,
            x2=window.x2 - 35,
            y2=window.y2 - 35,
        )
        gray = 0
        blue = 0
        total = 0
        for y in range(max(0, roi.y1), min(image.height, roi.y2), 4):
            for x in range(max(0, roi.x1), min(image.width, roi.x2), 4):
                red, green, blue_channel = image.getpixel((x, y))
                total += 1
                if abs(red - green) <= 18 and abs(green - blue_channel) <= 18 and 135 <= red <= 230:
                    gray += 1
                if blue_channel >= 175 and blue_channel - red >= 80 and blue_channel - green >= 35:
                    blue += 1
        return total > 0 and gray / total >= 0.22 and blue < 8
    finally:
        image.close()


def _looks_like_in_meeting(normalized: str) -> bool:
    if sum(1 for item in ("会议信息", "正在识别说话人", "共享", "安全", "字幕", "ai总结", "布局") if item in normalized) >= 2:
        return True
    markers = (
        "离开会议",
        "结束会议",
        "参会人",
        "共享",
        "静音",
        "解除静音",
        "开启摄像头",
        "关闭摄像头",
        "leave",
        "participants",
        "mute",
        "camera",
    )
    return sum(1 for item in markers if item in normalized) >= 2


def _mini_meeting_bar_visible(observation: Observation, normalized: str) -> bool:
    if detect_vc_meeting_window() is None:
        return False
    if any(item in normalized for item in ("正在讲话", "speaking", "会议信息", "meetinginfo")):
        return True
    title = _normalize_text(observation.window_title or "")
    if not _looks_like_meeting_child_window(title) and not _looks_like_meeting_child_window(normalized):
        return False
    return True


def _looks_like_permission_prompt(normalized: str) -> bool:
    markers = ("权限", "允许", "麦克风", "摄像头", "permission", "allow")
    return ("权限" in normalized or "permission" in normalized or "allow" in normalized) and any(
        item in normalized for item in ("麦克风", "摄像头", "camera", "microphone")
    )


def _device_controls_visible(normalized: str) -> bool:
    if any(item in normalized for item in ("麦克风", "摄像头", "共享", "安全", "字幕", "ai总结")):
        return True
    return any(item in normalized for item in ("麦克风", "静音", "解除静音", "摄像头", "camera", "mute", "microphone"))


def _camera_off(normalized: str) -> bool | None:
    if any(item in normalized for item in ("开启摄像头", "打开摄像头", "startvideo")):
        return True
    if any(item in normalized for item in ("关闭摄像头", "stopvideo")):
        return False
    return None


def _mic_muted(normalized: str) -> bool | None:
    if any(item in normalized for item in ("解除静音", "取消静音", "unmute")):
        return True
    if any(item in normalized for item in ("静音", "mute")):
        return False
    return None


def _device_off_from_button_roi(observation: Observation, strategy: str) -> bool | None:
    bbox = vc_strategy_bbox_from_screenshot(observation.screenshot_path, strategy)
    if bbox is None:
        return None
    image = Image.open(observation.screenshot_path).convert("RGB")
    try:
        red = 0
        total = 0
        for y in range(max(0, bbox.y1), min(image.height, bbox.y2), 2):
            for x in range(max(0, bbox.x1), min(image.width, bbox.x2), 2):
                r, g, b = image.getpixel((x, y))
                total += 1
                if r >= 190 and g <= 95 and b <= 95:
                    red += 1
        if total <= 0:
            return None
        return (red / total) >= 0.012
    finally:
        image.close()


def _main_meeting_mic_muted(observation: Observation) -> bool | None:
    return _main_meeting_device_off(observation, "vc_join_microphone_button")


def _main_meeting_camera_off(observation: Observation) -> bool | None:
    return _main_meeting_device_off(observation, "vc_join_camera_button")


def _main_meeting_device_off(observation: Observation, strategy: str) -> bool | None:
    window = detect_vc_window(observation.screenshot_path)
    if window is None or window.width < 900 or window.height < 600:
        return None
    bbox = vc_strategy_bbox_from_screenshot(observation.screenshot_path, strategy)
    if bbox is None:
        return None
    image = Image.open(observation.screenshot_path).convert("RGB")
    try:
        red = 0
        total = 0
        for y in range(max(0, bbox.y1), min(image.height, bbox.y2), 2):
            for x in range(max(0, bbox.x1), min(image.width, bbox.x2), 2):
                r, g, b = image.getpixel((x, y))
                total += 1
                if r >= 190 and g <= 125 and b <= 125:
                    red += 1
        if total <= 0:
            return None
        return (red / total) >= 0.012
    finally:
        image.close()


def _first_wrong_state(
    normalized: str,
    *,
    vc_visible: bool,
    prejoin_visible: bool,
    in_meeting_visible: bool,
    vc_home_visible: bool,
    permission_prompt_visible: bool,
    device_controls_visible: bool,
    join_dialog_visible: bool,
    join_button_disabled: bool,
    meeting_id_not_entered: bool,
) -> str | None:
    if _looks_like_account_switch_modal(normalized):
        return "account_switch_modal"
    if permission_prompt_visible:
        return "permission_popup"
    if not vc_visible:
        lark_hit = any(item in normalized for item in ("飞书", "feishu", "lark"))
        return "not_vc_screen" if lark_hit or normalized else None
    if meeting_id_not_entered:
        return "meeting_id_not_entered"
    if join_button_disabled:
        return "join_button_disabled"
    if prejoin_visible and not in_meeting_visible:
        return "prejoin_not_in_meeting"
    if vc_visible and not in_meeting_visible and "加入会议" not in normalized and "发起会议" not in normalized:
        return "meeting_not_joined"
    if in_meeting_visible and not device_controls_visible:
        return "device_controls_missing"
    return None


def _looks_like_account_switch_modal(normalized: str) -> bool:
    markers = (
        "\u767b\u5f55\u66f4\u591a\u8d26\u53f7",
        "\u52a0\u5165\u5df2\u6709\u4f01\u4e1a",
        "\u521b\u5efa\u65b0\u8d26\u53f7",
        "\u4f7f\u7528\u5176\u4ed6\u65b9\u5f0f\u767b\u5f55",
        "moreaccounts",
        "login",
    )
    return any(item in normalized for item in markers)
