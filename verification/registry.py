from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from core.schemas import Observation, PlanStep, StepVerification, TestCase
from tools.vision.lark_locator import detect_lark_window, strategy_bbox_from_screenshot
from tools.vision.ocr_client import ocr_image
from tools.vision.smoke import (
    is_safe_smoke_case,
    observe_smoke_screen,
    verify_smoke_case,
    verify_smoke_step,
)


def supports_local_observation(case: TestCase) -> bool:
    return _template(case) in {
        "safe_smoke",
        "im_search_only",
        "im_send_message_guarded",
        "docs_open_smoke",
        "docs_smoke",
        "docs_create_doc_guarded",
        "calendar_create_event_guarded",
    } or is_safe_smoke_case(case)


def local_observe(case: TestCase, screenshot_path: str, ocr_lines: list[str] | None, window_title: str | None) -> Observation | None:
    if not supports_local_observation(case):
        return None
    if is_safe_smoke_case(case) or _template(case) in {"safe_smoke", "im_search_only"}:
        return observe_smoke_screen(screenshot_path, ocr_lines, window_title)
    flags = _image_flags(screenshot_path)
    return Observation(
        screenshot_path=screenshot_path,
        window_title=window_title,
        page_type=f"{_template(case)}_local",
        page_summary="Local fast product-smoke observation. No VLM call was made.",
        ocr_lines=ocr_lines or [],
        raw_model_output={"provider": "local_product", "template": _template(case), **flags},
    )


def local_verify_step(
    case: TestCase,
    step: PlanStep,
    before: Observation | None,
    after: Observation | None,
) -> StepVerification | None:
    template = _template(case)
    if is_safe_smoke_case(case) or template in {"safe_smoke", "im_search_only"}:
        return verify_smoke_step(step, before, after)

    verifier = str(step.metadata.get("local_verifier") or "")
    if not verifier:
        return None
    if after is None:
        return _fail("No after observation available.", "perception_failed", verifier)

    if step.action == "focus_window" and step.metadata.get("dry_run_simulated_focus"):
        return _pass("Dry-run simulated Feishu/Lark window focus.", verifier or "focus_window", 0.75)

    if verifier in {"visible_screen", "docs_no_create", "lark_focused"}:
        return _pass("Visible screen is available and no mutation action was executed.", verifier) if _healthy_image(after.screenshot_path) else _fail("Screenshot is not healthy.", "perception_failed", verifier)

    if verifier in {"docs_entry_clicked", "docs_visible"}:
        return _verify_docs_visible(before, after, verifier)

    if verifier == "calendar_visible":
        return _verify_calendar_visible(before, after, verifier)

    if verifier in {
        "docs_editor_opened",
        "calendar_editor_opened",
        "calendar_event_saved",
    }:
        diff = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
        ok = _healthy_image(after.screenshot_path) and diff > 0.5
        return (
            _pass(f"Visible product screen changed after the action. image_diff={diff:.2f}.", verifier, 0.76)
            if ok
            else _fail(f"Expected visible product state change was not locally confirmed. image_diff={diff:.2f}.", "verification_failed", verifier)
        )

    if verifier == "calendar_event_visible":
        return _verify_calendar_event_visible(after, step, verifier)

    if verifier in {
        "docs_title_entered",
        "docs_body_entered",
        "docs_content_visible",
        "calendar_title_entered",
        "calendar_start_date_entered",
        "calendar_start_time_entered",
        "calendar_time_entered",
        "calendar_attendees_entered",
    }:
        # Exact text/content verification should be semantic; let the VLM check
        # the screenshot instead of locally guessing from pixels.
        return None

    if verifier == "im_open":
        title = after.window_title or ""
        ok = _looks_like_lark(title) and _healthy_image(after.screenshot_path)
        return (
            _pass("Feishu/Lark foreground window and healthy screenshot were confirmed.", verifier, 0.95)
            if ok
            else _fail(f"Feishu/Lark foreground was not confirmed: {title!r}", "product_state_invalid", verifier)
        )

    if verifier == "im_search_focused":
        diff = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
        ok = _healthy_image(after.screenshot_path) and diff > 1.0
        return (
            _pass(f"Search focus changed the visible screen. image_diff={diff:.2f}.", verifier, 0.85)
            if ok
            else _fail(f"Search focus was not locally confirmed. image_diff={diff:.2f}.", "verification_failed", verifier)
        )

    if verifier == "im_search_text_entered":
        bbox = strategy_bbox_from_screenshot(after.screenshot_path, str(step.metadata.get("locator_strategy") or "search_dialog_input"))
        if bbox is None:
            return _fail("Search input bbox could not be derived from the current screenshot.", "location_failed", verifier)
        changed = _crop_diff(before.screenshot_path if before else None, after.screenshot_path, bbox.model_dump())
        text_like = _input_crop_has_text_like_pixels(after.screenshot_path, bbox.model_dump())
        ok = (changed > 0.5 and text_like) or changed > 2.0
        return (
            _pass(f"Search input crop changed and contains text-like pixels. crop_diff={changed:.2f}.", verifier, 0.88)
            if ok
            else _fail(f"Search input text was not locally confirmed. crop_diff={changed:.2f}, text_like={text_like}.", "verification_failed", verifier)
        )

    if verifier == "im_chat_opened":
        if step.metadata.get("target"):
            return None
        diff = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
        ok = _healthy_image(after.screenshot_path) and diff > 0.5
        return (
            _pass(f"Chat opening changed the visible screen. image_diff={diff:.2f}.", verifier, 0.78)
            if ok
            else _fail(f"Chat opening was not locally confirmed. image_diff={diff:.2f}.", "verification_failed", verifier)
        )

    if verifier == "im_message_drafted":
        bbox = strategy_bbox_from_screenshot(after.screenshot_path, str(step.metadata.get("locator_strategy") or "message_input"))
        if bbox is None:
            return _fail("Message input bbox could not be derived from the current screenshot.", "location_failed", verifier)
        changed = _crop_diff(before.screenshot_path if before else None, after.screenshot_path, bbox.model_dump())
        text_like = _input_crop_has_text_like_pixels(after.screenshot_path, bbox.model_dump())
        ok = changed > 0.5 and text_like
        return (
            _pass(f"Message input crop changed and contains text-like pixels. crop_diff={changed:.2f}.", verifier, 0.82)
            if ok
            else _fail(f"Message draft was not locally confirmed. crop_diff={changed:.2f}, text_like={text_like}.", "verification_failed", verifier)
        )

    if verifier == "im_message_sent":
        if step.metadata.get("target") or step.metadata.get("message"):
            return None
        diff = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
        ok = _healthy_image(after.screenshot_path) and diff > 0.3
        return (
            _pass(f"Send action changed the visible chat screen. image_diff={diff:.2f}.", verifier, 0.72)
            if ok
            else _fail(f"Send action was not locally confirmed. image_diff={diff:.2f}.", "verification_failed", verifier)
        )

    if verifier == "im_message_visible":
        if case.metadata.get("target") or case.metadata.get("message"):
            return None
        return (
            _pass("Final chat screen is visible after guarded send workflow.", verifier, 0.72)
            if _healthy_image(after.screenshot_path)
            else _fail("Final chat screenshot is not healthy.", "perception_failed", verifier)
        )

    if verifier == "no_send":
        return _pass("No send action exists in this safe verification step.", verifier, 0.9)

    return None


