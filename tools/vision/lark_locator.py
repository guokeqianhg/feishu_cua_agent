from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import calendar
import re

from PIL import Image

from core.schemas import BoundingBox, LocatedTarget, Observation, PlanStep
from tools.desktop.window_manager import WindowManager
from tools.vision.ocr_client import ocr_image


@dataclass(frozen=True)
class WindowBox:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1


def locate_lark_target(observation: Observation, step: PlanStep) -> LocatedTarget | None:
    strategy = str(step.metadata.get("locator_strategy") or "")
    if not strategy:
        strategy = _strategy_from_step(step)
    if not strategy:
        return None
    if _is_vc_strategy_name(strategy):
        return None
    if step.metadata.get("skip_if_event_date_visible") and _calendar_target_date_visible(observation.screenshot_path, step):
        return None
    if step.metadata.get("skip_if_calendar_busy_free_visible") and _calendar_target_busy_free_visible(
        observation.screenshot_path,
        step,
    ):
        return LocatedTarget(
            step_id=step.id,
            target_description=step.target_description,
            source="cv",
            confidence=0.0,
            reason="Calendar busy/free contact is already selected and target time axis is readable; skip duplicate click.",
            warnings=[],
            recommended_action="skip",
            metadata={"strategy": strategy, "skip_reason": "already_selected_contact_result"},
        )
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
    if step.metadata.get("skip_if_docs_share_recipient_ready_for_send"):
        window = _window_for_strategy(observation.screenshot_path, strategy)
        if window is not None and _docs_share_recipient_ready_for_send(observation.screenshot_path, window, step):
            return LocatedTarget(
                step_id=step.id,
                target_description=step.target_description,
                source="cv",
                confidence=0.0,
                reason="Docs share recipient is already selected and the footer Send button is available; skip duplicate add-recipient click.",
                warnings=[],
                recommended_action="skip",
                metadata={"strategy": strategy, "skip_reason": "docs_share_recipient_ready_for_send"},
            )
    if strategy == "search_first_result":
        located = _im_search_result_for_target(observation.screenshot_path, step)
        if located is not None:
            return located

    window = _window_for_strategy(observation.screenshot_path, strategy)
    if window is None:
        return None

    ocr_bbox = _text_bbox_for_strategy(observation.screenshot_path, window, strategy, step)
    if ocr_bbox is not None:
        return LocatedTarget(
            step_id=step.id,
            target_description=step.target_description,
            source="ocr",
            bbox=ocr_bbox,
            center=ocr_bbox.center(),
            confidence=0.93,
            reason=f"Located by OCR-confirmed Feishu UI text: {strategy}.",
            metadata={
                "strategy": strategy,
                "window_bbox": {"x1": window.x1, "y1": window.y1, "x2": window.x2, "y2": window.y2},
                "locator_priority": "ocr_text",
            },
        )
    if step.metadata.get("require_lark_locator"):
        return None

    bbox = _bbox_for_strategy(window, strategy)
    if bbox is None:
        return None
    metadata = {
        "strategy": strategy,
        "window_bbox": {"x1": window.x1, "y1": window.y1, "x2": window.x2, "y2": window.y2},
    }
    if strategy == "calendar_main_time_axis":
        metadata.update(_calendar_time_axis_scroll_metadata(observation.screenshot_path, window, step))
    return LocatedTarget(
        step_id=step.id,
        target_description=step.target_description,
        source="cv",
        bbox=bbox,
        center=bbox.center(),
        confidence=0.82,
        reason=f"Located by screenshot-derived Feishu window-relative layout: {strategy}.",
        metadata=metadata,
    )


def strategy_bbox_from_screenshot(screenshot_path: str, strategy: str) -> BoundingBox | None:
    if _is_vc_strategy_name(strategy):
        return None
    window = _window_for_strategy(screenshot_path, strategy)
    if window is None:
        return None
    ocr_bbox = _text_bbox_for_strategy(screenshot_path, window, strategy, None)
    if ocr_bbox is not None:
        return ocr_bbox
    return _bbox_for_strategy(window, strategy)


def _is_vc_strategy_name(strategy: str) -> bool:
    return strategy.startswith("vc_")


def _window_for_strategy(screenshot_path: str, strategy: str) -> WindowBox | None:
    screenshot_window = detect_lark_window(screenshot_path)
    if strategy in {"calendar_sidebar_entry", "docs_sidebar_entry", "im_sidebar_entry", "vc_sidebar_entry"} and screenshot_window is not None:
        return screenshot_window
    return _os_lark_window_for_strategy(strategy) or screenshot_window


def _os_lark_window_for_strategy(strategy: str) -> WindowBox | None:
    if strategy in {
        "docs_title_input",
        "docs_body_input",
        "docs_share_button",
        "docs_share_recipient_input",
        "docs_share_recipient_result",
        "docs_share_add_recipient_button",
        "docs_share_confirm_button",
    }:
        try:
            manager = WindowManager()
            hwnd = manager.find_docs_editor_window()
            rect = manager.window_rect(hwnd) if hwnd else None
        except Exception:
            rect = None
        if rect:
            left, top, right, bottom = rect
            if right - left >= 450 and bottom - top >= 350:
                return WindowBox(x1=left, y1=top, x2=right, y2=bottom)

    if strategy not in {
        "sidebar_search_box",
        "search_dialog_input",
        "docs_sidebar_entry",
        "calendar_sidebar_entry",
        "calendar_blocking_panel",
        "calendar_main_tab",
        "docs_template_preview_back",
        "docs_transient_overlay",
        "docs_create_button",
        "docs_blank_doc_option",
        "docs_blank_doc_card",
        "docs_title_input",
        "docs_body_input",
        "docs_share_button",
        "docs_share_recipient_input",
        "docs_share_recipient_result",
        "docs_share_add_recipient_button",
        "docs_share_confirm_button",
        "calendar_create_button",
        "calendar_cancel_button",
        "calendar_discard_exit_button",
        "calendar_create_confirm_cancel_button",
        "calendar_create_confirm_button",
        "calendar_add_participant_cancel_button",
        "calendar_meeting_room_back_button",
        "calendar_event_title_input",
        "calendar_event_attendee_input",
        "calendar_attendee_result",
        "calendar_add_participant_confirm_button",
        "calendar_event_time_row",
        "calendar_event_start_date",
        "calendar_date_picker_day",
        "calendar_event_start_time",
        "calendar_event_end_time",
        "calendar_view_date_button",
        "calendar_main_time_axis",
        "calendar_people_search_box",
        "calendar_people_search_result",
        "calendar_subscribed_section_header",
        "calendar_subscribed_contact_row",
        "calendar_save_button",
        "vc_sidebar_entry",
        "vc_start_meeting_button",
        "vc_join_meeting_button",
        "vc_meeting_id_input",
        "vc_meeting_card_join_button",
        "vc_prejoin_join_button",
        "vc_camera_button",
        "vc_microphone_button",
        "vc_leave_button",
        "vc_permission_allow_button",
        "search_first_result",
        "message_input",
        "im_sidebar_entry",
        "im_search_history_tab",
        "im_new_chat_button",
        "im_create_group_option",
        "im_group_member_input",
        "im_group_member_result",
        "im_group_name_input",
        "im_group_create_confirm_button",
        "im_mention_suggestion_row",
        "im_message_row_by_text",
        "im_reaction_button",
        "im_emoji_picker_item",
    }:
        return None
    try:
        rect = WindowManager().window_rect()
    except Exception:
        return None
    if not rect:
        return None
    left, top, right, bottom = rect
    if right - left < 450 or bottom - top < 350:
        return None
    return WindowBox(x1=left, y1=top, x2=right, y2=bottom)


def detect_lark_window(screenshot_path: str) -> WindowBox | None:
    path = Path(screenshot_path)
    if not path.exists():
        return None
    image = Image.open(path).convert("RGB")
    width, height = image.size
    step = 4
    grid_w = (width + step - 1) // step
    grid_h = (height + step - 1) // step
    pixels = image.load()
    mask = [[False for _ in range(grid_w)] for _ in range(grid_h)]
    for gy in range(grid_h):
        y = min(gy * step, height - 1)
        for gx in range(grid_w):
            x = min(gx * step, width - 1)
            red, green, blue = pixels[x, y]
            mask[gy][gx] = _looks_like_lark_surface(red, green, blue)

    visited = [[False for _ in range(grid_w)] for _ in range(grid_h)]
    candidates: list[tuple[int, int, int, int, int]] = []
    for gy in range(grid_h):
        for gx in range(grid_w):
            if visited[gy][gx] or not mask[gy][gx]:
                continue
            component = _flood(mask, visited, gx, gy)
            count, min_x, min_y, max_x, max_y = component
            pixel_w = (max_x - min_x + 1) * step
            pixel_h = (max_y - min_y + 1) * step
            if count < 800 or pixel_w < 420 or pixel_h < 320:
                continue
            candidates.append(component)
    if not candidates:
        return None
    best = _choose_lark_component(candidates, width, height, step)
    _count, min_x, min_y, max_x, max_y = best
    x1, x2 = max(min_x * step - 8, 0), min((max_x + 1) * step + 8, width)
    y1, y2 = max(min_y * step - 8, 0), min((max_y + 1) * step + 8, height)
    if (x2 - x1) < 450 or (y2 - y1) < 350:
        return None
    return WindowBox(x1=x1, y1=y1, x2=x2, y2=y2)


def _choose_lark_component(
    candidates: list[tuple[int, int, int, int, int]],
    screen_width: int,
    screen_height: int,
    step: int,
) -> tuple[int, int, int, int, int]:
    def pixel_size(component: tuple[int, int, int, int, int]) -> tuple[int, int]:
        _count, min_x, min_y, max_x, max_y = component
        return (max_x - min_x + 1) * step, (max_y - min_y + 1) * step

    # When Docs opens in a browser behind the Feishu desktop window, the bright
    # browser page can be the largest component. Prefer a foreground-sized app
    # surface over a nearly full-screen white browser canvas.
    foreground = [
        component
        for component in candidates
        if pixel_size(component)[0] < screen_width * 0.90 or pixel_size(component)[1] < screen_height * 0.90
    ]
    pool = foreground or candidates
    return max(pool, key=lambda component: component[0])


def _flood(mask: list[list[bool]], visited: list[list[bool]], start_x: int, start_y: int) -> tuple[int, int, int, int, int]:
    height = len(mask)
    width = len(mask[0]) if height else 0
    stack = [(start_x, start_y)]
    visited[start_y][start_x] = True
    count = 0
    min_x = max_x = start_x
    min_y = max_y = start_y
    while stack:
        x, y = stack.pop()
        count += 1
        min_x, max_x = min(min_x, x), max(max_x, x)
        min_y, max_y = min(min_y, y), max(max_y, y)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nx < 0 or ny < 0 or nx >= width or ny >= height:
                continue
            if visited[ny][nx] or not mask[ny][nx]:
                continue
            visited[ny][nx] = True
            stack.append((nx, ny))
    return count, min_x, min_y, max_x, max_y


def _looks_like_lark_surface(red: int, green: int, blue: int) -> bool:
    # Feishu desktop surfaces are dominated by low-saturation light gray/white
    # panels. This deliberately ignores dark VS Code and most desktop wallpaper.
    bright = red > 215 and green > 218 and blue > 222
    low_saturation = max(red, green, blue) - min(red, green, blue) < 38
    light_blue_gray = red > 205 and green > 215 and blue > 225 and blue >= red
    return (bright and low_saturation) or light_blue_gray


