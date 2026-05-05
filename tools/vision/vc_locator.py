from __future__ import annotations

from core.schemas import BoundingBox, LocatedTarget, Observation, PlanStep
from tools.vision.lark_locator import WindowBox, detect_lark_window
from tools.vision.ocr_client import ocr_image
from PIL import Image


VC_STRATEGIES = {
    "vc_sidebar_entry",
    "vc_start_meeting_button",
    "vc_start_meeting_button_fresh",
    "vc_join_meeting_button",
    "vc_meeting_id_input",
    "vc_meeting_title_input",
    "vc_meeting_card_join_button",
    "vc_prejoin_join_button",
    "vc_join_confirm_button",
    "vc_camera_button",
    "vc_microphone_button",
    "vc_join_camera_button",
    "vc_join_microphone_click_button",
    "vc_join_microphone_button",
    "vc_start_camera_button",
    "vc_start_microphone_button",
    "vc_toggle_camera_button",
    "vc_toggle_microphone_button",
    "vc_leave_button",
    "vc_permission_allow_button",
    "vc_account_switch_modal",
}


def is_vc_strategy(strategy: str) -> bool:
    return strategy in VC_STRATEGIES


def is_vc_step(step: PlanStep) -> bool:
    strategy = str(step.metadata.get("locator_strategy") or _strategy_from_step(step) or "")
    return is_vc_strategy(strategy)


def locate_vc_target(observation: Observation, step: PlanStep) -> LocatedTarget | None:
    strategy = str(step.metadata.get("locator_strategy") or _strategy_from_step(step) or "")
    if not is_vc_strategy(strategy):
        return None

    if step.metadata.get("skip_if_vc_device_state_matches"):
        skip_reason = _vc_device_state_skip_reason(observation, step)
        if skip_reason:
            return LocatedTarget(
                step_id=step.id,
                target_description=step.target_description,
                source="cv",
                confidence=0.0,
                reason=skip_reason,
                warnings=[],
                recommended_action="skip",
                metadata={"strategy": strategy, "skip_reason": "vc_device_state_already_matches"},
            )

    if step.metadata.get("skip_if_vc_in_meeting"):
        skip_reason = _vc_in_meeting_skip_reason(observation)
        if skip_reason:
            return LocatedTarget(
                step_id=step.id,
                target_description=step.target_description,
                source="cv",
                confidence=0.0,
                reason=skip_reason,
                warnings=[],
                recommended_action="skip",
                metadata={"strategy": strategy, "skip_reason": "vc_already_in_meeting"},
            )

    window = detect_vc_window(observation.screenshot_path, strategy)
    if window is None:
        return None

    ocr_bbox = _text_bbox_for_strategy(observation.screenshot_path, window, strategy)
    if ocr_bbox is not None:
        return LocatedTarget(
            step_id=step.id,
            target_description=step.target_description,
            source="ocr",
            bbox=ocr_bbox,
            center=ocr_bbox.center(),
            confidence=0.93,
            reason=f"Located by VC-specific OCR strategy: {strategy}.",
            metadata={
                "strategy": strategy,
                "window_bbox": {"x1": window.x1, "y1": window.y1, "x2": window.x2, "y2": window.y2},
                "locator_scope": "vc",
                "locator_priority": "ocr_text",
            },
        )

    if step.metadata.get("require_lark_locator"):
        return None

    bbox = _bbox_for_strategy(window, strategy)
    if bbox is None:
        return None
    return LocatedTarget(
        step_id=step.id,
        target_description=step.target_description,
        source="cv",
        bbox=bbox,
        center=bbox.center(),
        confidence=0.82,
        reason=f"Located by VC-specific window-relative layout: {strategy}.",
        metadata={
            "strategy": strategy,
            "window_bbox": {"x1": window.x1, "y1": window.y1, "x2": window.x2, "y2": window.y2},
            "locator_scope": "vc",
        },
    )


def vc_strategy_bbox_from_screenshot(screenshot_path: str, strategy: str) -> BoundingBox | None:
    if not is_vc_strategy(strategy):
        return None
    window = detect_vc_window(screenshot_path, strategy)
    if window is None:
        return None
    ocr_bbox = _text_bbox_for_strategy(screenshot_path, window, strategy)
    if ocr_bbox is not None:
        return ocr_bbox
    return _bbox_for_strategy(window, strategy)


