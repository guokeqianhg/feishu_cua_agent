from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
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

    window = _os_lark_window_for_strategy(strategy) or detect_lark_window(observation.screenshot_path)
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
        reason=f"Located by screenshot-derived Feishu window-relative layout: {strategy}.",
        metadata={
            "strategy": strategy,
            "window_bbox": {"x1": window.x1, "y1": window.y1, "x2": window.x2, "y2": window.y2},
        },
    )


def strategy_bbox_from_screenshot(screenshot_path: str, strategy: str) -> BoundingBox | None:
    window = _os_lark_window_for_strategy(strategy) or detect_lark_window(screenshot_path)
    if window is None:
        return None
    ocr_bbox = _text_bbox_for_strategy(screenshot_path, window, strategy, None)
    if ocr_bbox is not None:
        return ocr_bbox
    return _bbox_for_strategy(window, strategy)


def _os_lark_window_for_strategy(strategy: str) -> WindowBox | None:
    if strategy not in {
        "sidebar_search_box",
        "search_dialog_input",
        "docs_sidebar_entry",
        "calendar_sidebar_entry",
        "calendar_main_tab",
        "docs_template_preview_back",
        "docs_transient_overlay",
        "docs_create_button",
        "docs_blank_doc_option",
        "docs_blank_doc_card",
        "calendar_create_button",
        "calendar_cancel_button",
        "calendar_discard_exit_button",
        "calendar_event_title_input",
        "calendar_event_attendee_input",
        "calendar_event_time_row",
        "calendar_event_start_date",
        "calendar_date_picker_day",
        "calendar_event_start_time",
        "calendar_event_end_time",
        "calendar_view_date_button",
        "calendar_save_button",
        "search_first_result",
        "message_input",
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
    if step.id in {"type_safe_query", "type_query"}:
        return "search_dialog_input"
    if step.id == "open_docs":
        return "docs_sidebar_entry"
    if step.id == "open_calendar":
        return "calendar_sidebar_entry"
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
    if step.id == "click_create_event":
        return "calendar_create_button"
    if step.id == "close_calendar_editor":
        return "calendar_cancel_button"
    if step.id == "confirm_calendar_editor_exit":
        return "calendar_discard_exit_button"
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
    if step.id == "click_calendar_view_day":
        return "calendar_date_picker_day"
    if step.id == "type_event_start_time":
        return "calendar_event_start_time"
    if step.id == "type_event_end_time":
        return "calendar_event_end_time"
    if step.id == "type_event_attendees":
        return "calendar_event_attendee_input"
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
    if strategy == "sidebar_search_box":
        return _clamp(BoundingBox(x1=x + 20, y1=y + 85, x2=x + min(270, w - 25), y2=y + 145), window)
    if strategy == "search_dialog_input":
        if modal_like:
            return _clamp(BoundingBox(x1=x + 35, y1=y + 30, x2=x + w - 90, y2=y + 90), window)
        return _clamp(BoundingBox(x1=x + 180, y1=y + 105, x2=x + min(1020, w - 170), y2=y + 165), window)
    if strategy == "docs_sidebar_entry":
        return _clamp(BoundingBox(x1=x + 20, y1=y + 255, x2=x + min(270, w - 25), y2=y + 315), window)
    if strategy == "calendar_sidebar_entry":
        # Calendar sits below Contacts in the global Feishu sidebar. Floating
        # Feishu child windows can make the detected surface start a little
        # higher than the main sidebar, so compensate before clicking.
        top_offset = 705 if y < 220 else 665
        return _clamp(BoundingBox(x1=x + 20, y1=y + top_offset - 35, x2=x + min(270, w - 25), y2=y + top_offset + 35), window)
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
    if strategy == "calendar_create_button":
        return _clamp(BoundingBox(x1=x + w - 365, y1=y + 55, x2=x + w - 190, y2=y + 115), window)
    if strategy == "calendar_event_title_input":
        return _clamp(BoundingBox(x1=x + 540, y1=y + 90, x2=x + min(1360, w - 570), y2=y + 175), window)
    if strategy == "calendar_event_attendee_input":
        return _clamp(BoundingBox(x1=x + 580, y1=y + 165, x2=x + min(1220, w - 700), y2=y + 230), window)
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
    if strategy == "calendar_save_button":
        return _clamp(BoundingBox(x1=x + min(1210, w - 730), y1=y + h - 105, x2=x + min(1345, w - 595), y2=y + h - 45), window)
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
    return None


def _text_bbox_for_strategy(
    screenshot_path: str,
    window: WindowBox,
    strategy: str,
    step: PlanStep | None = None,
) -> BoundingBox | None:
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
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("取消",))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 36, y1=text_bbox.y1 - 18, x2=text_bbox.x2 + 36, y2=text_bbox.y2 + 18), window)
    if strategy == "calendar_discard_exit_button":
        roi = _clamp(BoundingBox(x1=window.x1, y1=window.y1, x2=window.x2, y2=window.y2), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("退出",))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 44, y1=text_bbox.y1 - 22, x2=text_bbox.x2 + 44, y2=text_bbox.y2 + 22), window)
    if strategy == "calendar_save_button":
        roi = _clamp(BoundingBox(x1=window.x1, y1=window.y2 - 160, x2=window.x2, y2=window.y2 - 20), window)
        text_bbox = _find_ocr_text_bbox(screenshot_path, roi, ("保存",))
        if text_bbox is None:
            return None
        return _clamp(BoundingBox(x1=text_bbox.x1 - 42, y1=text_bbox.y1 - 20, x2=text_bbox.x2 + 42, y2=text_bbox.y2 + 20), window)
    if strategy == "calendar_date_picker_day":
        return _calendar_date_picker_day_bbox(screenshot_path, window, step)
    return None


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


def _normalize_ocr_text(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


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