def _strategy_from_step(step: PlanStep) -> str | None:
    if step.id in {"focus_search"}:
        return "sidebar_search_box"
    if step.id == "open_im":
        return "im_sidebar_entry"
    if step.id in {"type_safe_query", "type_query", "type_history_query"}:
        return "search_dialog_input"
    if step.id == "open_message_results":
        return "im_search_history_tab"
    if step.id == "click_new_chat":
        return "im_new_chat_button"
    if step.id == "click_create_group":
        return "im_create_group_option"
    if step.id == "type_group_member":
        return "im_group_member_input"
    if step.id == "select_group_member":
        return "im_group_member_result"
    if step.id == "type_group_name":
        return "im_group_name_input"
    if step.id == "confirm_create_group":
        return "im_group_create_confirm_button"
    if step.id == "select_mention_candidate":
        return "im_mention_suggestion_row"
    if step.id == "find_reaction_message":
        return "im_message_row_by_text"
    if step.id == "hover_reaction_message":
        return "im_message_row_by_text"
    if step.id == "cancel_reply_context_if_visible":
        return "im_reply_context_bar"
    if step.id == "apply_quick_reaction":
        return "im_quick_reaction_button"
    if step.id == "open_reaction_picker":
        return "im_reaction_button"
    if step.id == "select_reaction_emoji":
        return "im_emoji_picker_item"
    if step.id == "open_docs":
        return "docs_sidebar_entry"
    if step.id == "open_calendar":
        return "calendar_sidebar_entry"
    if step.id == "open_vc":
        return "vc_sidebar_entry"
    if step.id == "click_vc_start_meeting":
        return "vc_start_meeting_button"
    if step.id == "click_vc_join_meeting":
        return "vc_join_meeting_button"
    if step.id == "type_vc_meeting_id":
        return "vc_meeting_id_input"
    if step.id == "enter_started_meeting":
        return "vc_meeting_card_join_button"
    if step.id in {"confirm_start_meeting", "confirm_join_meeting"}:
        return "vc_prejoin_join_button"
    if step.id == "set_vc_camera_state":
        return "vc_camera_button"
    if step.id == "set_vc_mic_state":
        return "vc_microphone_button"
    if step.id == "allow_vc_permission":
        return "vc_permission_allow_button"
    if step.id == "click_calendar_main_tab":
        return "calendar_main_tab"
    if step.id == "close_docs_template_preview":
        return "docs_template_preview_back"
    if step.id == "dismiss_docs_popups":
        return "docs_transient_overlay"
    if step.id == "click_create_doc":
        return "docs_create_button"
    if step.id == "click_blank_doc":
        return "docs_blank_doc_option"
    if step.id == "click_blank_doc_card":
        return "docs_blank_doc_card"
    if step.id == "type_doc_title":
        return "docs_title_input"
    if step.id in {"type_doc_body", "insert_doc_heading_and_list"}:
        return "docs_body_input"
    if step.id == "open_doc_share":
        return "docs_share_button"
    if step.id == "type_doc_share_recipient":
        return "docs_share_recipient_input"
    if step.id == "select_doc_share_recipient":
        return "docs_share_recipient_result"
    if step.id == "add_doc_share_recipient":
        return "docs_share_add_recipient_button"
    if step.id == "confirm_doc_share":
        return "docs_share_confirm_button"
    if step.id == "click_create_event":
        return "calendar_create_button"
    if step.id == "close_calendar_editor":
        return "calendar_cancel_button"
    if step.id == "confirm_calendar_editor_exit":
        return "calendar_discard_exit_button"
    if step.id in {"cancel_calendar_create_confirmation", "cancel_busy_free_create_confirmation"}:
        return "calendar_create_confirm_cancel_button"
    if step.id == "confirm_calendar_create_confirmation":
        return "calendar_create_confirm_button"
    if step.id == "cancel_stale_add_participant_dialog":
        return "calendar_add_participant_cancel_button"
    if step.id == "close_stale_meeting_room_panel":
        return "calendar_meeting_room_back_button"
    if step.id == "type_event_title":
        return "calendar_event_title_input"
    if step.id == "type_event_time":
        return "calendar_event_time_row"
    if step.id == "type_event_start_date":
        return "calendar_event_start_date"
    if step.id == "click_event_start_date":
        return "calendar_event_start_date"
    if step.id == "click_event_start_day":
        return "calendar_date_picker_day"
    if step.id == "click_calendar_view_date":
        return "calendar_view_date_button"
    if step.id in {"scroll_saved_calendar_to_event_time", "scroll_calendar_to_event_time"}:
        return "calendar_main_time_axis"
    if step.id == "click_calendar_view_day":
        return "calendar_date_picker_day"
    if step.id in {"focus_calendar_people_search", "type_busy_free_contact"}:
        return "calendar_people_search_box"
    if step.id == "select_busy_free_contact":
        return "calendar_people_search_result"
    if step.id == "expand_subscribed_calendars":
        return "calendar_subscribed_section_header"
    if step.id == "select_subscribed_busy_free_calendar":
        return "calendar_subscribed_contact_row"
    if step.id == "type_event_start_time":
        return "calendar_event_start_time"
    if step.id == "type_event_end_time":
        return "calendar_event_end_time"
    if step.id == "type_event_attendees":
        return "calendar_event_attendee_input"
    if step.id == "select_event_attendee":
        return "calendar_attendee_result"
    if step.id in {"confirm_add_busy_free_attendee", "confirm_add_event_attendee"}:
        return "calendar_add_participant_confirm_button"
    if step.id == "save_event":
        return "calendar_save_button"
    if step.id == "open_chat":
        return "search_first_result"
    if step.id == "type_message":
        return "message_input"
    return None