def detect_vc_window(screenshot_path: str, strategy: str | None = None) -> WindowBox | None:
    # Keep VC window selection behind a product-specific boundary. Today this
    # delegates to the existing Feishu surface detector; future VC-only window
    # heuristics can change here without touching IM/Docs/Calendar.
    if strategy in {"vc_toggle_camera_button", "vc_toggle_microphone_button"}:
        toolbar_window = _floating_meeting_toolbar_window(screenshot_path)
        if toolbar_window is not None:
            return toolbar_window
    if strategy in {"vc_camera_button", "vc_microphone_button", "vc_leave_button"}:
        meeting_window = _os_meeting_window()
        if meeting_window is not None:
            return meeting_window
    return detect_lark_window(screenshot_path)


def detect_vc_meeting_window() -> WindowBox | None:
    return _os_meeting_window()


def _strategy_from_step(step: PlanStep) -> str | None:
    if step.id == "open_vc":
        return "vc_sidebar_entry"
    if step.id == "click_vc_start_meeting":
        return "vc_start_meeting_button"
    if step.id == "click_vc_join_meeting":
        return "vc_join_meeting_button"
    if step.id == "type_vc_meeting_id":
        return "vc_meeting_id_input"
    if step.id == "type_vc_meeting_title":
        return "vc_meeting_title_input"
    if step.id == "enter_started_meeting":
        return "vc_meeting_card_join_button"
    if step.id == "confirm_start_meeting":
        return "vc_prejoin_join_button"
    if step.id == "confirm_join_meeting":
        return "vc_join_confirm_button"
    if step.id == "set_vc_camera_state":
        return "vc_camera_button"
    if step.id == "set_vc_mic_state":
        return "vc_microphone_button"
    if step.id == "allow_vc_permission":
        return "vc_permission_allow_button"
    if step.id == "dismiss_vc_account_modal":
        return "vc_account_switch_modal"
    return None


def _bbox_for_strategy(window: WindowBox, strategy: str) -> BoundingBox | None:
    x, y, w, h = window.x1, window.y1, window.width, window.height
    if strategy == "vc_sidebar_entry":
        return _clamp(BoundingBox(x1=x + 20, y1=y + 500, x2=x + min(270, w - 25), y2=y + 575), window)
    if strategy in {"vc_start_meeting_button", "vc_start_meeting_button_fresh"}:
        return _clamp(BoundingBox(x1=x + int(w * 0.36), y1=y + int(h * 0.28), x2=x + int(w * 0.55), y2=y + int(h * 0.42)), window)
    if strategy == "vc_join_meeting_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.56), y1=y + int(h * 0.28), x2=x + int(w * 0.75), y2=y + int(h * 0.42)), window)
    if strategy == "vc_meeting_id_input":
        return _clamp(BoundingBox(x1=x + int(w * 0.43), y1=y + int(h * 0.10), x2=x + int(w * 0.48), y2=y + int(h * 0.16)), window)
    if strategy == "vc_meeting_title_input":
        return _clamp(BoundingBox(x1=x + int(w * 0.57), y1=y + int(h * 0.165), x2=x + int(w * 0.71), y2=y + int(h * 0.190)), window)
    if strategy == "vc_meeting_card_join_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.64), y1=y + int(h * 0.42), x2=x + int(w * 0.96), y2=y + int(h * 0.74)), window)
    if strategy == "vc_prejoin_join_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.40), y1=y + int(h * 0.70), x2=x + int(w * 0.60), y2=y + int(h * 0.80)), window)
    if strategy == "vc_join_confirm_button":
        return _clamp(BoundingBox(x1=x2 - 280, y1=y2 - 155, x2=x2 - 55, y2=y2 - 55), window)
    if strategy == "vc_camera_button":
        if _looks_like_mini_meeting_window(window):
            return _clamp(BoundingBox(x1=x + int(w * 0.54), y1=y + int(h * 0.36), x2=x + int(w * 0.70), y2=y + int(h * 0.82)), window)
        return _clamp(BoundingBox(x1=x + int(w * 0.42), y1=y + h - 125, x2=x + int(w * 0.49), y2=y + h - 55), window)
    if strategy == "vc_microphone_button":
        if _looks_like_mini_meeting_window(window):
            return _clamp(BoundingBox(x1=x + int(w * 0.32), y1=y + int(h * 0.36), x2=x + int(w * 0.48), y2=y + int(h * 0.82)), window)
        return _clamp(BoundingBox(x1=x + int(w * 0.33), y1=y + h - 125, x2=x + int(w * 0.40), y2=y + h - 55), window)
    if strategy == "vc_join_microphone_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.260), y1=y + h - 85, x2=x + int(w * 0.290), y2=y + h - 35), window)
    if strategy == "vc_join_microphone_click_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.305), y1=y + h - 85, x2=x + int(w * 0.335), y2=y + h - 35), window)
    if strategy == "vc_join_camera_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.325), y1=y + h - 85, x2=x + int(w * 0.355), y2=y + h - 35), window)
    if strategy == "vc_start_microphone_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.305), y1=y + h - 85, x2=x + int(w * 0.335), y2=y + h - 35), window)
    if strategy == "vc_start_camera_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.370), y1=y + h - 85, x2=x + int(w * 0.400), y2=y + h - 35), window)
    if strategy == "vc_toggle_microphone_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.31), y1=y + int(h * 0.44), x2=x + int(w * 0.45), y2=y + int(h * 0.88)), window)
    if strategy == "vc_toggle_camera_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.55), y1=y + int(h * 0.44), x2=x + int(w * 0.69), y2=y + int(h * 0.88)), window)
    if strategy == "vc_leave_button":
        if _looks_like_mini_meeting_window(window):
            return _clamp(BoundingBox(x1=x + int(w * 0.76), y1=y + int(h * 0.36), x2=x + int(w * 0.96), y2=y + int(h * 0.82)), window)
        return _clamp(BoundingBox(x1=x + int(w * 0.72), y1=y + h - 125, x2=x + int(w * 0.84), y2=y + h - 55), window)
    if strategy == "vc_permission_allow_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.52), y1=y + int(h * 0.58), x2=x + int(w * 0.72), y2=y + int(h * 0.70)), window)
    return None