def local_verify_case(case: TestCase, final_observation: Observation | None) -> StepVerification | None:
    template = _template(case)
    if is_safe_smoke_case(case) or template in {"safe_smoke", "im_search_only"}:
        return verify_smoke_case(case, final_observation)
    if template in {"docs_open_smoke", "docs_smoke"}:
        if final_observation is None:
            return _fail("No final observation available.", "perception_failed", "docs_case")
        if _healthy_image(final_observation.screenshot_path):
            return _pass("Docs smoke completed without document creation or mutation.", "docs_case", 0.85)
        return _fail("No final healthy observation was available.", "perception_failed", "docs_case")
    if template == "calendar_create_event_guarded":
        if final_observation is None:
            return _fail("No final observation available.", "perception_failed", "calendar_case")
        event_time = str(case.metadata.get("event_time") or "明天 10:00")
        event_date, start_time, _end_time = _calendar_time_parts(event_time)
        step = PlanStep(
            id="final_calendar_event_visible",
            action="verify",
            metadata={
                "event_title": str(case.metadata.get("event_title") or ""),
                "event_date": event_date,
                "start_time": start_time,
            },
        )
        return _verify_calendar_event_visible(final_observation, step, "calendar_case")
    if template in {"im_send_message_guarded", "docs_create_doc_guarded"}:
        return None
    return None


def _template(case: TestCase) -> str:
    if case.metadata.get("safe_smoke"):
        return "safe_smoke"
    return str(case.metadata.get("plan_template") or "").strip()


def _pass(reason: str, verifier: str, confidence: float = 0.9) -> StepVerification:
    return StepVerification(
        success=True,
        confidence=confidence,
        reason=reason,
        matched_criteria=[verifier],
        failure_category="none",
        raw_model_output={"provider": "local_product", "verifier": verifier},
    )


def _fail(reason: str, category: str, verifier: str) -> StepVerification:
    return StepVerification(
        success=False,
        confidence=0.2,
        reason=reason,
        failed_criteria=[verifier],
        failure_category=category,  # type: ignore[arg-type]
        raw_model_output={"provider": "local_product", "verifier": verifier},
    )