def _bbox_for_strategy(window: WindowBox, strategy: str) -> BoundingBox | None:
    x, y, w, h = window.x1, window.y1, window.width, window.height
    modal_like = w < 1150 and h < 950
    if strategy == "calendar_create_confirm_button":
        return None
    if strategy == "sidebar_search_box":
        return _clamp(BoundingBox(x1=x + 20, y1=y + 85, x2=x + min(270, w - 25), y2=y + 145), window)
    if strategy == "search_dialog_input":
        if modal_like:
            return _clamp(BoundingBox(x1=x + 35, y1=y + 30, x2=x + w - 90, y2=y + 90), window)
        return _clamp(BoundingBox(x1=x + 180, y1=y + 105, x2=x + min(1020, w - 170), y2=y + 165), window)
    if strategy == "im_sidebar_entry":
        return _clamp(BoundingBox(x1=x + 20, y1=y + 130, x2=x + min(270, w - 25), y2=y + 205), window)
    if strategy == "docs_sidebar_entry":
        return _clamp(BoundingBox(x1=x + 20, y1=y + 255, x2=x + min(270, w - 25), y2=y + 315), window)
    if strategy == "calendar_sidebar_entry":
        # Calendar sits below Contacts in the global Feishu sidebar. Floating
        # Feishu child windows can make the detected surface start a little
        # higher than the main sidebar, so compensate before clicking.
        top_offset = 681 if y < 220 else 641
        return _clamp(BoundingBox(x1=x + 20, y1=y + top_offset - 35, x2=x + min(270, w - 25), y2=y + top_offset + 35), window)
    if strategy == "vc_sidebar_entry":
        return _clamp(BoundingBox(x1=x + 20, y1=y + 500, x2=x + min(270, w - 25), y2=y + 575), window)
    if strategy == "calendar_sidebar_entry":
        roi = _clamp(BoundingBox(x1=window.x1, y1=window.y1 + 520, x2=window.x1 + 330, y2=window.y2 - 60), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("日历", "鏃ュ巻"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 52, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 116, y2=text_bbox.y2 + 24), window)
    if strategy == "calendar_sidebar_entry":
        text_bbox = _sidebar_text_bbox(screenshot_path, window, ("日历", "鏃ゅ巻"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 52, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 116, y2=text_bbox.y2 + 24), window)
    if strategy == "calendar_main_tab":
        return _clamp(BoundingBox(x1=x + 285, y1=y + 55, x2=x + 390, y2=y + 125), window)
    if strategy == "docs_template_preview_back":
        return None
    if strategy == "docs_transient_overlay":
        return None
    if strategy == "docs_create_button":
        return _clamp(BoundingBox(x1=x + 720, y1=y + 145, x2=x + min(955, w - 45), y2=y + 245), window)
    if strategy == "docs_blank_doc_option":
        right_offset = min(1005, max(760, w - 45))
        return _clamp(BoundingBox(x1=x + 720, y1=y + 105, x2=x + right_offset, y2=y + 170), window)
    if strategy == "docs_blank_doc_card":
        if modal_like:
            return _clamp(BoundingBox(x1=x + 335, y1=y + 205, x2=x + min(680, w - 430), y2=y + 600), window)
        return _clamp(BoundingBox(x1=x + 610, y1=y + 300, x2=x + min(960, w - 260), y2=y + 700), window)
    if strategy == "docs_title_input":
        return _clamp(
            BoundingBox(
                x1=x + int(w * 0.12),
                y1=y + int(h * 0.17),
                x2=x + int(w * 0.40),
                y2=y + int(h * 0.26),
            ),
            window,
        )
    if strategy == "docs_body_input":
        return _clamp(
            BoundingBox(
                x1=x + int(w * 0.18),
                y1=y + int(h * 0.32),
                x2=x + int(w * 0.86),
                y2=y + int(h * 0.74),
            ),
            window,
        )
    if strategy == "docs_share_button":
        return _clamp(BoundingBox(x1=x + 580, y1=y + 130, x2=x + 760, y2=y + 200), window)
    if strategy == "docs_share_recipient_input":
        return _clamp(BoundingBox(x1=x + max(360, w // 4), y1=y + 210, x2=x + min(w - 260, 980), y2=y + 285), window)
    if strategy == "docs_share_recipient_result":
        return _clamp(BoundingBox(x1=x + max(360, w // 4), y1=y + 285, x2=x + min(w - 240, 1000), y2=y + 365), window)
    if strategy == "docs_share_add_recipient_button":
        return _clamp(BoundingBox(x1=x + 1125, y1=y + 345, x2=x + 1210, y2=y + 420), window)
    if strategy == "docs_share_confirm_button":
        return _clamp(BoundingBox(x1=x + 1050, y1=y + 735, x2=x + 1230, y2=y + 825), window)
    if strategy == "calendar_create_button":
        return _clamp(BoundingBox(x1=x + w - 365, y1=y + 55, x2=x + w - 190, y2=y + 115), window)
    if strategy == "calendar_event_title_input":
        return _clamp(BoundingBox(x1=x + 540, y1=y + 90, x2=x + min(1360, w - 570), y2=y + 175), window)
    if strategy == "calendar_event_attendee_input":
        return _clamp(BoundingBox(x1=x + 580, y1=y + 165, x2=x + min(1220, w - 700), y2=y + 230), window)
    if strategy == "calendar_attendee_result":
        return _clamp(BoundingBox(x1=x + 95, y1=y + 230, x2=x + min(760, w - 500), y2=y + 430), window)
    if strategy == "calendar_event_time_row":
        return _clamp(BoundingBox(x1=x + 580, y1=y + 300, x2=x + min(1230, w - 680), y2=y + 365), window)
    if strategy == "calendar_event_start_date":
        return _clamp(BoundingBox(x1=x + 95, y1=y + 300, x2=x + min(280, w - 820), y2=y + 365), window)
    if strategy == "calendar_event_start_time":
        return _clamp(BoundingBox(x1=x + 275, y1=y + 300, x2=x + min(380, w - 720), y2=y + 365), window)
    if strategy == "calendar_event_end_time":
        return _clamp(BoundingBox(x1=x + 395, y1=y + 300, x2=x + min(510, w - 600), y2=y + 365), window)
    if strategy == "calendar_view_date_button":
        return _clamp(BoundingBox(x1=x + 420, y1=y + 135, x2=x + min(760, w - 520), y2=y + 205), window)
    if strategy == "calendar_main_time_axis":
        bbox = _clamp(
            BoundingBox(
                x1=x + max(520, int(w * 0.48)),
                y1=y + 250,
                x2=x + min(w - 80, int(w * 0.82)),
                y2=y + h - 120,
            ),
            window,
        )
        return bbox
    if strategy == "calendar_people_search_box":
        return _clamp(BoundingBox(x1=x + 260, y1=y + h - 330, x2=x + min(620, w - 900), y2=y + h - 265), window)
    if strategy == "calendar_people_search_result":
        return _clamp(BoundingBox(x1=x + 260, y1=y + h - 270, x2=x + min(720, w - 720), y2=y + h - 190), window)
    if strategy == "calendar_subscribed_section_header":
        return None
    if strategy == "calendar_subscribed_contact_row":
        return None
    if strategy == "calendar_create_confirm_button":
        roi = _clamp(BoundingBox(x1=window.x1, y1=window.y1, x2=window.x2, y2=window.y2), window)
        text = _ocr_text_for_roi(screenshot_path, roi)
        normalized = _normalize_ocr_text(text)
        if "确定创建日程吗" not in normalized and "创建日程吗" not in normalized:
            return None
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("确定", "Confirm", "OK"))
        if text_bbox is not None:
            return _clamp(BoundingBox(x1=text_bbox.x1 - 44, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 44, y2=text_bbox.y2 + 22), window)
        return _clamp(BoundingBox(x1=window.x1 + int(window.width * 0.63), y1=window.y1 + int(window.height * 0.52), x2=window.x1 + int(window.width * 0.70), y2=window.y1 + int(window.height * 0.58)), window)
    if strategy == "calendar_save_button":
        return _clamp(BoundingBox(x1=x + min(1210, w - 730), y1=y + h - 105, x2=x + min(1345, w - 595), y2=y + h - 45), window)
    if strategy == "vc_start_meeting_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.36), y1=y + int(h * 0.28), x2=x + int(w * 0.55), y2=y + int(h * 0.42)), window)
    if strategy == "vc_join_meeting_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.56), y1=y + int(h * 0.28), x2=x + int(w * 0.75), y2=y + int(h * 0.42)), window)
    if strategy == "vc_meeting_id_input":
        return _clamp(BoundingBox(x1=x + int(w * 0.43), y1=y + int(h * 0.10), x2=x + int(w * 0.48), y2=y + int(h * 0.16)), window)
    if strategy == "vc_meeting_card_join_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.64), y1=y + int(h * 0.42), x2=x + int(w * 0.96), y2=y + int(h * 0.74)), window)
    if strategy == "vc_prejoin_join_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.40), y1=y + int(h * 0.70), x2=x + int(w * 0.60), y2=y + int(h * 0.80)), window)
    if strategy == "vc_camera_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.42), y1=y + h - 125, x2=x + int(w * 0.49), y2=y + h - 55), window)
    if strategy == "vc_microphone_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.33), y1=y + h - 125, x2=x + int(w * 0.40), y2=y + h - 55), window)
    if strategy == "vc_leave_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.72), y1=y + h - 125, x2=x + int(w * 0.84), y2=y + h - 55), window)
    if strategy == "vc_permission_allow_button":
        return _clamp(BoundingBox(x1=x + int(w * 0.52), y1=y + int(h * 0.58), x2=x + int(w * 0.72), y2=y + int(h * 0.70)), window)
    if strategy == "search_first_result":
        # 动态计算第一个搜索结果的位置：基于搜索输入框的位置向下偏移
        input_box = _bbox_for_strategy(window, "search_dialog_input")
        if input_box:
            # 搜索结果第一个条目位于搜索框下方，偏移20px，高度约60px
            result_top = input_box.y2 + 20
            result_height = 60
            return _clamp(BoundingBox(
                x1=input_box.x1,
                y1=result_top,
                x2=input_box.x2,
                y2=result_top + result_height
            ), window)
        # fallback到原硬编码位置
        if modal_like:
            return _clamp(BoundingBox(x1=x + 35, y1=y + 205, x2=x + w - 35, y2=y + 305), window)
        return _clamp(BoundingBox(x1=x + 180, y1=y + 185, x2=x + min(1040, w - 170), y2=y + 285), window)
    if strategy == "message_input":
        return _clamp(BoundingBox(x1=x + max(520, w // 2), y1=y + h - 165, x2=x + w - 40, y2=y + h - 45), window)
    if strategy == "im_search_history_tab":
        return _clamp(BoundingBox(x1=x + 210, y1=y + 165, x2=x + 450, y2=y + 225), window)
    if strategy == "im_new_chat_button":
        return _clamp(BoundingBox(x1=x + 210, y1=y + 24, x2=x + 285, y2=y + 92), window)
    if strategy == "im_create_group_option":
        return None
    if strategy == "im_group_member_input":
        return _clamp(BoundingBox(x1=x + 330, y1=y + 405, x2=x + min(860, w - 260), y2=y + 465), window)
    if strategy == "im_group_member_result":
        return _clamp(BoundingBox(x1=x + 330, y1=y + 485, x2=x + min(860, w - 260), y2=y + 575), window)
    if strategy == "im_group_name_input":
        return _clamp(BoundingBox(x1=x + 300, y1=y + 210, x2=x + min(760, w - 260), y2=y + 285), window)
    if strategy == "im_group_create_confirm_button":
        return _clamp(BoundingBox(x1=x + min(1030, w - 260), y1=y + h - 100, x2=x + min(1160, w - 120), y2=y + h - 45), window)
    if strategy == "im_mention_suggestion_row":
        return None
    if strategy == "im_message_row_by_text":
        return _clamp(BoundingBox(x1=x + max(420, w // 3), y1=y + 170, x2=x + w - 45, y2=y + h - 210), window)
    if strategy == "im_reaction_button":
        return _clamp(BoundingBox(x1=x + w - 230, y1=y + h // 2 - 80, x2=x + w - 120, y2=y + h // 2 + 40), window)
    if strategy == "im_quick_reaction_button":
        return None
    if strategy == "im_reply_context_bar":
        return None
    if strategy == "im_emoji_picker_item":
        return _clamp(BoundingBox(x1=x + max(460, w // 2), y1=y + h - 345, x2=x + max(560, w // 2 + 100), y2=y + h - 245), window)
    return None


def _text_bbox_for_strategy(
    screenshot_path: str,
    window: WindowBox,
    strategy: str,
    step: PlanStep | None = None,
) -> BoundingBox | None:
    if strategy == "calendar_discard_exit_button":
        image = Image.open(screenshot_path)
        try:
            full_window = WindowBox(x1=0, y1=0, x2=image.width, y2=image.height)
        finally:
            image.close()
        roi = BoundingBox(x1=0, y1=0, x2=full_window.x2, y2=full_window.y2)
        text = _ocr_text_for_roi(screenshot_path, roi)
        normalized = _normalize_ocr_text(text)
        if "确定退出当前日程编辑吗" not in normalized and "无法保存当前日程" not in normalized:
            return None
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("退出", "离开", "不保存", "Leave", "Discard"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 44, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 44, y2=text_bbox.y2 + 22), full_window)
    if strategy == "calendar_sidebar_entry":
        text_bbox = _sidebar_text_bbox(screenshot_path, window, ("日历", "鏃ゅ巻"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 52, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 116, y2=text_bbox.y2 + 24), window)
    if strategy == "vc_sidebar_entry":
        text_bbox = _sidebar_text_bbox(screenshot_path, window, ("视频会议", "会议", "VC", "Meeting"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 52, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 126, y2=text_bbox.y2 + 24), window)
    if strategy == "vc_start_meeting_button":
        roi = _clamp(BoundingBox(x1=window.x1 + 240, y1=window.y1 + 120, x2=window.x2 - 120, y2=window.y2 - 160), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("发起会议", "开始会议", "新会议", "Start meeting", "New meeting"))
        if text_bbox is None:
            return None
        if strategy == "vc_join_meeting_button":
            return _clamp(BoundingBox(x1=text_bbox.x1 - 80, y1=text_bbox.y1 - 110, x2=text_bbox.x2 + 90, y2=text_bbox.y2 + 48), window)
        return _clamp(BoundingBox(x1=text_bbox.x1 - 60, y1=text_bbox.y1 - 28, x2=text_bbox.x2 + 80, y2=text_bbox.y2 + 34), window)
    if strategy == "vc_join_meeting_button":
        roi = _clamp(BoundingBox(x1=window.x1 + 240, y1=window.y1 + 120, x2=window.x2 - 120, y2=window.y2 - 160), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("加入会议", "加入", "Join meeting", "Join"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 60, y1=text_bbox.y1 - 28, x2=text_bbox.x2 + 80, y2=text_bbox.y2 + 34), window)
    if strategy == "vc_meeting_id_input":
        roi = _clamp(BoundingBox(x1=window.x1 + 220, y1=window.y1 + 120, x2=window.x2 - 160, y2=window.y2 - 180), window)
        text = _normalize_ocr_text(_ocr_text_for_roi(screenshot_path, roi))
        if "发起会议" in text and "预约会议" in text and "网络研讨会" in text:
            return None
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("会议ID", "会议号", "输入会议", "Meeting ID", "meeting id"))
        if text_bbox is None:
            if strategy == "vc_meeting_id_input":
                # Focused input can hide the placeholder from OCR; infer the
                # input line from the confirmed join dialog.
                return _bbox_for_strategy(window, strategy)
            return None
        # Feishu keeps the caret at the left edge of the floating label area.
        # Click that text baseline, not the empty preview panel below it.
        return _clamp(
            BoundingBox(
                x1=text_bbox.x1 - 16,
                y1=text_bbox.y1 - 8,
                x2=text_bbox.x1 + 36,
                y2=text_bbox.y2 + 10,
            ),
            window,
        )
    if strategy == "vc_meeting_card_join_button":
        roi = _clamp(BoundingBox(x1=window.x1 + int(window.width * 0.50), y1=window.y1 + 120, x2=window.x2 - 20, y2=window.y2 - 120), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("加入会议", "进入会议", "发起会议", "加入", "进入", "Join", "Start"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 54, y1=text_bbox.y1 - 26, x2=text_bbox.x2 + 82, y2=text_bbox.y2 + 30), window)
    if strategy == "vc_prejoin_join_button":
        roi = _clamp(BoundingBox(x1=window.x1 + 180, y1=window.y1 + int(window.height * 0.55), x2=window.x2 - 160, y2=window.y2 - 40), window)
        text = _normalize_ocr_text(_ocr_text_for_roi(screenshot_path, roi))
        if "历史记录" in text and "视频会议" in text:
            return None
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("加入会议", "开始会议", "发起会议", "加入", "开始", "Join", "Start"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 52, y1=text_bbox.y1 - 24, x2=text_bbox.x2 + 72, y2=text_bbox.y2 + 28), window)
    if strategy == "vc_permission_allow_button":
        roi = _clamp(BoundingBox(x1=window.x1 + 200, y1=window.y1 + 120, x2=window.x2 - 120, y2=window.y2 - 80), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("允许", "同意", "Allow", "OK"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 42, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 52, y2=text_bbox.y2 + 24), window)
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
    if strategy == "calendar_blocking_panel":
        roi = _clamp(
            BoundingBox(
                x1=window.x1 + int(window.width * 0.35),
                y1=window.y1 + 40,
                x2=window.x2 - 20,
                y2=window.y2 - 40,
            ),
            window,
        )
        text = _ocr_text_for_roi(screenshot_path, roi)
        normalized = _normalize_ocr_text(text)
        markers = (
            "鏃ュ巻鍔╂墜",
            "鍙戣捣瑙嗛浼氳",
            "鍒涘缓浼氳绾",
            "鎻愬墠5鍒嗛挓",
            "纭畾鍒涘缓鏃ョ▼鍚?",
            "鍒涘缓鏃ョ▼鍚?",
            "娣诲姞鍙備笌鑰?",
            "日历助手",
            "发起视频会议",
            "创建会议纪要",
            "提前5分钟",
            "确定创建日程吗",
            "创建日程吗",
            "添加参与者",
        )
        if not any(item in normalized for item in markers):
            return None
        return _clamp(
            BoundingBox(x1=window.x2 - 130, y1=window.y1 + 90, x2=window.x2 - 28, y2=window.y1 + 230),
            window,
        )
    if strategy == "calendar_attendee_result":
        attendees = []
        if step:
            raw_attendees = step.metadata.get("attendees") or []
            attendees = [str(item) for item in raw_attendees if str(item).strip()]
        candidates = tuple(attendees + ["李新元", "鏉庢柊鍏?"])
        roi = _clamp(BoundingBox(x1=window.x1 + 70, y1=window.y1 + 175, x2=window.x1 + 850, y2=window.y1 + 520), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, candidates)
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 68, y1=text_bbox.y1 - 34, x2=text_bbox.x2 + 280, y2=text_bbox.y2 + 36), window)
    if strategy == "calendar_people_search_box":
        roi = _clamp(BoundingBox(x1=window.x1 + 250, y1=window.y2 - 380, x2=window.x1 + 780, y2=window.y2 - 245), window)
        candidates = ["搜索联系人", "公共日历", "联系人", "Search", "李新元"]
        if step:
            raw_attendees = step.metadata.get("attendees") or []
            candidates.extend(str(item) for item in raw_attendees if str(item).strip())
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, tuple(candidates))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 28, y1=text_bbox.y1 - 18, x2=text_bbox.x2 + 260, y2=text_bbox.y2 + 24), window)
    if strategy == "calendar_meeting_room_back_button":
        roi = _clamp(BoundingBox(x1=window.x1, y1=window.y1, x2=window.x1 + min(window.width, 980), y2=window.y2), window)
        text = _ocr_text_for_roi(screenshot_path, roi)
        normalized = _normalize_ocr_text(text)
        if "添加会议室" not in normalized and "没有搜索到可用的会议室" not in normalized:
            return None
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("添加会议室",))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 46, y1=text_bbox.y1 - 24, x2=text_bbox.x1 - 6, y2=text_bbox.y2 + 24), window)
    if strategy == "calendar_people_search_result":
        precise_bbox = _calendar_people_search_result_bbox(screenshot_path, window, step)
        if precise_bbox is not None:
            return precise_bbox
        if step and step.metadata.get("require_lark_locator"):
            return None
        attendees = []
        if step:
            raw_attendees = step.metadata.get("attendees") or []
            attendees = [str(item) for item in raw_attendees if str(item).strip()]
        roi = _clamp(BoundingBox(x1=window.x1 + 250, y1=window.y1 + 180, x2=window.x1 + 850, y2=window.y2 - 80), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, tuple(item for item in attendees if item) + ("李新元", "Search"))
        if text_bbox is None:
            return None
        row_right = min(window.x1 + 780, window.x2 - 20)
        center_y = text_bbox.center()[1]
        return _clamp(BoundingBox(x1=row_right - 58, y1=center_y - 28, x2=row_right - 8, y2=center_y + 28), window)
    if strategy == "calendar_subscribed_section_header":
        return _calendar_subscribed_section_bbox(screenshot_path, window)
    if strategy == "calendar_subscribed_contact_row":
        return _calendar_subscribed_contact_bbox(screenshot_path, window, step)
    if strategy == "docs_template_preview_back":
        roi = _clamp(BoundingBox(x1=window.x1 + 260, y1=window.y1 + 70, x2=window.x1 + 620, y2=window.y1 + 230), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("返回", "模板预览", "使用模板"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 75, y1=text_bbox.y1 - 28, x2=text_bbox.x1 - 12, y2=text_bbox.y2 + 28), window)
    if strategy == "docs_transient_overlay":
        roi = _clamp(BoundingBox(x1=window.x1 + 520, y1=window.y1 + 95, x2=window.x2 - 180, y2=window.y2 - 90), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("大家都在搜", "猜你想搜", "搜索历史"))
        if text_bbox is None:
            return None
        return text_bbox
    if strategy == "docs_create_button":
        roi = _clamp(BoundingBox(x1=window.x1 + 520, y1=window.y1 + 95, x2=window.x2 - 320, y2=window.y1 + 260), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("新建",))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 52, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 90, y2=text_bbox.y2 + 28), window)
    if strategy == "docs_blank_doc_option":
        roi = _clamp(BoundingBox(x1=window.x1 + 520, y1=window.y1 + 80, x2=window.x2 - 260, y2=window.y2 - 90), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("文档",))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 52, y1=text_bbox.y1 - 20, x2=text_bbox.x2 + 120, y2=text_bbox.y2 + 26), window)
    if strategy == "docs_blank_doc_card":
        if window.width < 1250:
            roi = _clamp(BoundingBox(x1=window.x1 + 230, y1=window.y1 + 125, x2=window.x2 - 280, y2=window.y2 - 60), window)
        else:
            roi = _clamp(BoundingBox(x1=window.x1 + 560, y1=window.y1 + 250, x2=window.x2 - 240, y2=window.y2 - 130), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("新建空白文档", "空白文档"))
        if text_bbox is None:
            return None
        text_cx, _text_cy = text_bbox.center()
        plus_cy = text_bbox.y1 - 62
        return _clamp(BoundingBox(x1=text_cx - 54, y1=plus_cy - 54, x2=text_cx + 54, y2=plus_cy + 54), window)
    if strategy == "docs_title_input":
        roi = _clamp(
            BoundingBox(
                x1=window.x1 + int(window.width * 0.06),
                y1=window.y1 + int(window.height * 0.15),
                x2=window.x1 + int(window.width * 0.42),
                y2=window.y1 + int(window.height * 0.32),
            ),
            window,
        )
        text_bbox = _find_ocr_text_bbox(
            screenshot_path,
            roi,
            (
                "\u8bf7\u8f93\u5165\u6807\u9898",
                "\u65e0\u6807\u9898",
                "\u672a\u547d\u540d\u6587\u6863",
                "Untitled",
                "Title",
            ),
        )
        if text_bbox is None:
            return None
        return _clamp(
            BoundingBox(
                x1=max(text_bbox.x1 - 24, roi.x1),
                y1=max(text_bbox.y1 - 18, roi.y1),
                x2=min(text_bbox.x2 + 18, roi.x2),
                y2=min(text_bbox.y2 + 18, roi.y2),
            ),
            window,
        )
    if strategy == "docs_body_input":
        title_bbox = _text_bbox_for_strategy(screenshot_path, window, "docs_title_input", step)
        if title_bbox is not None:
            return _clamp(
                BoundingBox(
                    x1=title_bbox.x1,
                    y1=title_bbox.y2 + 28,
                    x2=min(title_bbox.x2 + 120, window.x2 - 90),
                    y2=min(title_bbox.y2 + 320, window.y2 - 140),
                ),
                window,
            )
        return _bbox_for_strategy(window, "docs_body_input")
    if strategy == "docs_share_button":
        blue_bbox = _docs_share_button_from_pixels(screenshot_path, window)
        if blue_bbox is not None:
            return blue_bbox
        roi = _clamp(BoundingBox(x1=window.x1 + 650, y1=window.y1 + 120, x2=window.x1 + 860, y2=window.y1 + 220), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("分享", "共享", "Share"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 42, y1=text_bbox.y1 - 20, x2=text_bbox.x2 + 52, y2=text_bbox.y2 + 22), window)
    if strategy == "docs_share_recipient_input":
        roi = _clamp(BoundingBox(x1=window.x1 + 70, y1=window.y1 + 235, x2=window.x1 + 820, y2=window.y1 + 470), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("搜索", "添加", "姓名", "邮箱", "联系人"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 28, y1=text_bbox.y1 - 18, x2=text_bbox.x2 + 460, y2=text_bbox.y2 + 24), window)
    if strategy == "docs_share_recipient_result":
        recipient = str(step.metadata.get("share_recipient") or "") if step else ""
        roi = _clamp(BoundingBox(x1=window.x1 + 70, y1=window.y1 + 360, x2=window.x1 + 860, y2=window.y1 + 790), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, tuple(item for item in (recipient, "李新元") if item))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 40, y1=text_bbox.y1 - 20, x2=text_bbox.x2 + 180, y2=text_bbox.y2 + 26), window)
    if strategy == "docs_share_add_recipient_button":
        return _docs_share_add_button_bbox(screenshot_path, window)
    if strategy == "docs_share_confirm_button":
        blue_bbox = _docs_share_confirm_button_from_pixels(screenshot_path, window)
        if blue_bbox is not None:
            return blue_bbox
        roi = _docs_share_confirm_footer_roi(screenshot_path, window)
        if roi is None:
            roi = _clamp(BoundingBox(x1=window.x1 + 520, y1=window.y1 + 690, x2=window.x1 + 880, y2=window.y1 + 900), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("发送", "邀请", "确定", "完成", "Send", "Invite"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 42, y1=text_bbox.y1 - 20, x2=text_bbox.x2 + 52, y2=text_bbox.y2 + 22), window)
    if strategy == "calendar_create_button":
        roi = _clamp(BoundingBox(x1=window.x2 - 380, y1=window.y1 + 35, x2=window.x2 - 20, y2=window.y1 + 140), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("创建日程", "新建日程", "创建"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 26, y1=text_bbox.y1 - 12, x2=text_bbox.x2 + 44, y2=text_bbox.y2 + 12), window)
    if strategy == "calendar_main_tab":
        roi = _clamp(BoundingBox(x1=window.x1 + 240, y1=window.y1 + 45, x2=window.x1 + 520, y2=window.y1 + 150), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("日历",))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 36, y1=text_bbox.y1 - 20, x2=text_bbox.x2 + 54, y2=text_bbox.y2 + 22), window)
    if strategy == "calendar_view_date_button":
        roi = _clamp(BoundingBox(x1=window.x1 + 340, y1=window.y1 + 110, x2=window.x1 + 840, y2=window.y1 + 240), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("2026年4月", "4月"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 40, y1=text_bbox.y1 - 18, x2=text_bbox.x2 + 70, y2=text_bbox.y2 + 22), window)
    if strategy == "calendar_cancel_button":
        roi = _clamp(BoundingBox(x1=window.x1, y1=window.y2 - 160, x2=window.x2, y2=window.y2 - 20), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("离开", "退出", "不保存", "Leave", "Discard"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 36, y1=text_bbox.y1 - 18, x2=text_bbox.x2 + 36, y2=text_bbox.y2 + 18), window)
    if strategy == "calendar_discard_exit_button":
        roi = _clamp(BoundingBox(x1=window.x1, y1=window.y1, x2=window.x2, y2=window.y2), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("离开", "退出", "不保存", "Leave", "Discard"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 44, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 44, y2=text_bbox.y2 + 22), window)
    if strategy == "calendar_create_confirm_cancel_button":
        roi = _clamp(BoundingBox(x1=window.x1, y1=window.y1, x2=window.x2, y2=window.y2), window)
        text = _ocr_text_for_roi(screenshot_path, roi)
        normalized = _normalize_ocr_text(text)
        if "确定创建日程吗" not in normalized and "创建日程吗" not in normalized:
            return None
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("取消", "Cancel"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 44, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 44, y2=text_bbox.y2 + 22), window)
    if strategy == "calendar_create_confirm_button":
        roi = _clamp(BoundingBox(x1=window.x1, y1=window.y1, x2=window.x2, y2=window.y2), window)
        text = _ocr_text_for_roi(screenshot_path, roi)
        normalized = _normalize_ocr_text(text)
        if "确定创建日程吗" not in normalized and "创建日程吗" not in normalized:
            return None
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("确定", "Confirm", "OK"))
        if text_bbox is not None:
            return _clamp(BoundingBox(x1=text_bbox.x1 - 44, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 44, y2=text_bbox.y2 + 22), window)
        return _clamp(BoundingBox(x1=window.x1 + int(window.width * 0.63), y1=window.y1 + int(window.height * 0.52), x2=window.x1 + int(window.width * 0.70), y2=window.y1 + int(window.height * 0.58)), window)
    if strategy == "calendar_add_participant_confirm_button":
        roi = _clamp(BoundingBox(x1=window.x1, y1=window.y1, x2=window.x2, y2=window.y2), window)
        text = _ocr_text_for_roi(screenshot_path, roi)
        normalized = _normalize_ocr_text(text)
        if "添加参与者" not in normalized and "参与者" not in normalized:
            return None
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("确定", "Ctrl+Enter", "Confirm", "OK"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 44, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 44, y2=text_bbox.y2 + 22), window)
    if strategy == "calendar_add_participant_cancel_button":
        roi = _clamp(BoundingBox(x1=window.x1, y1=window.y1, x2=window.x2, y2=window.y2), window)
        text = _ocr_text_for_roi(screenshot_path, roi)
        normalized = _normalize_ocr_text(text)
        if "添加参与者" not in normalized and "参与者" not in normalized:
            return None
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("取消", "Cancel"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 44, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 44, y2=text_bbox.y2 + 22), window)
    if strategy == "calendar_save_button":
        roi = _clamp(BoundingBox(x1=window.x1, y1=window.y2 - 160, x2=window.x2, y2=window.y2 - 20), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("保存",))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 42, y1=text_bbox.y1 - 20, x2=text_bbox.x2 + 42, y2=text_bbox.y2 + 20), window)
    if strategy == "im_sidebar_entry":
        roi = _clamp(BoundingBox(x1=window.x1, y1=window.y1 + 90, x2=window.x1 + 300, y2=window.y1 + 260), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("消息", "聊天"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 44, y1=text_bbox.y1 - 24, x2=text_bbox.x2 + 88, y2=text_bbox.y2 + 24), window)
    if strategy == "im_search_history_tab":
        roi = _clamp(BoundingBox(x1=window.x1 + 150, y1=window.y1 + 140, x2=window.x2 - 160, y2=window.y1 + 280), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("聊天记录", "消息", "相关消息"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 36, y1=text_bbox.y1 - 18, x2=text_bbox.x2 + 42, y2=text_bbox.y2 + 20), window)
    if strategy == "im_create_group_option":
        roi = _clamp(BoundingBox(x1=window.x1 + 40, y1=window.y1 + 50, x2=window.x1 + 520, y2=window.y2 - 40), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("创建群组", "创建群", "发起群聊", "新建群组"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 48, y1=text_bbox.y1 - 20, x2=text_bbox.x2 + 80, y2=text_bbox.y2 + 24), window)
    if strategy == "im_mention_suggestion_row":
        mention_user = str(step.metadata.get("mention_user") or "") if step else ""
        msg = _bbox_for_strategy(window, "message_input")
        if msg is None:
            return None
        roi = _clamp(BoundingBox(x1=msg.x1 - 20, y1=max(window.y1, msg.y1 - 260), x2=msg.x2, y2=max(window.y1 + 80, msg.y1 - 20)), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, tuple(item for item in (mention_user, "李新元") if item))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=roi.x1, y1=text_bbox.y1 - 26, x2=roi.x2, y2=text_bbox.y2 + 30), window)
    if strategy == "im_group_create_confirm_button":
        roi = _clamp(BoundingBox(x1=window.x1, y1=window.y2 - 170, x2=window.x2, y2=window.y2 - 20), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("创建", "确定", "完成"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 42, y1=text_bbox.y1 - 20, x2=text_bbox.x2 + 42, y2=text_bbox.y2 + 20), window)
    if strategy == "im_group_member_input":
        roi = _clamp(BoundingBox(x1=window.x1 + 300, y1=window.y1 + 390, x2=window.x1 + min(window.width, 980), y2=window.y1 + 485), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("搜索联系人、部门和我管理的群组", "搜索联系人", "部门和我管理的群组", "管理的群组"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 34, y1=text_bbox.y1 - 18, x2=text_bbox.x2 + 260, y2=text_bbox.y2 + 24), window)
    if strategy == "im_group_name_input":
        roi = _clamp(BoundingBox(x1=window.x1 + 260, y1=window.y1 + 180, x2=window.x1 + min(window.width, 820), y2=window.y1 + 310), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("输入群名称", "群名称", "选填"))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 34, y1=text_bbox.y1 - 18, x2=text_bbox.x2 + 300, y2=text_bbox.y2 + 24), window)
    if strategy == "im_message_row_by_text":
        return _message_row_bbox_by_text(screenshot_path, window, step)
    if strategy == "im_reply_context_bar":
        return _reply_context_bbox_from_ocr(screenshot_path, window)
    if strategy == "im_quick_reaction_button":
        return _quick_reaction_bbox_from_pixels(screenshot_path, window)
    if strategy == "calendar_date_picker_day":
        return _calendar_date_picker_day_bbox(screenshot_path, window, step)
    return None