def _os_meeting_window() -> WindowBox | None:
    try:
        from tools.desktop.window_manager import WindowManager
    except Exception:
        return None
    manager = WindowManager()
    hwnd = manager.find_lark_meeting_window()
    rect = manager.window_rect(hwnd) if hwnd else None
    if not rect:
        return None
    left, top, right, bottom = rect
    if right - left < 80 or bottom - top < 50:
        return None
    return WindowBox(x1=left, y1=top, x2=right, y2=bottom)


def _looks_like_mini_meeting_window(window: WindowBox) -> bool:
    return window.width <= 700 and window.height <= 260


def _floating_meeting_toolbar_window(screenshot_path: str) -> WindowBox | None:
    try:
        image = Image.open(screenshot_path).convert("RGB")
    except Exception:
        return None
    try:
        width, height = image.size
        red_pixels: set[tuple[int, int]] = set()
        x_start = int(width * 0.70)
        x_end = width
        y_end = max(220, int(height * 0.18))
        for y in range(0, min(height, y_end), 2):
            for x in range(x_start, x_end, 2):
                r, g, b = image.getpixel((x, y))
                if r >= 180 and g <= 135 and b <= 135 and r - g >= 45 and r - b >= 45:
                    red_pixels.add((x, y))
        if not red_pixels:
            return None

        seen: set[tuple[int, int]] = set()
        best: tuple[int, int, int, int, int] | None = None
        for pixel in list(red_pixels):
            if pixel in seen:
                continue
            stack = [pixel]
            seen.add(pixel)
            xs: list[int] = []
            ys: list[int] = []
            while stack:
                px, py = stack.pop()
                xs.append(px)
                ys.append(py)
                for nx, ny in ((px + 2, py), (px - 2, py), (px, py + 2), (px, py - 2)):
                    neighbor = (nx, ny)
                    if neighbor in red_pixels and neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
            if len(xs) < 12:
                continue
            component = (len(xs), min(xs), min(ys), max(xs), max(ys))
            if best is None or component[0] > best[0]:
                best = component
        if best is None:
            return None
        _count, min_x, min_y, max_x, max_y = best
        center_x = (min_x + max_x) // 2
        center_y = (min_y + max_y) // 2
        return WindowBox(
            x1=max(0, center_x - 335),
            y1=max(0, center_y - 90),
            x2=min(width, center_x + 55),
            y2=min(height, center_y + 45),
        )
    finally:
        image.close()