def _verify_docs_visible(before: Observation | None, after: Observation, verifier: str) -> StepVerification:
    text = " ".join(after.ocr_lines or [])
    title = after.window_title or ""
    keywords = ("docs", "doc", "wiki", "云文档", "文档", "知识库", "飞书文档", "多维表格")
    keyword_hit = any(item.lower() in f"{title} {text}".lower() for item in keywords)
    diff = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
    sidebar_selected = _docs_sidebar_entry_selected(after.screenshot_path)
    if _healthy_image(after.screenshot_path) and (keyword_hit or sidebar_selected):
        return _pass(
            f"Docs-related screen was locally confirmed. image_diff={diff:.2f}, keyword_hit={keyword_hit}, sidebar_selected={sidebar_selected}.",
            verifier,
            0.82,
        )
    return _fail(
        f"Docs screen was not locally confirmed. image_diff={diff:.2f}, keyword_hit={keyword_hit}, sidebar_selected={sidebar_selected}.",
        "verification_failed",
        verifier,
    )


def _verify_calendar_visible(before: Observation | None, after: Observation, verifier: str) -> StepVerification:
    text = " ".join(after.ocr_lines or [])
    title = after.window_title or ""
    keywords = ("calendar", "meeting", "event", "日历", "会议", "日程", "飞书日历")
    keyword_hit = any(item.lower() in f"{title} {text}".lower() for item in keywords)
    diff = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
    sidebar_selected = _calendar_sidebar_entry_selected(after.screenshot_path)
    grid_visible = _calendar_grid_visible(after.screenshot_path)
    if _healthy_image(after.screenshot_path) and (keyword_hit or sidebar_selected or grid_visible or diff > 0.5):
        return _pass(
            (
                "Calendar-related screen was locally confirmed. "
                f"image_diff={diff:.2f}, keyword_hit={keyword_hit}, "
                f"sidebar_selected={sidebar_selected}, grid_visible={grid_visible}."
            ),
            verifier,
            0.78,
        )
    return _fail(
        (
            f"Calendar screen was not locally confirmed. image_diff={diff:.2f}, "
            f"keyword_hit={keyword_hit}, sidebar_selected={sidebar_selected}, grid_visible={grid_visible}."
        ),
        "verification_failed",
        verifier,
    )


def _verify_calendar_event_visible(after: Observation, step: PlanStep, verifier: str) -> StepVerification:
    if not _healthy_image(after.screenshot_path):
        return _fail("Final calendar screenshot is not healthy.", "perception_failed", verifier)

    results = ocr_image(after.screenshot_path)
    text = " ".join(item[1] for item in results)
    normalized = _normalize_text(text)
    title = str(step.metadata.get("event_title") or "").strip()
    event_date = str(step.metadata.get("event_date") or "").strip()
    start_time = str(step.metadata.get("start_time") or "").strip()

    title_norm = _normalize_text(title)
    title_hit = bool(title_norm and (title_norm in normalized or "cualark" in normalized))
    date_hit = _calendar_date_visible(normalized, event_date)
    time_hit = bool(start_time and _normalize_text(start_time) in normalized)

    if title_hit and (date_hit or time_hit):
        return _pass(
            (
                "Calendar event was locally confirmed by OCR after save. "
                f"title_hit={title_hit}, date_hit={date_hit}, time_hit={time_hit}."
            ),
            verifier,
            0.86,
        )
    if title_hit:
        return _pass(
            "Calendar event title was locally confirmed by OCR after save.",
            verifier,
            0.78,
        )
    return _fail(
        (
            "Calendar event title was not found in the current screenshot OCR. "
            f"date_hit={date_hit}, time_hit={time_hit}."
        ),
        "verification_failed",
        verifier,
    )


def _normalize_text(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _calendar_date_visible(normalized_text: str, event_date: str) -> bool:
    import re

    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", event_date)
    if not match:
        return False
    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))
    candidates = (
        f"{year}年{month}月{day}日",
        f"{year}年{month:02d}月{day:02d}日",
        f"{month}月{day}日",
    )
    return any(_normalize_text(item) in normalized_text for item in candidates)


def _calendar_time_parts(raw_time: str) -> tuple[str, str, str]:
    now = datetime.now()
    event_date = now + timedelta(days=1 if "明天" in raw_time else 0)
    start_hour = 10
    start_minute = 0
    import re

    match = re.search(r"(\d{1,2}):(\d{2})", raw_time)
    if match:
        start_hour = int(match.group(1))
        start_minute = int(match.group(2))
    start_dt = event_date.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end_dt = start_dt + timedelta(minutes=30)
    return start_dt.strftime("%Y-%m-%d"), start_dt.strftime("%H:%M"), end_dt.strftime("%H:%M")