def _im_search_result_for_target(screenshot_path: str, step: PlanStep) -> LocatedTarget | None:
    target = str(step.metadata.get("target") or "").strip()
    if not target:
        return None
    window = _window_for_strategy(screenshot_path, "search_first_result")
    if window is None:
        return None
    input_box = _bbox_for_strategy(window, "search_dialog_input")
    if input_box is None:
        return None
    roi = _clamp(
        BoundingBox(
            x1=max(window.x1, input_box.x1 - 20),
            y1=input_box.y2 + 6,
            x2=min(window.x2, input_box.x2 + 40),
            y2=min(window.y2, input_box.y2 + 360),
        ),
        window,
    )
    results = ocr_image(screenshot_path, roi)
    target_norm = _normalize_ocr_text(target)
    best: tuple[BoundingBox, str, float] | None = None
    for bbox, text, confidence in results:
        normalized = _normalize_ocr_text(text)
        if not target_norm or target_norm not in normalized:
            continue
        row_text = _ocr_text_for_roi(
            screenshot_path,
            _clamp(
                BoundingBox(
                    x1=roi.x1,
                    y1=max(roi.y1, bbox.y1 - 24),
                    x2=roi.x2,
                    y2=min(roi.y2, bbox.y2 + 34),
                ),
                window,
            ),
        )
        row_norm = _normalize_ocr_text(row_text)
        if _looks_like_wrong_im_result(row_norm):
            continue
        score = float(confidence)
        if best is None or score > best[2]:
            best = (bbox, row_text or text, score)
    if best is None:
        return LocatedTarget(
            step_id=step.id,
            target_description=step.target_description,
            source="ocr",
            bbox=None,
            center=None,
            confidence=0.0,
            reason=f"OCR did not find allowed IM target {target!r} in search results.",
            warnings=[f"target {target!r} not found in visible IM search results"],
            recommended_action="abort",
            metadata={"strategy": "search_first_result", "target": target, "roi": roi.model_dump()},
        )
    text_bbox, row_text, confidence = best
    row_bbox = _clamp(
        BoundingBox(
            x1=roi.x1,
            y1=max(roi.y1, text_bbox.y1 - 26),
            x2=roi.x2,
            y2=min(roi.y2, text_bbox.y2 + 38),
        ),
        window,
    )
    return LocatedTarget(
        step_id=step.id,
        target_description=step.target_description,
        source="ocr",
        bbox=row_bbox,
        center=_safe_click_in_search_result_row(text_bbox, row_bbox),
        confidence=min(0.98, max(0.86, confidence)),
        reason=f"OCR confirmed IM target row for {target!r}: {row_text!r}.",
        metadata={"strategy": "search_first_result", "target": target, "row_text": row_text, "roi": roi.model_dump()},
    )