def _text_bbox_for_strategy(screenshot_path: str, window: WindowBox, strategy: str) -> BoundingBox | None:
    if strategy == "vc_sidebar_entry":
        text_bbox = _sidebar_text_bbox(screenshot_path, window, ("视频会议", "会议", "VC", "Meeting"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 52, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 126, y2=text_bbox.y2 + 24), window)
    if strategy in {"vc_start_meeting_button", "vc_start_meeting_button_fresh"}:
        roi = _clamp(BoundingBox(x1=window.x1 + 240, y1=window.y1 + 120, x2=window.x2 - 120, y2=window.y2 - 160), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("发起会议", "开始会议", "新会议", "Start meeting", "New meeting"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 60, y1=text_bbox.y1 - 28, x2=text_bbox.x2 + 80, y2=text_bbox.y2 + 34), window)
    if strategy == "vc_join_meeting_button":
        roi = _clamp(BoundingBox(x1=window.x1 + 240, y1=window.y1 + 120, x2=window.x2 - 120, y2=window.y2 - 160), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("加入会议", "加入", "Join meeting", "Join"))
        if text_bbox is None:
            return None
        icon_bbox = _find_ocr_text_bbox(
            screenshot_path,
            _clamp(BoundingBox(x1=text_bbox.x1 - 40, y1=text_bbox.y1 - 100, x2=text_bbox.x2 + 40, y2=text_bbox.y1 - 20), window),
            ("+",),
        )
        if icon_bbox is not None:
            return _clamp(BoundingBox(x1=icon_bbox.x1 - 34, y1=icon_bbox.y1 - 34, x2=icon_bbox.x2 + 34, y2=icon_bbox.y2 + 34), window)
        return _clamp(BoundingBox(x1=text_bbox.x1 - 4, y1=text_bbox.y1 - 94, x2=text_bbox.x1 + 76, y2=text_bbox.y1 - 14), window)
    if strategy == "vc_meeting_id_input":
        roi = _clamp(BoundingBox(x1=window.x1 + 220, y1=window.y1 + 120, x2=window.x2 - 160, y2=window.y2 - 180), window)
        text = _normalize_ocr_text(_ocr_text_for_roi(screenshot_path, roi))
        if "发起会议" in text and "预约会议" in text and "网络研讨会" in text:
            return None
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("会议ID", "会议号", "输入会议", "Meeting ID", "meeting id"))
        if text_bbox is None:
            return _bbox_for_strategy(window, strategy)
        return _clamp(BoundingBox(x1=text_bbox.x1 - 16, y1=text_bbox.y1 - 8, x2=text_bbox.x1 + 36, y2=text_bbox.y2 + 10), window)
    if strategy == "vc_meeting_title_input":
        return _bbox_for_strategy(window, strategy)
    if strategy == "vc_meeting_card_join_button":
        roi = _clamp(BoundingBox(x1=window.x1 + int(window.width * 0.50), y1=window.y1 + 120, x2=window.x2 - 20, y2=window.y2 - 120), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("加入会议", "进入会议", "发起会议", "加入", "进入", "Join", "Start"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 54, y1=text_bbox.y1 - 26, x2=text_bbox.x2 + 82, y2=text_bbox.y2 + 30), window)
    if strategy in {"vc_prejoin_join_button", "vc_join_confirm_button"}:
        roi = _clamp(BoundingBox(x1=window.x1 + 180, y1=window.y1 + int(window.height * 0.55), x2=window.x2 - 160, y2=window.y2 - 40), window)
        text = _normalize_ocr_text(_ocr_text_for_roi(screenshot_path, roi))
        if "历史记录" in text and "视频会议" in text:
            return None
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("加入会议", "开始会议", "发起会议", "加入", "开始", "Join", "Start"))
        if text_bbox is None and strategy == "vc_join_confirm_button":
            return _bbox_for_strategy(window, strategy)
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 52, y1=text_bbox.y1 - 24, x2=text_bbox.x2 + 72, y2=text_bbox.y2 + 28), window)
    if strategy == "vc_permission_allow_button":
        roi = _clamp(BoundingBox(x1=window.x1 + 200, y1=window.y1 + 120, x2=window.x2 - 120, y2=window.y2 - 80), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("允许", "同意", "Allow", "OK"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 42, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 52, y2=text_bbox.y2 + 24), window)
    if strategy == "vc_account_switch_modal":
        roi = _clamp(BoundingBox(x1=window.x1 + 120, y1=window.y1 + 80, x2=window.x2 - 120, y2=window.y2 - 80), window)
        text = _normalize_ocr_text(_ocr_text_for_roi(screenshot_path, roi))
        markers = ("登录更多账号", "加入已有企业", "创建新账号", "使用其他方式登录", "moreaccounts", "login")
        if not any(item in text for item in markers):
            return None
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("登录更多账号", "加入已有企业", "创建新账号", "Login"))
        if text_bbox is None:
            return _clamp(
                BoundingBox(
                    x1=window.x1 + int(window.width * 0.30),
                    y1=window.y1 + int(window.height * 0.16),
                    x2=window.x1 + int(window.width * 0.72),
                    y2=window.y1 + int(window.height * 0.66),
                ),
                window,
            )
        return _clamp(BoundingBox(x1=text_bbox.x1 - 40, y1=text_bbox.y1 - 28, x2=text_bbox.x2 + 80, y2=text_bbox.y2 + 36), window)
    if strategy in {"vc_camera_button", "vc_microphone_button", "vc_leave_button"}:
        candidates = {
            "vc_camera_button": ("摄像头", "摄像", "Camera", "Video"),
            "vc_microphone_button": ("麦克风", "麦克", "静音", "Microphone", "Mute", "Mic"),
            "vc_leave_button": ("离开", "结束", "Leave", "End"),
        }[strategy]
        roi = _clamp(BoundingBox(x1=window.x1 + 180, y1=window.y2 - 180, x2=window.x2 - 120, y2=window.y2 - 20), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, candidates)
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 34, y1=text_bbox.y1 - 34, x2=text_bbox.x2 + 34, y2=text_bbox.y2 + 34), window)
    if strategy == "vc_join_microphone_click_button":
        roi = _clamp(BoundingBox(x1=window.x1 + 180, y1=window.y2 - 180, x2=window.x2 - 120, y2=window.y2 - 20), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("麦克风", "麦克", "Microphone", "Mic"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 26, y1=text_bbox.y1 - 10, x2=text_bbox.x1 + 10, y2=text_bbox.y2 + 10), window)
    return None