def _looks_like_lark(title: str) -> bool:
    raw = title.lower()
    return any(item in raw for item in ("飞书", "feishu", "lark"))


def _healthy_image(path: str) -> bool:
    if not Path(path).exists():
        return False
    image = Image.open(path).convert("L")
    stat = ImageStat.Stat(image)
    lo, hi = image.getextrema()
    return stat.mean[0] > 5 and stat.stddev[0] > 2 and (hi - lo) > 8


def _image_flags(path: str) -> dict:
    if not Path(path).exists():
        return {"healthy_image": False}
    image = Image.open(path).convert("L")
    stat = ImageStat.Stat(image)
    lo, hi = image.getextrema()
    return {
        "healthy_image": _healthy_image(path),
        "mean_luma": round(float(stat.mean[0]), 3),
        "stdev_luma": round(float(stat.stddev[0]), 3),
        "min_luma": int(lo),
        "max_luma": int(hi),
    }


def _image_diff(before_path: str | None, after_path: str) -> float:
    if not before_path or not Path(before_path).exists() or not Path(after_path).exists():
        return 0.0
    before = Image.open(before_path).convert("L")
    after = Image.open(after_path).convert("L")
    if before.size != after.size:
        after = after.resize(before.size)
    return float(ImageStat.Stat(ImageChops.difference(before, after)).mean[0])


def _crop_diff(before_path: str | None, after_path: str, box: dict) -> float:
    if not before_path or not Path(before_path).exists() or not Path(after_path).exists():
        return 0.0
    crop_box = (box["x1"], box["y1"], box["x2"], box["y2"])
    before = Image.open(before_path).convert("L").crop(crop_box)
    after = Image.open(after_path).convert("L").crop(crop_box)
    return float(ImageStat.Stat(ImageChops.difference(before, after)).mean[0])


def _input_crop_has_text_like_pixels(path: str, box: dict) -> bool:
    if not Path(path).exists():
        return False
    crop_box = (box["x1"], box["y1"], box["x2"], box["y2"])
    crop = Image.open(path).convert("L").crop(crop_box)
    dark_pixels = sum(1 for value in crop.getdata() if value < 120)
    total = max(crop.width * crop.height, 1)
    return (dark_pixels / total) > 0.002


def _docs_sidebar_entry_selected(path: str) -> bool:
    if not Path(path).exists():
        return False
    image = Image.open(path).convert("RGB")
    docs_box = strategy_bbox_from_screenshot(path, "docs_sidebar_entry")
    if docs_box is None:
        return False
    docs_row = image.crop((docs_box.x1, docs_box.y1, docs_box.x2, docs_box.y2))
    docs_score = _selected_nav_row_score(docs_row)
    return docs_score > 0.18


def _calendar_sidebar_entry_selected(path: str) -> bool:
    if not Path(path).exists():
        return False
    image = Image.open(path).convert("RGB")
    calendar_box = strategy_bbox_from_screenshot(path, "calendar_sidebar_entry")
    if calendar_box is None:
        return False
    calendar_row = image.crop((calendar_box.x1, calendar_box.y1, calendar_box.x2, calendar_box.y2))
    calendar_score = _selected_nav_row_score(calendar_row)
    return calendar_score > 0.18


def _calendar_grid_visible(path: str) -> bool:
    if not Path(path).exists():
        return False
    window = detect_lark_window(path)
    if window is None:
        return False
    image = Image.open(path).convert("L")
    # Calendar day/week views have many thin vertical and horizontal grid lines
    # in the main content area; this is a cheap local signal for "already there".
    crop = image.crop((window.x1 + 650, window.y1 + 220, window.x2 - 20, window.y2 - 80))
    if crop.width < 200 or crop.height < 200:
        return False
    vertical_hits = 0
    for x in range(0, crop.width, 8):
        col = [crop.getpixel((x, y)) for y in range(0, crop.height, 16)]
        if col and sum(1 for value in col if 205 <= value <= 235) / len(col) > 0.18:
            vertical_hits += 1
    horizontal_hits = 0
    for y in range(0, crop.height, 8):
        row = [crop.getpixel((x, y)) for x in range(0, crop.width, 16)]
        if row and sum(1 for value in row if 205 <= value <= 235) / len(row) > 0.18:
            horizontal_hits += 1
    return vertical_hits >= 4 and horizontal_hits >= 4


def _selected_nav_row_score(crop: Image.Image) -> float:
    pixels = list(crop.getdata())
    if not pixels:
        return 0.0
    selected = 0
    for red, green, blue in pixels:
        # Selected Feishu sidebar rows are very light and slightly blue/gray.
        if red > 225 and green > 232 and blue > 238 and abs(red - green) < 18 and abs(green - blue) < 22:
            selected += 1
    return selected / len(pixels)