def _safe_click_in_search_result_row(text_bbox: BoundingBox, row_bbox: BoundingBox) -> tuple[int, int]:
    _text_cx, text_cy = text_bbox.center()
    x = max(row_bbox.x1 + 42, min(text_bbox.x1 - 28, row_bbox.x2 - 60))
    y = max(row_bbox.y1 + 12, min(text_cy, row_bbox.y2 - 12))
    return (x, y)


def _looks_like_wrong_im_result(normalized_text: str) -> bool:
    wrong_tokens = ("知识问答", "知识库问答", "智能问答", "机器人", "ai助手")
    return any(_normalize_ocr_text(token) in normalized_text for token in wrong_tokens)


def _calendar_people_search_result_bbox(
    screenshot_path: str,
    window: WindowBox,
    step: PlanStep | None,
) -> BoundingBox | None:
    attendees = []
    if step:
        raw_attendees = step.metadata.get("attendees") or []
        attendees = [str(item) for item in raw_attendees if str(item).strip()]
    candidates = tuple(item for item in attendees if item) + ("李新元",)
    roi = _clamp(
        BoundingBox(
            x1=window.x1 + 250,
            y1=max(window.y1 + 250, window.y2 - 285),
            x2=min(window.x1 + 700, window.x2 - 20),
            y2=window.y2 - 120,
        ),
        window,
    )
    text_bbox = _find_ocr_text_bbox(screenshot_path, roi, candidates)
    if text_bbox is None:
        return None
    row_text = _ocr_text_for_roi(
        screenshot_path,
        _clamp(
            BoundingBox(
                x1=max(window.x1, text_bbox.x1 - 65),
                y1=max(window.y1, text_bbox.y1 - 28),
                x2=min(window.x2, text_bbox.x2 + 235),
                y2=min(window.y2, text_bbox.y2 + 28),
            ),
            window,
        ),
    )
    if "订阅中" in row_text or "退订成功" in row_text:
        return None
    if step and step.id == "select_busy_free_contact":
        center_y = text_bbox.center()[1]
        return _clamp(
            BoundingBox(
                x1=max(window.x1, text_bbox.x1 - 76),
                y1=center_y - 28,
                x2=min(window.x2, text_bbox.x2 + 170),
                y2=center_y + 28,
            ),
            window,
        )
    icon_center_x = min(text_bbox.x2 + 155, window.x1 + 585, window.x2 - 35)
    icon_center_y = text_bbox.center()[1]
    if _calendar_search_result_icon_selected(screenshot_path, icon_center_x, icon_center_y):
        return None
    return _clamp(
        BoundingBox(
            x1=icon_center_x - 24,
            y1=icon_center_y - 24,
            x2=icon_center_x + 24,
            y2=icon_center_y + 24,
        ),
        window,
    )


def _calendar_search_result_icon_selected(screenshot_path: str, center_x: int, center_y: int) -> bool:
    path = Path(screenshot_path)
    if not path.exists():
        return False
    image = Image.open(path).convert("RGB")
    try:
        blue = 0
        gray = 0
        for y in range(max(0, center_y - 18), min(image.height, center_y + 19), 2):
            for x in range(max(0, center_x - 18), min(image.width, center_x + 19), 2):
                red, green, blue_channel = image.getpixel((x, y))
                if blue_channel >= 170 and blue_channel - red >= 95 and blue_channel - green >= 45:
                    blue += 1
                if abs(red - green) <= 14 and abs(green - blue_channel) <= 18 and 80 <= red <= 230:
                    gray += 1
        return blue >= 6 and blue > gray * 0.08
    finally:
        image.close()