def _find_ocr_text_bbox(screenshot_path: str, roi: BoundingBox, candidates: tuple[str, ...]) -> BoundingBox | None:
    results = ocr_image(screenshot_path, roi)
    if not results:
        return None
    best: tuple[BoundingBox, float] | None = None
    for bbox, text, confidence in results:
        normalized = _normalize_ocr_text(text)
        if not normalized:
            continue
        for candidate in candidates:
            target = _normalize_ocr_text(candidate)
            if target and (target in normalized or normalized in target):
                score = float(confidence) * min(1.0, max(len(target), 1) / max(len(normalized), 1))
                if best is None or score > best[1]:
                    best = (bbox, score)
    return best[0] if best else None


def _sidebar_text_bbox(screenshot_path: str, window: WindowBox, candidates: tuple[str, ...]) -> BoundingBox | None:
    roi = _clamp(
        BoundingBox(
            x1=max(0, window.x1 - 10),
            y1=window.y1 + 420,
            x2=min(window.x1 + 380, window.x2),
            y2=window.y2 - 50,
        ),
        window,
    )
    return _find_ocr_text_bbox(screenshot_path, roi, candidates)


def _ocr_text_for_roi(screenshot_path: str, roi: BoundingBox) -> str:
    return " ".join(text for _bbox, text, _confidence in ocr_image(screenshot_path, roi))


def _normalize_ocr_text(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _vc_device_state_skip_reason(observation: Observation, step: PlanStep) -> str | None:
    try:
        from tools.vision.vc_error_library import analyze_vc_device_state
    except Exception:
        return None
    camera_off, mic_muted = analyze_vc_device_state(observation, scope=str(step.metadata.get("vc_device_state_scope") or ""))
    desired_camera = step.metadata.get("desired_camera_on")
    if desired_camera is not None and camera_off is not None:
        camera_on = not camera_off
        if camera_on == bool(desired_camera):
            return f"VC camera already matches desired state camera_on={camera_on}."
    desired_mic = step.metadata.get("desired_mic_on")
    if desired_mic is not None and mic_muted is not None:
        mic_on = not mic_muted
        if mic_on == bool(desired_mic):
            return f"VC microphone already matches desired state mic_on={mic_on}."
    return None


def _vc_in_meeting_skip_reason(observation: Observation) -> str | None:
    try:
        from tools.vision.vc_error_library import analyze_vc_screen
    except Exception:
        return None
    state = analyze_vc_screen(observation)
    if state and state.in_meeting_visible:
        return "VC meeting is already active; no extra prejoin confirmation click is needed."
    return None


def _clamp(bbox: BoundingBox, window: WindowBox) -> BoundingBox:
    x1 = max(window.x1, min(bbox.x1, window.x2 - 2))
    y1 = max(window.y1, min(bbox.y1, window.y2 - 2))
    x2 = max(window.x1 + 2, min(bbox.x2, window.x2))
    y2 = max(window.y1 + 2, min(bbox.y2, window.y2))
    if x2 <= x1:
        x2 = min(window.x2, x1 + 2)
        x1 = max(window.x1, x2 - 2)
    if y2 <= y1:
        y2 = min(window.y2, y1 + 2)
        y1 = max(window.y1, y2 - 2)
    return BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2)