def _calendar_target_busy_free_visible(screenshot_path: str, step: PlanStep | None) -> bool:
    if step is None:
        return False
    window = detect_lark_window(screenshot_path)
    if window is None:
        return False
    attendees = [str(item).strip() for item in step.metadata.get("attendees", []) if str(item).strip()]
    attendee_tokens: list[str] = []
    for name in attendees:
        normalized_name = _normalize_ocr_text(name)
        if normalized_name:
            attendee_tokens.append(normalized_name)
            if len(normalized_name) >= 2:
                attendee_tokens.append(normalized_name[:2])
    if _calendar_selected_search_result_visible(screenshot_path, window, attendee_tokens):
        return _calendar_time_axis_has_readable_hour(screenshot_path, window, step)
    if _calendar_selected_subscribed_contact_visible(screenshot_path, window, attendee_tokens):
        return _calendar_time_axis_has_readable_hour(screenshot_path, window, step)
    roi = _clamp(
        BoundingBox(
            x1=window.x1 + int(window.width * 0.45),
            y1=window.y1 + 160,
            x2=window.x2 - 45,
            y2=window.y2 - 80,
        ),
        window,
    )
    text = _normalize_ocr_text(_ocr_text_for_roi(screenshot_path, roi))
    return bool(attendee_tokens and any(token in text for token in attendee_tokens))


def _calendar_selected_search_result_visible(screenshot_path: str, window: WindowBox, attendee_tokens: list[str]) -> bool:
    if not attendee_tokens:
        return False
    roi = _clamp(
        BoundingBox(
            x1=window.x1 + 250,
            y1=max(window.y1 + 250, window.y2 - 285),
            x2=min(window.x1 + 700, window.x2 - 20),
            y2=window.y2 - 120,
        ),
        window,
    )
    for bbox, text, confidence in ocr_image(screenshot_path, roi):
        if confidence < 0.35:
            continue
        normalized = _normalize_ocr_text(text)
        if not any(token and token in normalized for token in attendee_tokens):
            continue
        icon_center_x = min(bbox.x2 + 155, window.x1 + 585, window.x2 - 35)
        icon_center_y = bbox.center()[1]
        if _calendar_search_result_icon_selected(screenshot_path, icon_center_x, icon_center_y):
            return True
    return False


def _calendar_selected_subscribed_contact_visible(screenshot_path: str, window: WindowBox, attendee_tokens: list[str]) -> bool:
    if not attendee_tokens:
        return False
    roi = _clamp(
        BoundingBox(
            x1=window.x1 + 250,
            y1=window.y2 - 285,
            x2=min(window.x1 + 700, window.x2 - 20),
            y2=window.y2 - 20,
        ),
        window,
    )
    for bbox, text, confidence in ocr_image(screenshot_path, roi):
        if confidence < 0.35:
            continue
        normalized = _normalize_ocr_text(text)
        if not any(token and token in normalized for token in attendee_tokens):
            continue
        icon_center_x = max(window.x1 + 335, bbox.x1 - 22)
        icon_center_y = bbox.center()[1]
        if _calendar_search_result_icon_selected(screenshot_path, icon_center_x, icon_center_y):
            return True
    return False


def _calendar_time_axis_has_readable_hour(screenshot_path: str, window: WindowBox, step: PlanStep | None) -> bool:
    target_hour = _calendar_target_hour(step)
    if target_hour is None:
        return bool(_calendar_visible_time_axis_hour_marks(screenshot_path, window))
    metadata = _calendar_time_axis_scroll_metadata(screenshot_path, window, step)
    return metadata.get("time_axis_state") in {
        "target_readable",
        "target_visible_without_position",
    }


def _calendar_subscribed_section_bbox(screenshot_path: str, window: WindowBox) -> BoundingBox | None:
    roi = _clamp(
        BoundingBox(
            x1=window.x1 + 250,
            y1=window.y2 - 260,
            x2=min(window.x1 + 650, window.x2 - 20),
            y2=window.y2 - 20,
        ),
        window,
    )
    text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("我订阅的", "Subscribed"))
    if text_bbox is None:
        return None
    # If a subscribed contact is already visible below the header, the section
    # is expanded and clicking the header would collapse it.
    below = _clamp(
        BoundingBox(
            x1=roi.x1,
            y1=text_bbox.y2,
            x2=roi.x2,
            y2=roi.y2,
        ),
        window,
    )
    below_text = _normalize_ocr_text(_ocr_text_for_roi(screenshot_path, below))
    if "李新" in below_text:
        return None
    cx, cy = text_bbox.center()
    return _clamp(BoundingBox(x1=cx - 80, y1=cy - 24, x2=cx + 80, y2=cy + 24), window)


def _calendar_subscribed_contact_bbox(
    screenshot_path: str,
    window: WindowBox,
    step: PlanStep | None,
) -> BoundingBox | None:
    attendees = []
    if step:
        raw_attendees = step.metadata.get("attendees") or []
        attendees = [str(item) for item in raw_attendees if str(item).strip()]
    candidates = tuple(item for item in attendees if item) + ("李新元", "李新")
    roi = _clamp(
        BoundingBox(
            x1=window.x1 + 250,
            y1=window.y2 - 260,
            x2=min(window.x1 + 700, window.x2 - 20),
            y2=window.y2 - 20,
        ),
        window,
    )
    text_bbox = _find_ocr_text_bbox(screenshot_path, roi, candidates)
    if text_bbox is None:
        return None
    icon_center_y = text_bbox.center()[1]
    icon_center_x = max(window.x1 + 335, text_bbox.x1 - 22)
    return _clamp(
        BoundingBox(
            x1=icon_center_x - 22,
            y1=icon_center_y - 22,
            x2=icon_center_x + 22,
            y2=icon_center_y + 22,
        ),
        window,
    )


def _calendar_target_date_visible(screenshot_path: str, step: PlanStep | None) -> bool:
    target = _parse_event_date(step)
    if target is None:
        return False
    window = detect_lark_window(screenshot_path)
    roi = None
    if window is not None:
        roi = BoundingBox(
            x1=window.x1 + int(window.width * 0.34),
            y1=window.y1 + 90,
            x2=window.x2 - 20,
            y2=window.y1 + 260,
        )
    results = ocr_image(screenshot_path, roi)
    normalized = _normalize_ocr_text(" ".join(text for _bbox, text, _confidence in results))
    candidates = (
        f"{target.year}{target.month}{target.day}",
        f"{target.year}{target.month:02d}{target.day:02d}",
        f"{target.month}{target.day}",
        f"{target.month:02d}{target.day:02d}",
    )
    return any(item in normalized for item in candidates)


def _calendar_time_axis_scroll_metadata(
    screenshot_path: str,
    window: WindowBox,
    step: PlanStep | None,
) -> dict:
    target_hour = _calendar_target_hour(step)
    hour_marks = _calendar_visible_time_axis_hour_marks(screenshot_path, window)
    visible_hours = sorted({hour for hour, _center_y in hour_marks})
    metadata = {
        "target_hour": target_hour,
        "visible_hours": visible_hours,
    }
    if target_hour is None or not visible_hours:
        return metadata
    lo = min(visible_hours)
    hi = max(visible_hours)
    viewport_top = window.y1 + 235
    viewport_bottom = window.y2 - 35
    readable_top = viewport_top + int((viewport_bottom - viewport_top) * 0.22)
    readable_bottom = viewport_top + int((viewport_bottom - viewport_top) * 0.72)
    desired_y = viewport_top + int((viewport_bottom - viewport_top) * 0.48)
    target_y = next((center_y for hour, center_y in hour_marks if hour == target_hour), None)
    pixels_per_hour = _calendar_pixels_per_hour(hour_marks)
    metadata.update(
        {
            "readable_top": readable_top,
            "readable_bottom": readable_bottom,
            "desired_y": desired_y,
            "target_hour_y": target_y,
            "pixels_per_hour": pixels_per_hour,
        }
    )
    if target_y is not None:
        delta_y = target_y - desired_y
        if readable_top <= target_y <= readable_bottom:
            metadata["scroll_amount"] = 0
            metadata["time_axis_state"] = "target_readable"
            return metadata
        metadata["scroll_amount"] = _calendar_scroll_amount_from_pixel_delta(delta_y, pixels_per_hour)
        metadata["time_axis_state"] = (
            "target_below_readable_area" if target_y > readable_bottom else "target_above_readable_area"
        )
        return metadata
    if lo <= target_hour <= hi:
        metadata["scroll_amount"] = 0
        metadata["time_axis_state"] = "target_visible_without_position"
    elif target_hour > hi:
        delta = target_hour - hi
        metadata["scroll_amount"] = -max(18, min(160, delta * 30))
        metadata["time_axis_state"] = "target_below_view"
    else:
        delta = lo - target_hour
        metadata["scroll_amount"] = max(18, min(160, delta * 30))
        metadata["time_axis_state"] = "target_above_view"
    return metadata


def _calendar_target_hour(step: PlanStep | None) -> int | None:
    if step is None:
        return None
    raw = str(step.metadata.get("start_time") or step.metadata.get("event_time") or "").strip()
    match = re.search(r"(\d{1,2}):(\d{2})", raw)
    if not match:
        return None
    hour = int(match.group(1))
    if 0 <= hour <= 23:
        return hour
    return None


def _calendar_scroll_amount_from_pixel_delta(delta_y: int, pixels_per_hour: float | None) -> int:
    if abs(delta_y) < 8:
        return 0
    pixels = pixels_per_hour or 70.0
    # Scroll units are not pixels. Estimate from the observed hour-label spacing
    # so any target hour can be moved into a readable band, not just 10:00.
    amount = -round((delta_y / max(pixels, 1.0)) * 30)
    if amount == 0:
        amount = -18 if delta_y > 0 else 18
    return max(-180, min(180, amount))


def _calendar_visible_time_axis_hours(screenshot_path: str, window: WindowBox) -> list[int]:
    return sorted({hour for hour, _center_y in _calendar_visible_time_axis_hour_marks(screenshot_path, window)})


def _calendar_visible_time_axis_hour_marks(screenshot_path: str, window: WindowBox) -> list[tuple[int, int]]:
    roi = _clamp(
        BoundingBox(
            x1=window.x1 + int(window.width * 0.32),
            y1=window.y1 + 235,
            x2=window.x1 + int(window.width * 0.48),
            y2=window.y2 - 35,
        ),
        window,
    )
    marks: list[tuple[int, int]] = []
    for bbox, text, confidence in ocr_image(screenshot_path, roi):
        if confidence < 0.45:
            continue
        match = re.search(r"(\d{1,2})\s*[:：]\s*00", text)
        if not match:
            continue
        hour = int(match.group(1))
        if 0 <= hour <= 23 and hour not in [item[0] for item in marks]:
            marks.append((hour, bbox.center()[1]))
    return sorted(marks, key=lambda item: item[0])


def _calendar_pixels_per_hour(hour_marks: list[tuple[int, int]]) -> float | None:
    deltas: list[float] = []
    for (hour_a, y_a), (hour_b, y_b) in zip(hour_marks, hour_marks[1:]):
        hour_delta = hour_b - hour_a
        y_delta = y_b - y_a
        if hour_delta <= 0 or y_delta <= 0:
            continue
        deltas.append(y_delta / hour_delta)
    if not deltas:
        return None
    deltas.sort()
    return deltas[len(deltas) // 2]


def _reply_context_bbox_from_ocr(screenshot_path: str, window: WindowBox) -> BoundingBox | None:
    roi = _clamp(
        BoundingBox(
            x1=window.x1 + max(420, window.width // 3),
            y1=window.y2 - 260,
            x2=window.x2 - 30,
            y2=window.y2 - 105,
        ),
        window,
    )
    text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("回复", "鍥炲"))
    if text_bbox is None:
        return None
    return _clamp(BoundingBox(x1=text_bbox.x1 - 34, y1=text_bbox.y1 - 18, x2=text_bbox.x2 + 320, y2=text_bbox.y2 + 22), window)


def _quick_reaction_bbox_from_pixels(screenshot_path: str, window: WindowBox) -> BoundingBox | None:
    path = Path(screenshot_path)
    if not path.exists():
        return None
    image = Image.open(path).convert("RGB")
    try:
        message_bbox = _message_row_bbox_by_text(screenshot_path, window)
        roi = _clamp(
            (
                BoundingBox(
                    x1=max(window.x1 + max(420, window.width // 3), message_bbox.x1 - 120),
                    y1=max(window.y1 + 120, message_bbox.y1 - 120),
                    x2=min(window.x2 - 70, message_bbox.x2 + 380),
                    y2=min(window.y2 - 120, message_bbox.y2 + 120),
                )
                if message_bbox is not None
                else BoundingBox(
                    x1=window.x1 + max(460, window.width // 3),
                    y1=window.y1 + 170,
                    x2=window.x2 - 95,
                    y2=window.y2 - 170,
                )
            ),
            window,
        )
        pixels = image.load()
        width, height = image.size
        candidates: list[tuple[int, int, int, int, int]] = []
        visited: set[tuple[int, int]] = set()
        for y in range(max(roi.y1, 0), min(roi.y2, height), 2):
            for x in range(max(roi.x1, 0), min(roi.x2, width), 2):
                if (x, y) in visited or not _looks_like_toolbar_border(*pixels[x, y]):
                    continue
                component = _flood_toolbar_border(pixels, width, height, roi, x, y, visited)
                if component is None:
                    continue
                count, min_x, min_y, max_x, max_y = component
                box_w = max_x - min_x + 1
                box_h = max_y - min_y + 1
                if count >= 12 and 120 <= box_w <= 260 and 30 <= box_h <= 70:
                    candidates.append(component)
        if not candidates:
            if message_bbox is not None:
                cx = min(window.x2 - 120, message_bbox.x2 + 46)
                cy = max(window.y1 + 160, min(message_bbox.y1 - 24, window.y2 - 180))
                return _clamp(BoundingBox(x1=cx - 22, y1=cy - 22, x2=cx + 22, y2=cy + 22), window)
            return None
        if message_bbox is not None:
            target_y = message_bbox.center()[1]
            _count, min_x, min_y, _max_x, max_y = min(
                candidates,
                key=lambda item: (abs(((item[2] + item[4]) // 2) - target_y), -item[0]),
            )
        else:
            _count, min_x, min_y, _max_x, max_y = max(candidates, key=lambda item: (item[2], item[0]))
        button_size = max(28, min(44, (max_y - min_y + 1) - 4))
        return _clamp(
            BoundingBox(
                x1=min_x + 2,
                y1=min_y + 2,
                x2=min_x + 2 + button_size,
                y2=max_y - 2,
            ),
            window,
        )
    finally:
        image.close()


def _message_row_bbox_by_text(screenshot_path: str, window: WindowBox, step: PlanStep | None = None) -> BoundingBox | None:
    roi = _clamp(
        BoundingBox(
            x1=window.x1 + max(360, window.width // 3),
            y1=window.y1 + 160,
            x2=window.x2 - 40,
            y2=window.y2 - 150,
        ),
        window,
    )
    search_text = str(step.metadata.get("search_text") or "") if step else ""
    candidates = tuple(item for item in (search_text, "hello from CUA") if item) or ("hello from CUA",)
    text_bbox = _find_ocr_text_bbox(screenshot_path, roi, candidates)
    if text_bbox is None:
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("CUA-Lark guarded smoke message",))
    if text_bbox is None:
        return None
    return _clamp(BoundingBox(x1=text_bbox.x1 - 40, y1=text_bbox.y1 - 28, x2=text_bbox.x2 + 70, y2=text_bbox.y2 + 34), window)


def _docs_share_button_from_pixels(screenshot_path: str, window: WindowBox) -> BoundingBox | None:
    path = Path(screenshot_path)
    if not path.exists():
        return None
    image = Image.open(path).convert("RGB")
    try:
        roi = _clamp(
            BoundingBox(
                x1=window.x1 + 420,
                y1=window.y1 + 95,
                x2=min(window.x2 - 260, window.x1 + 900),
                y2=window.y1 + 230,
            ),
            window,
        )
        pixels = image.load()
        width, height = image.size
        visited: set[tuple[int, int]] = set()
        candidates: list[tuple[int, int, int, int, int]] = []
        for y in range(max(roi.y1, 0), min(roi.y2, height), 2):
            for x in range(max(roi.x1, 0), min(roi.x2, width), 2):
                if (x, y) in visited or not _looks_like_docs_share_blue(*pixels[x, y]):
                    continue
                component = _flood_color_component(
                    pixels,
                    width,
                    height,
                    roi,
                    x,
                    y,
                    visited,
                    _looks_like_docs_share_blue,
                    max_count=7000,
                )
                if component is None:
                    continue
                count, min_x, min_y, max_x, max_y = component
                box_w = max_x - min_x + 1
                box_h = max_y - min_y + 1
                if count >= 80 and 70 <= box_w <= 180 and 34 <= box_h <= 70:
                    candidates.append(component)
        if not candidates:
            return None
        _count, min_x, min_y, max_x, max_y = max(candidates, key=lambda item: (item[0], item[3] - item[1]))
        return _clamp(BoundingBox(x1=min_x - 6, y1=min_y - 6, x2=max_x + 6, y2=max_y + 6), window)
    finally:
        image.close()


def _docs_share_confirm_button_from_pixels(screenshot_path: str, window: WindowBox) -> BoundingBox | None:
    path = Path(screenshot_path)
    if not path.exists():
        return None
    image = Image.open(path).convert("RGB")
    try:
        roi = _docs_share_confirm_footer_roi(screenshot_path, window)
        if roi is None:
            roi = _clamp(BoundingBox(x1=window.x1 + 520, y1=window.y1 + 690, x2=window.x1 + 880, y2=window.y1 + 900), window)
        return _docs_share_blue_button_bbox_in_roi(image, roi, window)
    finally:
        image.close()


def _docs_share_recipient_ready_for_send(screenshot_path: str, window: WindowBox, step: PlanStep) -> bool:
    _ = step
    return _docs_share_confirm_button_from_pixels(screenshot_path, window) is not None


def _docs_share_add_button_bbox(screenshot_path: str, window: WindowBox) -> BoundingBox | None:
    recipient_roi = _clamp(BoundingBox(x1=window.x1 + 70, y1=window.y1 + 250, x2=window.x1 + 840, y2=window.y1 + 470), window)
    plus_bbox = _find_ocr_text_bbox(screenshot_path, recipient_roi, ("+",))
    if plus_bbox is not None:
        return _clamp(BoundingBox(x1=plus_bbox.x1 - 30, y1=plus_bbox.y1 - 30, x2=plus_bbox.x2 + 30, y2=plus_bbox.y2 + 30), window)
    return _clamp(BoundingBox(x1=window.x1 + 700, y1=window.y1 + 275, x2=window.x1 + 780, y2=window.y1 + 345), window)


def _docs_share_confirm_footer_roi(screenshot_path: str, window: WindowBox) -> BoundingBox | None:
    _ = screenshot_path
    return _clamp(
        BoundingBox(
            x1=window.x1 + 610,
            y1=window.y1 + 720,
            x2=window.x1 + 860,
            y2=window.y1 + 900,
        ),
        window,
    )


def _docs_share_blue_button_bbox_in_roi(image: Image.Image, roi: BoundingBox, window: WindowBox) -> BoundingBox | None:
    pixels = image.load()
    width, height = image.size
    visited: set[tuple[int, int]] = set()
    candidates: list[tuple[int, int, int, int, int]] = []
    for y in range(max(roi.y1, 0), min(roi.y2, height), 2):
        for x in range(max(roi.x1, 0), min(roi.x2, width), 2):
            if (x, y) in visited or not _looks_like_docs_share_blue(*pixels[x, y]):
                continue
            component = _flood_color_component(
                pixels,
                width,
                height,
                roi,
                x,
                y,
                visited,
                _looks_like_docs_share_blue,
                max_count=7000,
            )
            if component is None:
                continue
            count, min_x, min_y, max_x, max_y = component
            box_w = max_x - min_x + 1
            box_h = max_y - min_y + 1
            if count >= 80 and 60 <= box_w <= 200 and 32 <= box_h <= 80:
                candidates.append(component)
    if not candidates:
        return None
    _count, min_x, min_y, max_x, max_y = max(candidates, key=lambda item: (item[0], item[2]))
    return _clamp(BoundingBox(x1=min_x - 6, y1=min_y - 6, x2=max_x + 6, y2=max_y + 6), window)


def _largest_blue_button_bbox(image: Image.Image, roi: BoundingBox, window: WindowBox) -> BoundingBox | None:
    pixels = image.load()
    width, height = image.size
    visited: set[tuple[int, int]] = set()
    candidates: list[tuple[int, int, int, int, int]] = []
    for y in range(max(roi.y1, 0), min(roi.y2, height), 2):
        for x in range(max(roi.x1, 0), min(roi.x2, width), 2):
            if (x, y) in visited or not _looks_like_docs_share_blue(*pixels[x, y]):
                continue
            component = _flood_color_component(
                pixels,
                width,
                height,
                roi,
                x,
                y,
                visited,
                _looks_like_docs_share_blue,
                max_count=7000,
            )
            if component is None:
                continue
            count, min_x, min_y, max_x, max_y = component
            box_w = max_x - min_x + 1
            box_h = max_y - min_y + 1
            if count >= 80 and 60 <= box_w <= 200 and 32 <= box_h <= 80:
                candidates.append(component)
    if not candidates:
        return None
    _count, min_x, min_y, max_x, max_y = max(candidates, key=lambda item: (item[0], item[2]))
    return _clamp(BoundingBox(x1=min_x - 6, y1=min_y - 6, x2=max_x + 6, y2=max_y + 6), window)


def _looks_like_docs_share_blue(red: int, green: int, blue: int) -> bool:
    return 0 <= red <= 110 and 70 <= green <= 180 and 180 <= blue <= 255 and blue - red >= 80 and blue - green >= 35


def _looks_like_toolbar_border(red: int, green: int, blue: int) -> bool:
    return 220 <= red <= 245 and 220 <= green <= 245 and 220 <= blue <= 245 and max(red, green, blue) - min(red, green, blue) <= 24


def _flood_color_component(
    pixels,
    width: int,
    height: int,
    roi: BoundingBox,
    start_x: int,
    start_y: int,
    visited: set[tuple[int, int]],
    predicate,
    max_count: int,
) -> tuple[int, int, int, int, int] | None:
    stack = [(start_x, start_y)]
    visited.add((start_x, start_y))
    count = 0
    min_x = max_x = start_x
    min_y = max_y = start_y
    while stack:
        x, y = stack.pop()
        count += 1
        min_x, max_x = min(min_x, x), max(max_x, x)
        min_y, max_y = min(min_y, y), max(max_y, y)
        if count > max_count:
            return None
        for nx, ny in ((x - 2, y), (x + 2, y), (x, y - 2), (x, y + 2)):
            if nx < roi.x1 or nx >= roi.x2 or ny < roi.y1 or ny >= roi.y2 or nx < 0 or nx >= width or ny < 0 or ny >= height:
                continue
            if (nx, ny) in visited:
                continue
            visited.add((nx, ny))
            if predicate(*pixels[nx, ny]):
                stack.append((nx, ny))
    return count, min_x, min_y, max_x, max_y


def _flood_toolbar_border(
    pixels,
    width: int,
    height: int,
    roi: BoundingBox,
    start_x: int,
    start_y: int,
    visited: set[tuple[int, int]],
) -> tuple[int, int, int, int, int] | None:
    stack = [(start_x, start_y)]
    visited.add((start_x, start_y))
    count = 0
    min_x = max_x = start_x
    min_y = max_y = start_y
    while stack:
        x, y = stack.pop()
        count += 1
        min_x, max_x = min(min_x, x), max(max_x, x)
        min_y, max_y = min(min_y, y), max(max_y, y)
        if count > 2500:
            return None
        for nx, ny in ((x - 2, y), (x + 2, y), (x, y - 2), (x, y + 2)):
            if nx < roi.x1 or nx >= roi.x2 or ny < roi.y1 or ny >= roi.y2 or nx < 0 or nx >= width or ny < 0 or ny >= height:
                continue
            if (nx, ny) in visited:
                continue
            visited.add((nx, ny))
            if _looks_like_toolbar_border(*pixels[nx, ny]):
                stack.append((nx, ny))
    return count, min_x, min_y, max_x, max_y


def _calendar_date_picker_day_bbox(
    screenshot_path: str,
    window: WindowBox,
    step: PlanStep | None,
) -> BoundingBox | None:
    target = _parse_event_date(step)
    if target is None:
        return None

    roi = _clamp(
        BoundingBox(
            x1=window.x1 + 40,
            y1=window.y1 + 110,
            x2=min(window.x2, window.x1 + 900),
            y2=window.y2 - 90,
        ),
        window,
    )
    results = ocr_image(screenshot_path, roi)
    if not results:
        return None

    text_bbox = _calendar_day_bbox_from_headers(results, roi, window, target)
    if text_bbox is None:
        text_bbox = _calendar_day_bbox_from_visible_month(results, roi, window, target)
    if text_bbox is None:
        return None
    cx, cy = text_bbox.center()
    return _clamp(BoundingBox(x1=cx - 28, y1=cy - 28, x2=cx + 28, y2=cy + 28), window)


def _parse_event_date(step: PlanStep | None) -> date | None:
    if step is None:
        return None
    raw = str(step.metadata.get("event_date") or "").strip()
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _find_calendar_picker_header(
    results: list[tuple[BoundingBox, str, float]],
    target: date,
) -> tuple[BoundingBox, str] | None:
    normalized_targets = {
        f"{target.year}年{target.month}月",
        f"{target.year}年{target.month:02d}月",
        f"{target.month}月",
    }
    best: tuple[BoundingBox, str, float] | None = None
    for bbox, text, confidence in results:
        normalized = _normalize_ocr_text(text)
        if not normalized:
            continue
        hit = any(_normalize_ocr_text(item) in normalized for item in normalized_targets)
        if not hit:
            continue
        if best is None or confidence > best[2]:
            best = (bbox, text, float(confidence))
    if best is None:
        return None
    return best[0], best[1]


def _calendar_day_bbox_from_headers(
    results: list[tuple[BoundingBox, str, float]],
    roi: BoundingBox,
    window: WindowBox,
    target: date,
) -> BoundingBox | None:
    best_candidate: tuple[BoundingBox, int, int] | None = None
    for header_bbox, _header_text, _confidence in _calendar_picker_header_candidates(results, target):
        panel = _clamp(
            BoundingBox(
                x1=max(roi.x1, header_bbox.x1 - 60),
                y1=header_bbox.y2 + 20,
                x2=min(roi.x2, header_bbox.x1 + 430),
                y2=min(roi.y2, header_bbox.y2 + 430),
            ),
            window,
        )
        number_boxes = [
            bbox
            for bbox, text, confidence in results
            if confidence >= 0.55
            and panel.x1 <= bbox.x1 <= panel.x2
            and panel.y1 <= bbox.y1 <= panel.y2
            and re.fullmatch(r"\d{1,2}", _normalize_ocr_text(text) or "")
        ]
        x_groups = _cluster_centers([bbox.center()[0] for bbox in number_boxes], tolerance=18)
        y_groups = _cluster_centers([bbox.center()[1] for bbox in number_boxes], tolerance=18)
        if len(x_groups) < 7 or len(y_groups) < 4:
            continue

        x_groups = x_groups[:7]
        first_weekday = date(target.year, target.month, 1).weekday()
        first_col = (first_weekday + 1) % 7  # Feishu date picker uses Sunday-first columns.
        index = first_col + target.day - 1
        target_row = index // 7
        target_col = index % 7
        if target_row >= len(y_groups):
            continue

        expected_x = x_groups[target_col]
        expected_y = y_groups[target_row]
        nearest: tuple[BoundingBox, int] | None = None
        for bbox in number_boxes:
            cx, cy = bbox.center()
            distance = abs(cx - expected_x) + abs(cy - expected_y)
            if nearest is None or distance < nearest[1]:
                nearest = (bbox, distance)
        if nearest is None or nearest[1] > 34:
            continue

        score = len(x_groups) * 10 + min(len(y_groups), 6)
        if best_candidate is None or score > best_candidate[1] or (
            score == best_candidate[1] and header_bbox.y1 > best_candidate[2]
        ):
            best_candidate = (nearest[0], score, header_bbox.y1)
    return best_candidate[0] if best_candidate else None


def _calendar_picker_header_candidates(
    results: list[tuple[BoundingBox, str, float]],
    target: date,
) -> list[tuple[BoundingBox, str, float]]:
    normalized_targets = {
        f"{target.year}年{target.month}月",
        f"{target.year}年{target.month:02d}月",
        f"{target.month}月",
    }
    headers: list[tuple[BoundingBox, str, float]] = []
    for bbox, text, confidence in results:
        normalized = _normalize_ocr_text(text)
        if not normalized:
            continue
        if any(_normalize_ocr_text(item) in normalized for item in normalized_targets):
            headers.append((bbox, text, float(confidence)))
    return sorted(headers, key=lambda item: (item[0].y1, -item[2]))


def _calendar_day_bbox_from_visible_month(
    results: list[tuple[BoundingBox, str, float]],
    roi: BoundingBox,
    window: WindowBox,
    target: date,
) -> BoundingBox | None:
    best_candidate: tuple[BoundingBox, int, int] | None = None
    for header_bbox, _header_text, _confidence, visible_month in _calendar_visible_month_headers(results):
        relation = _calendar_month_relation(visible_month, target)
        if relation not in {"current", "next"}:
            continue
        panel = _clamp(
            BoundingBox(
                x1=max(roi.x1, header_bbox.x1 - 60),
                y1=header_bbox.y2 + 20,
                x2=min(roi.x2, header_bbox.x1 + 430),
                y2=min(roi.y2, header_bbox.y2 + 430),
            ),
            window,
        )
        number_boxes = [
            bbox
            for bbox, text, confidence in results
            if confidence >= 0.55
            and panel.x1 <= bbox.x1 <= panel.x2
            and panel.y1 <= bbox.y1 <= panel.y2
            and re.fullmatch(r"\d{1,2}", _normalize_ocr_text(text) or "")
        ]
        x_groups = _cluster_centers([bbox.center()[0] for bbox in number_boxes], tolerance=18)
        y_groups = _cluster_centers([bbox.center()[1] for bbox in number_boxes], tolerance=18)
        expected = _calendar_expected_grid_position(visible_month, target, relation, x_groups, y_groups)
        if expected is None:
            continue
        expected_x, expected_y = expected
        nearest: tuple[BoundingBox, int] | None = None
        for bbox in number_boxes:
            cx, cy = bbox.center()
            distance = abs(cx - expected_x) + abs(cy - expected_y)
            if nearest is None or distance < nearest[1]:
                nearest = (bbox, distance)
        if nearest is None or nearest[1] > 34:
            continue
        score = len(x_groups) * 10 + min(len(y_groups), 6)
        if best_candidate is None or score > best_candidate[1] or (
            score == best_candidate[1] and header_bbox.y1 > best_candidate[2]
        ):
            best_candidate = (nearest[0], score, header_bbox.y1)
    return best_candidate[0] if best_candidate else None


def _calendar_visible_month_headers(
    results: list[tuple[BoundingBox, str, float]],
) -> list[tuple[BoundingBox, str, float, date]]:
    headers: list[tuple[BoundingBox, str, float, date]] = []
    for bbox, text, confidence in results:
        visible_month = _parse_calendar_header_month(text)
        if visible_month is None:
            continue
        headers.append((bbox, text, float(confidence), visible_month))
    return sorted(headers, key=lambda item: (item[0].y1, -item[2]))


def _parse_calendar_header_month(text: str) -> date | None:
    normalized = _normalize_ocr_text(text)
    match = re.search(r"(\d{4})年(\d{1,2})月", normalized)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        if 1 <= month <= 12:
            return date(year, month, 1)
    return None


def _calendar_month_relation(visible_month: date, target: date) -> str | None:
    if visible_month.year == target.year and visible_month.month == target.month:
        return "current"
    next_year = visible_month.year + (1 if visible_month.month == 12 else 0)
    next_month = 1 if visible_month.month == 12 else visible_month.month + 1
    if next_year == target.year and next_month == target.month:
        return "next"
    return None


def _calendar_expected_grid_position(
    visible_month: date,
    target: date,
    relation: str,
    x_groups: list[int],
    y_groups: list[int],
) -> tuple[int, int] | None:
    if len(x_groups) < 7 or len(y_groups) < 4:
        return None
    x_groups = x_groups[:7]
    first_weekday = date(visible_month.year, visible_month.month, 1).weekday()
    first_col = (first_weekday + 1) % 7  # Sunday-first
    if relation == "current":
        index = first_col + target.day - 1
    else:
        last_day = calendar.monthrange(visible_month.year, visible_month.month)[1]
        last_index = first_col + last_day - 1
        index = last_index + target.day
    target_row = index // 7
    target_col = index % 7
    if target_row >= len(y_groups):
        return None
    return (x_groups[target_col], y_groups[target_row])


def _cluster_centers(values: list[int], tolerance: int) -> list[int]:
    if not values:
        return []
    clusters: list[list[int]] = []
    for value in sorted(values):
        if not clusters or abs(value - clusters[-1][-1]) > tolerance:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return [round(sum(cluster) / len(cluster)) for cluster in clusters]


def _ocr_bbox_for_strategy(screenshot_path: str, window: WindowBox, strategy: str) -> BoundingBox | None:
    if strategy == "docs_blank_doc_card":
        roi = _clamp(BoundingBox(x1=window.x1 + 560, y1=window.y1 + 250, x2=window.x2 - 240, y2=window.y2 - 130), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("新建空白文档", "空白文档"))
        if text_bbox is None:
            return None
        return _clamp(
            BoundingBox(
                x1=text_bbox.x1 - 40,
                y1=text_bbox.y1 - 16,
                x2=text_bbox.x2 + 40,
                y2=text_bbox.y2 + 18,
            ),
            window,
        )
    if strategy == "calendar_create_button":
        roi = _clamp(BoundingBox(x1=window.x2 - 380, y1=window.y1 + 35, x2=window.x2 - 20, y2=window.y1 + 140), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("创建日程", "新建日程", "创建"))
        if text_bbox is None:
            return None
        return _clamp(
            BoundingBox(
                x1=text_bbox.x1 - 26,
                y1=text_bbox.y1 - 12,
                x2=text_bbox.x2 + 44,
                y2=text_bbox.y2 + 12,
            ),
            window,
        )
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


def _ocr_text_for_roi(screenshot_path: str, roi: BoundingBox) -> str:
    return " ".join(text for _bbox, text, _confidence in ocr_image(screenshot_path, roi))


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


def _normalize_ocr_text(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _vc_device_state_skip_reason(observation: Observation, step: PlanStep) -> str | None:
    try:
        from tools.vision.vc_error_library import analyze_vc_screen
    except Exception:
        return None
    state = analyze_vc_screen(observation)
    if state is None:
        return None
    desired_camera = step.metadata.get("desired_camera_on")
    if desired_camera is not None and state.camera_off is not None:
        camera_on = not state.camera_off
        if camera_on == bool(desired_camera):
            return f"VC camera already matches desired state camera_on={camera_on}."
    desired_mic = step.metadata.get("desired_mic_on")
    if desired_mic is not None and state.mic_muted is not None:
        mic_on = not state.mic_muted
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
    return BoundingBox(
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
    )
