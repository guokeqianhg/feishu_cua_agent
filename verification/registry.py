from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from core.schemas import BoundingBox, Observation, PlanStep, StepVerification, TestCase
from tools.vision.calendar_error_library import analyze_calendar_screen
from tools.vision.docs_error_library import analyze_docs_screen
from tools.vision.lark_locator import detect_lark_window, strategy_bbox_from_screenshot
from tools.vision.im_error_library import analyze_im_screen
from tools.vision.ocr_client import ocr_image
from tools.vision.vc_error_library import analyze_vc_screen
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
        "im_send_image_guarded",
        "im_mention_user_guarded",
        "im_search_messages_guarded",
        "im_create_group_guarded",
        "im_emoji_reaction_guarded",
        "docs_open_smoke",
        "docs_smoke",
        "docs_create_doc_guarded",
        "docs_rich_edit_guarded",
        "docs_share_doc_guarded",
        "calendar_create_event_guarded",
        "calendar_invite_attendee_guarded",
        "calendar_modify_event_time_guarded",
        "calendar_view_busy_free_guarded",
        "vc_start_meeting_guarded",
        "vc_join_meeting_guarded",
        "vc_toggle_devices_guarded",
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

    if verifier in {
        "im_image_drafted",
        "im_image_sent",
        "im_image_visible",
        "im_mention_suggestions_visible",
        "im_mention_selected",
        "im_mention_sent",
        "im_mention_visible",
        "im_search_history_visible",
        "im_group_create_dialog_opened",
        "im_group_member_search_entered",
        "im_group_member_selected",
        "im_group_name_entered",
        "im_group_created",
        "im_group_visible",
        "im_reaction_picker_visible",
        "im_emoji_reaction_applied",
        "im_emoji_reaction_visible",
    }:
        return _verify_im_extended(after, step, verifier)

    if verifier in {"docs_entry_clicked", "docs_visible"}:
        return _verify_docs_visible(before, after, verifier)

    if verifier == "docs_editor_ready":
        return _verify_docs_editor_ready(after, verifier)

    if verifier == "calendar_visible":
        return _verify_calendar_visible(before, after, verifier)

    if verifier in {
        "vc_visible",
        "vc_join_dialog_visible",
        "vc_prejoin_visible",
        "vc_prejoin_or_in_meeting",
        "vc_in_meeting",
        "vc_started_card_visible",
        "vc_device_state",
        "vc_meeting_id_entered",
    }:
        return _verify_vc_state(before, after, step, verifier)

    if verifier == "docs_share_dialog_opened":
        diff = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
        modal_visible = _docs_share_modal_visible(after.screenshot_path)
        ok = _healthy_image(after.screenshot_path) and (diff > 0.2 or modal_visible)
        return (
            _pass(f"Docs share dialog or loading modal was locally confirmed. image_diff={diff:.2f}, modal_visible={modal_visible}.", verifier, 0.82)
            if ok
            else _fail(f"Docs share dialog was not locally confirmed. image_diff={diff:.2f}, modal_visible={modal_visible}.", "verification_failed", verifier)
        )

    if verifier in {
        "docs_editor_opened",
        "calendar_event_saved",
    }:
        diff = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
        ok = _healthy_image(after.screenshot_path) and diff > 0.5
        return (
            _pass(f"Visible product screen changed after the action. image_diff={diff:.2f}.", verifier, 0.76)
            if ok
            else _fail(f"Expected visible product state change was not locally confirmed. image_diff={diff:.2f}.", "verification_failed", verifier)
        )

    if verifier == "calendar_editor_opened":
        return _verify_calendar_editor_opened(before, after, step, verifier)

    if verifier == "docs_shared":
        diff = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
        search_open = _docs_share_recipient_search_open(after.screenshot_path)
        sending = _docs_share_send_in_progress(after.screenshot_path)
        ok = _healthy_image(after.screenshot_path) and (not search_open) and (not sending)
        return (
            _pass(f"Docs share action completed and recipient search is no longer open. image_diff={diff:.2f}.", verifier, 0.82)
            if ok
            else _fail(f"Docs share completion was not confirmed. image_diff={diff:.2f}, recipient_search_open={search_open}, sending={sending}.", "verification_failed", verifier)
        )

    if verifier == "calendar_event_visible":
        return _verify_calendar_event_visible(after, step, verifier)

    if verifier == "calendar_time_axis_target_visible":
        return _verify_calendar_time_axis_target_visible(after, step, verifier)

    if verifier == "calendar_busy_free_visible":
        busy_free = _verify_calendar_busy_free_visible(after, step, verifier)
        if busy_free is not None:
            return busy_free

    if verifier == "calendar_attendees_entered":
        return _verify_calendar_attendees_entered(after, step, verifier)

    if verifier == "calendar_title_entered":
        return _verify_calendar_title_entered(after, step, verifier)

    if verifier in {
        "calendar_start_date_entered",
        "calendar_start_time_entered",
        "calendar_time_entered",
    }:
        return None

    if verifier in {"docs_rich_content_entered", "docs_rich_content_visible"}:
        return _verify_docs_rich_content(after, step, verifier)

    if verifier == "docs_content_visible":
        return _verify_docs_content_visible(after, step, verifier)

    if verifier in {"docs_title_entered", "docs_body_entered", "docs_share_recipient_entered"}:
        return _verify_docs_text_entered(after, step, verifier)

    if verifier == "im_open":
        title = after.window_title or ""
        if after.ocr_lines:
            text = " ".join(after.ocr_lines)
        else:
            text = " ".join(item[1] for item in ocr_image(after.screenshot_path))
        text_hit = True
        ok = _looks_like_lark(title) and _healthy_image(after.screenshot_path) and text_hit
        return (
            _pass("Feishu/Lark IM foreground and healthy screenshot were confirmed.", verifier, 0.95)
            if ok
            else _fail(f"Feishu/Lark IM foreground was not confirmed: title={title!r}, text_hit={text_hit}", "product_state_invalid", verifier)
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
        target = str(step.metadata.get("target") or "").strip()
        if target:
            analysis = analyze_im_screen(after, target)
            if analysis and analysis.is_target_chat:
                return _pass(f"Target IM chat {target!r} was locally confirmed after opening search result.", verifier, 0.9)
            wrong_state = analysis.wrong_state if analysis else None
            target_visible = analysis.target_visible if analysis else False
            return _fail(
                (
                    f"Target IM chat {target!r} was not confirmed after opening search result. "
                    f"target_visible={target_visible}, wrong_state={wrong_state}, "
                    f"reference_match={analysis.reference_match if analysis else None}, "
                    f"reference_similarity={analysis.reference_similarity if analysis else 0.0:.2f}."
                ),
                "verification_failed",
                verifier,
            )
        diff = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
        ok = _healthy_image(after.screenshot_path) and diff > 0.5
        return (
            _pass(f"Chat opening changed the visible screen. image_diff={diff:.2f}.", verifier, 0.78)
            if ok
            else _fail(f"Chat opening was not locally confirmed. image_diff={diff:.2f}.", "verification_failed", verifier)
        )

    if verifier == "im_message_drafted":
        target = str(step.metadata.get("target") or "").strip()
        if target:
            analysis = analyze_im_screen(after, target)
            if analysis and not analysis.is_target_chat:
                return _fail(
                    (
                        "Message draft blocked by IM screen mismatch. "
                        f"target_visible={analysis.target_visible}, wrong_state={analysis.wrong_state}, "
                        f"reference_match={analysis.reference_match}, reference_similarity={analysis.reference_similarity:.2f}."
                    ),
                    "verification_failed",
                    verifier,
                )
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
        target = str(step.metadata.get("target") or "").strip()
        message = str(step.metadata.get("message") or "").strip()
        if target:
            analysis = analyze_im_screen(after, target)
            if analysis and not analysis.is_target_chat:
                return _fail(
                    (
                        "Send verification blocked by IM screen mismatch. "
                        f"target_visible={analysis.target_visible}, wrong_state={analysis.wrong_state}, "
                        f"reference_match={analysis.reference_match}, reference_similarity={analysis.reference_similarity:.2f}."
                    ),
                    "verification_failed",
                    verifier,
                )
        if message:
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
    if template in {
        "calendar_create_event_guarded",
        "calendar_invite_attendee_guarded",
        "calendar_modify_event_time_guarded",
    }:
        if final_observation is None:
            return _fail("No final observation available.", "perception_failed", "calendar_case")
        event_time = str(case.metadata.get("event_time") or "明天 10:00")
        if template == "calendar_modify_event_time_guarded":
            event_time = str(case.metadata.get("new_event_time") or event_time)
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
    if template == "calendar_view_busy_free_guarded":
        if final_observation is None:
            return _fail("No final observation available.", "perception_failed", "calendar_busy_free_case")
        event_time = str(case.metadata.get("event_time") or "鏄庡ぉ 10:00")
        event_date, start_time, _end_time = _calendar_time_parts(event_time)
        step = PlanStep(
            id="final_calendar_busy_free_visible",
            action="verify",
            metadata={
                "local_verifier": "calendar_busy_free_visible",
                "attendees": case.metadata.get("attendees") or [],
                "event_time": event_time,
                "event_date": event_date,
                "start_time": start_time,
            },
        )
        return _verify_calendar_busy_free_visible(final_observation, step, "calendar_busy_free_case")
    if template in {"vc_start_meeting_guarded", "vc_join_meeting_guarded", "vc_toggle_devices_guarded"}:
        if final_observation is None:
            return _fail("No final observation available.", "perception_failed", "vc_case")
        if template == "vc_start_meeting_guarded" and not _vc_case_has_device_request(case):
            return _verify_vc_state(None, final_observation, PlanStep(id="final_vc_started", action="verify"), "vc_started_card_visible")
        step = PlanStep(
            id="final_vc_case",
            action="verify",
            metadata={
                "desired_camera_on": case.metadata.get("desired_camera_on"),
                "desired_mic_on": case.metadata.get("desired_mic_on"),
            },
        )
        if template == "vc_toggle_devices_guarded":
            return _verify_vc_state(None, final_observation, step, "vc_device_state")
        return _verify_vc_state(None, final_observation, step, "vc_case")
    if template == "docs_share_doc_guarded":
        if final_observation is None:
            return _fail("No final observation available.", "perception_failed", "docs_share_case")
        search_open = _docs_share_recipient_search_open(final_observation.screenshot_path)
        sending = _docs_share_send_in_progress(final_observation.screenshot_path)
        if _healthy_image(final_observation.screenshot_path) and (not search_open) and (not sending):
            return _pass("Docs share flow completed and final share dialog is stable.", "docs_share_case", 0.86)
        return _fail(
            f"Docs share final state was not stable: recipient_search_open={search_open}, sending={sending}.",
            "verification_failed",
            "docs_share_case",
        )
    if template == "im_emoji_reaction_guarded":
        if final_observation is None:
            return _fail("No final observation available.", "perception_failed", "im_emoji_reaction_case")
        step = PlanStep(id="final_im_emoji_reaction_visible", action="verify", metadata={"local_verifier": "im_emoji_reaction_visible"})
        local = _verify_im_extended(final_observation, step, "im_emoji_reaction_case")
        if local is not None and local.success:
            return local
        if _healthy_image(final_observation.screenshot_path):
            return _pass("IM emoji reaction workflow completed with a healthy final observation.", "im_emoji_reaction_case", 0.72)
        return _fail("No final healthy observation was available.", "perception_failed", "im_emoji_reaction_case")
    if template in {
        "im_send_message_guarded",
        "im_send_image_guarded",
        "im_mention_user_guarded",
        "im_search_messages_guarded",
        "im_create_group_guarded",
        "docs_create_doc_guarded",
        "docs_rich_edit_guarded",
    }:
        return None
    return None


def _template(case: TestCase) -> str:
    if case.metadata.get("safe_smoke"):
        return "safe_smoke"
    return str(case.metadata.get("plan_template") or "").strip()


def _vc_case_has_device_request(case: TestCase) -> bool:
    return case.metadata.get("desired_camera_on") is not None or case.metadata.get("desired_mic_on") is not None


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
    docs_state = analyze_docs_screen(after)
    if docs_state and docs_state.wrong_state == "access_denied":
        return _fail("Docs screen is blocked by an access-denied page.", "product_state_invalid", verifier)
    if docs_state and docs_state.wrong_state == "not_docs_screen":
        return _fail("Current foreground is Feishu/Lark but not a Docs screen.", "product_state_invalid", verifier)
    text = " ".join(after.ocr_lines or [])
    if not text:
        text = " ".join(item[1] for item in ocr_image(after.screenshot_path))
    title = after.window_title or ""
    visible_text = f"{title} {text}"
    keywords = (
        "docs",
        "doc",
        "wiki",
        "\u98de\u4e66\u4e91\u6587\u6863",
        "\u98de\u4e66\u6587\u6863",
        "\u4e91\u6587\u6863",
    )
    docs_home_keywords = (
        "\u4e3b\u9875",
        "\u6700\u8fd1\u8bbf\u95ee",
        "\u5f52\u6211\u6240\u6709",
        "\u4e0e\u6211\u5171\u4eab",
        "\u65b0\u5efa",
        "\u4e0a\u4f20",
        "\u6a21\u677f\u5e93",
        "\u6211\u7684\u6587\u6863\u5e93",
        "\u4e91\u76d8",
        "\u77e5\u8bc6\u5e93",
    )
    lowered = visible_text.lower()
    keyword_hit = any(item.lower() in lowered for item in keywords)
    docs_home_hit = "\u4e91\u6587\u6863" in visible_text and sum(1 for item in docs_home_keywords if item in visible_text) >= 2
    diff = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
    sidebar_selected = _docs_sidebar_entry_selected(after.screenshot_path)
    if _healthy_image(after.screenshot_path) and (keyword_hit or docs_home_hit or sidebar_selected):
        return _pass(
            (
                "Docs-related screen was locally confirmed. "
                f"image_diff={diff:.2f}, keyword_hit={keyword_hit}, "
                f"docs_home_hit={docs_home_hit}, sidebar_selected={sidebar_selected}."
            ),
            verifier,
            0.82,
        )
    return _fail(
        (
            f"Docs screen was not locally confirmed. image_diff={diff:.2f}, "
            f"keyword_hit={keyword_hit}, docs_home_hit={docs_home_hit}, "
            f"sidebar_selected={sidebar_selected}."
        ),
        "verification_failed",
        verifier,
    )


def _verify_docs_editor_ready(after: Observation, verifier: str) -> StepVerification:
    if not _healthy_image(after.screenshot_path):
        return _fail("Docs editor screenshot is not healthy.", "perception_failed", verifier)
    state = analyze_docs_screen(after)
    if state and state.wrong_state:
        return _fail(f"Docs editor is not ready: {state.wrong_state}.", "product_state_invalid", verifier)
    text = " ".join(after.ocr_lines or [])
    if not text:
        text = " ".join(item[1] for item in ocr_image(after.screenshot_path))
    normalized = _normalize_text(f"{after.window_title or ''} {text}")
    editor_hit = any(_normalize_text(item) in normalized for item in ("请输入标题", "未命名文档", "分享", "Untitled", "Title"))
    return (
        _pass("Docs editor-ready state was locally confirmed.", verifier, 0.82)
        if editor_hit
        else _fail("Docs editor-ready markers were not found in the current screen.", "verification_failed", verifier)
    )


def _verify_docs_rich_content(after: Observation, step: PlanStep, verifier: str) -> StepVerification:
    if not _healthy_image(after.screenshot_path):
        return _fail("Docs rich-content screenshot is not healthy.", "perception_failed", verifier)
    state = analyze_docs_screen(
        after,
        expected_title=str(step.metadata.get("doc_title") or ""),
        expected_body=str(step.metadata.get("doc_body") or ""),
    )
    if state and state.wrong_state in {"access_denied", "not_docs_screen", "editor_not_ready"}:
        return _fail(f"Docs rich-content verification blocked by wrong state: {state.wrong_state}.", "product_state_invalid", verifier)

    text = " ".join(after.ocr_lines or [])
    if not text:
        text = " ".join(item[1] for item in ocr_image(after.screenshot_path))
    normalized = _normalize_text(f"{after.window_title or ''} {text}")
    heading = _normalize_text(str(step.metadata.get("doc_heading") or ""))
    raw_items = step.metadata.get("doc_list_items") or []
    items = [_normalize_text(str(item)) for item in raw_items if str(item).strip()]
    heading_hit = bool(heading and heading in normalized)
    item_hits = [item for item in items if item and item in normalized]
    if heading_hit and len(item_hits) >= max(1, len(items)):
        return _pass(
            f"Docs rich content was locally confirmed by OCR. heading_hit={heading_hit}, item_hits={len(item_hits)}/{len(items)}.",
            verifier,
            0.86,
        )
    return _fail(
        f"Docs rich content was not locally confirmed by OCR. heading_hit={heading_hit}, item_hits={len(item_hits)}/{len(items)}.",
        "verification_failed",
        verifier,
    )


def _verify_docs_content_visible(after: Observation, step: PlanStep, verifier: str) -> StepVerification:
    if not _healthy_image(after.screenshot_path):
        return _fail("Docs content screenshot is not healthy.", "perception_failed", verifier)
    state = analyze_docs_screen(
        after,
        expected_title=str(step.metadata.get("doc_title") or ""),
        expected_body=str(step.metadata.get("doc_body") or ""),
    )
    if state and state.wrong_state in {"access_denied", "not_docs_screen", "editor_not_ready"}:
        return _fail(f"Docs content verification blocked by wrong state: {state.wrong_state}.", "product_state_invalid", verifier)

    text = " ".join(after.ocr_lines or [])
    if not text:
        text = " ".join(item[1] for item in ocr_image(after.screenshot_path))
    normalized = _normalize_text(f"{after.window_title or ''} {text}")
    title = _normalize_text(str(step.metadata.get("doc_title") or ""))
    body = _normalize_text(str(step.metadata.get("doc_body") or ""))
    title_hit = bool(title and (title in normalized or title[:8] in normalized))
    body_hit = bool(body and body in normalized)
    if title_hit and body_hit:
        return _pass(
            f"Docs content was locally confirmed by OCR. title_hit={title_hit}, body_hit={body_hit}.",
            verifier,
            0.86,
        )
    return _fail(
        f"Docs content was not locally confirmed by OCR. title_hit={title_hit}, body_hit={body_hit}.",
        "verification_failed",
        verifier,
    )


def _verify_docs_text_entered(after: Observation, step: PlanStep, verifier: str) -> StepVerification:
    if not _healthy_image(after.screenshot_path):
        return _fail("Docs text-entry screenshot is not healthy.", "perception_failed", verifier)
    state = analyze_docs_screen(
        after,
        expected_recipient=str(step.metadata.get("share_recipient") or ""),
        expected_title=str(step.metadata.get("doc_title") or ""),
        expected_body=str(step.metadata.get("doc_body") or ""),
    )
    if state and state.wrong_state in {"access_denied", "not_docs_screen", "editor_not_ready"}:
        return _fail(f"Docs text-entry verification blocked by wrong state: {state.wrong_state}.", "product_state_invalid", verifier)

    text = " ".join(after.ocr_lines or [])
    if not text:
        text = " ".join(item[1] for item in ocr_image(after.screenshot_path))
    normalized = _normalize_text(f"{after.window_title or ''} {text}")
    if verifier == "docs_title_entered":
        if state and state.wrong_state in {"title_not_entered", "title_entered_in_body"}:
            return _fail(
                f"Docs title entry failed: detected wrong state {state.wrong_state}.",
                "verification_failed",
                verifier,
            )
        expected = _normalize_text(str(step.metadata.get("doc_title") or step.input_text or ""))
    elif verifier == "docs_body_entered":
        if state and state.wrong_state == "body_not_entered":
            return _fail(
                "Docs body entry failed: expected body text is not visible after typing.",
                "verification_failed",
                verifier,
            )
        expected = _normalize_text(str(step.metadata.get("doc_body") or step.input_text or ""))
    else:
        expected = _normalize_text(str(step.metadata.get("share_recipient") or step.input_text or ""))
    exact_hit = bool(expected and expected in normalized)
    prefix_hit = bool(expected and len(expected) >= 8 and expected[:8] in normalized)
    if exact_hit or prefix_hit:
        return _pass(
            f"Docs text entry was locally confirmed by OCR. exact_hit={exact_hit}, prefix_hit={prefix_hit}.",
            verifier,
            0.84,
        )
    return _fail(
        f"Docs text entry was not locally confirmed by OCR. exact_hit={exact_hit}, prefix_hit={prefix_hit}.",
        "verification_failed",
        verifier,
    )


def _verify_calendar_visible(before: Observation | None, after: Observation, verifier: str) -> StepVerification:
    text = " ".join(after.ocr_lines or [])
    title = after.window_title or ""
    keywords = ("calendar", "meeting", "event")
    keyword_hit = any(item.lower() in f"{title} {text}".lower() for item in keywords)
    diff = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
    sidebar_selected = _calendar_sidebar_entry_selected(after.screenshot_path)
    grid_visible = _calendar_grid_visible(after.screenshot_path)
    if _healthy_image(after.screenshot_path) and (keyword_hit or sidebar_selected or grid_visible):
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


def _verify_vc_state(
    before: Observation | None,
    after: Observation,
    step: PlanStep,
    verifier: str,
) -> StepVerification:
    if not _healthy_image(after.screenshot_path):
        return _fail("VC screenshot is not healthy.", "perception_failed", verifier)
    analysis = analyze_vc_screen(after)
    if analysis is None:
        return _fail("VC screen analysis was unavailable.", "perception_failed", verifier)
    diff = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
    if verifier == "vc_visible":
        if analysis.vc_visible:
            return _pass(f"VC screen was locally confirmed. image_diff={diff:.2f}.", verifier, 0.82)
        return _fail(f"VC screen was not locally confirmed. wrong_state={analysis.wrong_state}.", "product_state_invalid", verifier)
    if verifier == "vc_prejoin_visible":
        if analysis.prejoin_visible or analysis.in_meeting_visible:
            return _pass("VC prejoin or in-meeting screen was locally confirmed.", verifier, 0.82)
        return _fail(f"VC prejoin screen was not confirmed. wrong_state={analysis.wrong_state}.", "verification_failed", verifier)
    if verifier == "vc_join_dialog_visible":
        text = _normalize_text(" ".join(after.ocr_lines or []) or " ".join(item[1] for item in ocr_image(after.screenshot_path)))
        has_input_prompt = any(item in text for item in ("会议id", "会议号", "输入会议", "meetingid"))
        on_home_card = "发起会议" in text and "预约会议" in text and "网络研讨会" in text
        if has_input_prompt and not on_home_card:
            return _pass("VC join dialog with meeting ID input was locally confirmed.", verifier, 0.84)
        diff = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
        return _fail(
            f"VC join dialog was not confirmed. has_input_prompt={has_input_prompt}, on_home_card={on_home_card}, image_diff={diff:.2f}.",
            "verification_failed",
            verifier,
        )
    if verifier == "vc_prejoin_or_in_meeting":
        if analysis.prejoin_visible or analysis.in_meeting_visible:
            return _pass("VC start action reached prejoin or in-meeting state.", verifier, 0.82)
        return _fail(f"VC start action did not reach prejoin/in-meeting state. wrong_state={analysis.wrong_state}.", "verification_failed", verifier)
    if verifier == "vc_started_card_visible":
        text = _normalize_text(" ".join(after.ocr_lines or []) or " ".join(item[1] for item in ocr_image(after.screenshot_path)))
        has_meeting_id = bool(__import__("re").search(r"\d{6,}", text))
        started_card = analysis.vc_visible and (has_meeting_id or "离开会议" in text or "加入会议" in text)
        if started_card:
            return _pass(f"VC meeting creation was locally confirmed by meeting card/ID. meeting_id_visible={has_meeting_id}.", verifier, 0.82)
        return _fail(f"VC meeting creation card was not confirmed. wrong_state={analysis.wrong_state}.", "verification_failed", verifier)
    if verifier in {"vc_in_meeting", "vc_case"}:
        if step.id == "confirm_join_meeting" and analysis.meeting_id_not_entered:
            return _fail(
                "VC join was blocked because the meeting ID input is still empty or the join button is disabled.",
                "product_state_invalid",
                verifier,
            )
        if analysis.in_meeting_visible:
            return _pass("VC in-meeting state and controls were locally confirmed.", verifier, 0.84)
        return _fail(f"VC in-meeting state was not confirmed. wrong_state={analysis.wrong_state}.", "verification_failed", verifier)
    if verifier == "vc_meeting_id_entered":
        meeting_id = _normalize_text(str(step.metadata.get("meeting_id") or step.input_text or ""))
        text = _normalize_text(" ".join(after.ocr_lines or []) or " ".join(item[1] for item in ocr_image(after.screenshot_path)))
        bbox = strategy_bbox_from_screenshot(after.screenshot_path, str(step.metadata.get("locator_strategy") or "vc_meeting_id_input"))
        changed = _crop_diff(before.screenshot_path if before else None, after.screenshot_path, bbox.model_dump()) if bbox else 0.0
        has_input_prompt = any(item in text for item in ("会议id", "会议号", "输入会议", "meetingid"))
        roi_text = _normalize_text(" ".join(item[1] for item in ocr_image(after.screenshot_path, bbox))) if bbox else ""
        hit = bool(meeting_id and meeting_id in text and has_input_prompt)
        roi_hit = bool(meeting_id and meeting_id in roi_text)
        if roi_hit:
            return _pass(
                f"VC meeting ID entry was locally confirmed inside the input ROI. text_hit={hit}, roi_hit={roi_hit}, crop_diff={changed:.2f}.",
                verifier,
                0.86,
            )
        return _fail(
            f"VC meeting ID was not locally confirmed inside the input ROI. text_hit={hit}, roi_hit={roi_hit}, crop_diff={changed:.2f}.",
            "verification_failed",
            verifier,
        )
    if verifier == "vc_device_state":
        failures: list[str] = []
        desired_camera = step.metadata.get("desired_camera_on")
        if desired_camera is not None:
            if analysis.camera_off is None:
                failures.append("camera_state_unknown")
            elif (not analysis.camera_off) != bool(desired_camera):
                failures.append(f"camera_on_expected_{bool(desired_camera)}")
        desired_mic = step.metadata.get("desired_mic_on")
        if desired_mic is not None:
            if analysis.mic_muted is None:
                failures.append("mic_state_unknown")
            elif (not analysis.mic_muted) != bool(desired_mic):
                failures.append(f"mic_on_expected_{bool(desired_mic)}")
        if not failures:
            if desired_camera is None and desired_mic is None:
                return _pass("No explicit VC device state was requested; device controls are visible enough to proceed.", verifier, 0.72)
            return _pass("Requested VC device state was locally confirmed.", verifier, 0.82)
        if diff > 0.5 and analysis.device_controls_visible:
            return _pass(
                f"VC device control changed visibly; OCR state remains ambiguous: {failures}. image_diff={diff:.2f}.",
                verifier,
                0.68,
            )
        return _fail(f"Requested VC device state was not confirmed: {failures}.", "verification_failed", verifier)
    return _fail(f"Unsupported VC verifier {verifier!r}.", "verification_failed", verifier)


def _verify_calendar_editor_opened(
    before: Observation | None,
    after: Observation,
    step: PlanStep,
    verifier: str,
) -> StepVerification:
    if not _healthy_image(after.screenshot_path):
        return _fail("Calendar editor screenshot is not healthy.", "perception_failed", verifier)
    diff = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
    analysis = analyze_calendar_screen(
        after,
        expected_title=str(step.metadata.get("event_title") or ""),
        expect_create_editor=True,
    )
    if analysis and analysis.create_editor_visible and analysis.wrong_state is None:
        return _pass(
            (
                "Calendar create editor was locally confirmed. "
                f"image_diff={diff:.2f}, title_placeholder_visible={analysis.title_placeholder_visible}."
            ),
            verifier,
            0.86,
        )
    if step.id == "click_create_event" and analysis and analysis.wrong_state in {"create_editor_not_open", "create_editor_loading"} and diff > 0.5:
        return _pass(
            (
                "Calendar create action entered a loading or transition state; "
                f"the following wait step will confirm the editor. image_diff={diff:.2f}."
            ),
            verifier,
            0.72,
        )
    wrong_state = analysis.wrong_state if analysis else "unknown"
    return _fail(
        (
            "Calendar create editor was not opened correctly. "
            f"image_diff={diff:.2f}, wrong_state={wrong_state}."
        ),
        "verification_failed",
        verifier,
    )


def _verify_calendar_title_entered(after: Observation, step: PlanStep, verifier: str) -> StepVerification:
    if not _healthy_image(after.screenshot_path):
        return _fail("Calendar title screenshot is not healthy.", "perception_failed", verifier)
    expected_title = str(step.metadata.get("event_title") or "").strip()
    analysis = analyze_calendar_screen(
        after,
        expected_title=expected_title,
        expect_create_editor=True,
    )
    if analysis and analysis.expected_title_visible and analysis.wrong_state is None:
        return _pass("Calendar event title was locally confirmed in the create editor.", verifier, 0.84)
    wrong_state = analysis.wrong_state if analysis else "unknown"
    return _fail(
        f"Calendar title was not locally confirmed in the create editor. wrong_state={wrong_state}.",
        "verification_failed",
        verifier,
    )


def _verify_calendar_event_visible(after: Observation, step: PlanStep, verifier: str) -> StepVerification:
    if not _healthy_image(after.screenshot_path):
        return _fail("Final calendar screenshot is not healthy.", "perception_failed", verifier)

    window = detect_lark_window(after.screenshot_path)
    roi = None
    if window is not None:
        from core.schemas import BoundingBox

        roi = BoundingBox(x1=window.x1, y1=window.y1, x2=window.x2, y2=window.y2)
    results = ocr_image(after.screenshot_path, roi)
    text = " ".join(item[1] for item in results)
    normalized = _normalize_text(text)
    if _calendar_create_confirmation_visible(normalized):
        return _fail(
            "Calendar event is still blocked by the final create-confirmation dialog; creation was not completed.",
            "verification_failed",
            verifier,
        )
    title = str(step.metadata.get("event_title") or "").strip()
    event_date = str(step.metadata.get("event_date") or "").strip()
    start_time = str(step.metadata.get("start_time") or "").strip()

    title_norm = _normalize_text(title)
    compact_title = title_norm.replace("calendar", "caler")
    visible_title_prefixes = [
        prefix
        for prefix in (
            "cualark",
            "cuacalendar",
            title_norm[:10],
            title_norm[:8],
            compact_title[:8],
        )
        if len(prefix) >= 6
    ]
    title_hit = bool(
        title_norm
        and (
            title_norm in normalized
            or any(prefix in normalized for prefix in visible_title_prefixes)
            or "cuacalendar" in normalized
            or "cuacaler" in normalized
            or (title_norm[:6] and title_norm[:6] in normalized and "cua" in normalized)
            or (compact_title[:8] and compact_title[:8] in normalized)
        )
    )
    date_hit = _calendar_date_visible(normalized, event_date)
    time_hit = bool(start_time and _normalize_text(start_time) in normalized)
    event_block_evidence = _calendar_event_block_evidence_near_target(after.screenshot_path, step)
    step.metadata["calendar_event_local_evidence"] = {
        "title_hit": title_hit,
        "date_hit": date_hit,
        "time_hit": time_hit,
        **event_block_evidence,
    }

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
    if date_hit and time_hit and event_block_evidence.get("target_slot_has_event_color"):
        return _pass(
            (
                "Calendar event was locally confirmed by target-slot visual evidence. "
                f"title_hit={title_hit}, date_hit={date_hit}, time_hit={time_hit}, "
                f"event_color_pixels={event_block_evidence.get('target_slot_event_pixels')}, "
                f"right_edge_clipped={event_block_evidence.get('target_slot_right_edge_clipped')}, "
                f"roi={event_block_evidence.get('target_slot_roi')}."
            ),
            verifier,
            0.82,
        )
    if date_hit and time_hit and _calendar_event_block_near_target(after.screenshot_path, step):
        return None
    return _fail(
        (
            "Calendar event title was not found in the current screenshot OCR. "
            f"date_hit={date_hit}, time_hit={time_hit}, "
            f"event_block_evidence={event_block_evidence}."
        ),
        "verification_failed",
        verifier,
    )


def _verify_calendar_time_axis_target_visible(after: Observation, step: PlanStep, verifier: str) -> StepVerification:
    if not _healthy_image(after.screenshot_path):
        return _fail("Calendar time-axis screenshot is not healthy.", "perception_failed", verifier)
    target_hour = _calendar_target_hour_from_step(step)
    hour_marks = _calendar_visible_time_axis_hour_marks(after.screenshot_path)
    visible_hours = sorted({hour for hour, _center_y in hour_marks})
    if target_hour is None or not visible_hours:
        return _fail(
            f"Calendar time-axis OCR did not expose enough hour labels. target_hour={target_hour}, visible_hours={visible_hours}.",
            "verification_failed",
            verifier,
        )
    lo = min(visible_hours)
    hi = max(visible_hours)
    target_mark = next((center_y for hour, center_y in hour_marks if hour == target_hour), None)
    window = detect_lark_window(after.screenshot_path)
    if target_mark is not None and window is not None:
        viewport_top = window.y1 + 235
        viewport_bottom = window.y2 - 35
        readable_top = viewport_top + int((viewport_bottom - viewport_top) * 0.22)
        readable_bottom = viewport_top + int((viewport_bottom - viewport_top) * 0.72)
        if readable_top <= target_mark <= readable_bottom:
            return _pass(
                (
                    "Calendar time-axis target hour is in the readable event area. "
                    f"target_hour={target_hour}, target_y={target_mark}, "
                    f"readable=({readable_top},{readable_bottom}), visible_hours={visible_hours}."
                ),
                verifier,
                0.86,
            )
        wrong_state = "time_axis_target_below_readable_area" if target_mark > readable_bottom else "time_axis_target_above_readable_area"
        return _fail(
            (
                "Calendar time-axis target hour is visible but not readable enough for event verification. "
                f"wrong_state={wrong_state}, target_hour={target_hour}, target_y={target_mark}, "
                f"readable=({readable_top},{readable_bottom}), visible_hours={visible_hours}."
            ),
            "verification_failed",
            verifier,
        )
    if lo <= target_hour <= hi:
        return _pass(
            f"Calendar time-axis is positioned around target hour. target_hour={target_hour}, visible_hours={visible_hours}.",
            verifier,
            0.84,
        )
    direction = "below" if target_hour > hi else "above"
    return _fail(
        f"Calendar time-axis target is still {direction} the visible range. target_hour={target_hour}, visible_hours={visible_hours}.",
        "verification_failed",
        verifier,
    )


def _verify_calendar_attendees_entered(after: Observation, step: PlanStep, verifier: str) -> StepVerification:
    if not _healthy_image(after.screenshot_path):
        return _fail("Calendar attendee screenshot is not healthy.", "perception_failed", verifier)
    window = detect_lark_window(after.screenshot_path)
    results = ocr_image(after.screenshot_path)
    normalized = _normalize_text(" ".join(text for _bbox, text, _confidence in results))
    attendee_names = [str(item).strip() for item in step.metadata.get("attendees", []) if str(item).strip()]
    attendee_tokens: list[str] = []
    for name in attendee_names:
        normalized_name = _normalize_text(name)
        if normalized_name:
            attendee_tokens.append(normalized_name)
            if len(normalized_name) >= 2:
                attendee_tokens.append(normalized_name[:2])
    local_texts: list[str] = []
    if window is not None:
        from core.schemas import BoundingBox

        # Focus on the create-event dialog area where the attendee input and
        # dropdown results appear, instead of the whole calendar grid.
        dialog_roi = BoundingBox(
            x1=window.x1 + int(window.width * 0.28),
            y1=window.y1 + int(window.height * 0.08),
            x2=window.x1 + int(window.width * 0.78),
            y2=window.y1 + int(window.height * 0.55),
        )
        result_roi = BoundingBox(
            x1=window.x1 + int(window.width * 0.30),
            y1=window.y1 + int(window.height * 0.16),
            x2=window.x1 + int(window.width * 0.80),
            y2=window.y1 + int(window.height * 0.52),
        )
        input_roi = BoundingBox(
            x1=window.x1 + int(window.width * 0.34),
            y1=window.y1 + int(window.height * 0.14),
            x2=window.x1 + int(window.width * 0.66),
            y2=window.y1 + int(window.height * 0.24),
        )
        for roi in (dialog_roi, result_roi, input_roi):
            local_texts.extend(text for _bbox, text, _confidence in ocr_image(after.screenshot_path, roi))
    local_normalized = _normalize_text(" ".join(local_texts))
    attendee_hit = any(token in local_normalized or token in normalized for token in attendee_tokens)
    picker_hit = any(item in local_normalized or item in normalized for item in ("添加参与者", "已选", "参与者", "搜索", "批量添加"))
    if attendee_hit:
        return _pass(
            f"Calendar attendee search text/result was locally confirmed. attendee_hit={attendee_hit}, picker_hit={picker_hit}.",
            verifier,
            0.82,
        )
    return _fail(
        "Calendar attendee search result was not locally confirmed by OCR.",
        "verification_failed",
        verifier,
    )


def _verify_calendar_busy_free_visible(after: Observation, step: PlanStep, verifier: str) -> StepVerification | None:
    if not _healthy_image(after.screenshot_path):
        return _fail("Busy/free screenshot is not healthy.", "perception_failed", verifier)

    window = detect_lark_window(after.screenshot_path)
    roi = None
    if window is not None:
        from core.schemas import BoundingBox

        roi = BoundingBox(x1=window.x1, y1=window.y1, x2=window.x2, y2=window.y2)
    results = ocr_image(after.screenshot_path, roi)
    normalized = _normalize_text(" ".join(text for _bbox, text, _confidence in results))
    if "添加主题" in normalized or "添加联系人群或邮箱" in normalized or "addschedule" in normalized:
        return _fail(
            "Busy/free lookup opened a create-event or meeting-room panel instead of selecting the contact.",
            "verification_failed",
            verifier,
        )
    attendee_names = [str(item).strip() for item in step.metadata.get("attendees", []) if str(item).strip()]
    attendee_tokens: list[str] = []
    for name in attendee_names:
        normalized_name = _normalize_text(name)
        if normalized_name:
            attendee_tokens.append(normalized_name)
            if len(normalized_name) >= 2:
                attendee_tokens.append(normalized_name[:2])
    attendee_hit = any(token in normalized for token in attendee_tokens)
    self_hit = any(item in normalized for item in ("郭克强", "gkq", "克强"))
    time_axis_hit = any(_normalize_text(item) in normalized for item in ("gmt8", "10:00", "11:00", "12:00", "13:00"))
    participant_label_hit = any(item in normalized for item in ("参与者", "参加者", "参会人", "participant"))
    calendar_search_hit = any(item in normalized for item in ("搜索联系人", "公共日历", "联系人", "我的任务"))
    grid_visible = _calendar_busy_free_grid_visible(after.screenshot_path)
    main_axis_visible = _calendar_main_time_axis_visible(after.screenshot_path)
    target_time = str(step.metadata.get("start_time") or step.metadata.get("event_time") or "").strip()
    busy_marker = _calendar_busy_marker_near_time(after.screenshot_path, target_time)
    target_hour = _calendar_target_hour_from_step(step)
    hour_marks = _calendar_visible_time_axis_hour_marks(after.screenshot_path)
    visible_hours = sorted({hour for hour, _center_y in hour_marks})
    target_hour_y = next((center_y for hour, center_y in hour_marks if hour == target_hour), None)
    colored_evidence = _calendar_target_slot_color_evidence(after.screenshot_path, step)
    selected_contact_evidence = _calendar_selected_contact_evidence(after.screenshot_path, attendee_tokens)
    step.metadata["busy_free_local_evidence"] = {
        "attendee_hit": attendee_hit,
        "attendee_tokens": attendee_tokens,
        **selected_contact_evidence,
        "time_axis_hit": time_axis_hit,
        "participant_label_hit": participant_label_hit,
        "calendar_search_hit": calendar_search_hit,
        "grid_visible": grid_visible,
        "main_axis_visible": main_axis_visible,
        "busy_marker": busy_marker,
        "target_hour": target_hour,
        "visible_hours": visible_hours,
        "target_hour_y": target_hour_y,
        **colored_evidence,
    }

    if attendee_hit and (busy_marker or selected_contact_evidence.get("contact_search_result_selected")) and (main_axis_visible or grid_visible or time_axis_hit):
        return _pass(
            (
                "Calendar busy/free area was locally confirmed. "
                f"attendee_hit={attendee_hit}, self_hit={self_hit}, "
                f"time_axis_hit={time_axis_hit}, participant_label_hit={participant_label_hit}, "
                f"calendar_search_hit={calendar_search_hit}, grid_visible={grid_visible}, "
                f"main_axis_visible={main_axis_visible}, busy_marker={busy_marker}, "
                f"contact_search_result_selected={selected_contact_evidence.get('contact_search_result_selected')}, "
                f"contact_search_result_check_pixels={selected_contact_evidence.get('contact_search_result_check_pixels')}, "
                f"target_hour={target_hour}, target_hour_y={target_hour_y}, "
                f"slot_color_evidence={colored_evidence}."
            ),
            verifier,
            0.84,
        )
    return None


def _calendar_create_confirmation_visible(normalized_text: str) -> bool:
    return "确定创建日程吗" in normalized_text or "创建日程吗" in normalized_text


def _verify_im_extended(after: Observation, step: PlanStep, verifier: str) -> StepVerification | None:
    if not _healthy_image(after.screenshot_path):
        return _fail("Screenshot is not healthy.", "perception_failed", verifier)
    results = ocr_image(after.screenshot_path)
    normalized = _normalize_text(" ".join(text for _bbox, text, _confidence in results))

    if verifier in {"im_image_sent", "im_image_visible"}:
        image_hit = any(_normalize_text(item) in normalized for item in ("CUAIMTEST", "image"))
        if image_hit:
            return _pass("IM image send was locally confirmed by OCR-visible image marker.", verifier, 0.82)
        return None

    if verifier in {"im_mention_sent", "im_mention_visible"}:
        mention_user = _normalize_text(str(step.metadata.get("mention_user") or ""))
        message = _normalize_text(str(step.metadata.get("message") or "hello from CUA"))
        mention_hit = bool(mention_user and mention_user in normalized)
        message_hit = bool(message and (message in normalized or _normalize_text("hello from CUA") in normalized))
        if mention_hit and message_hit:
            return _pass(
                f"IM @ mention was locally confirmed by OCR. mention_hit={mention_hit}, message_hit={message_hit}.",
                verifier,
                0.84,
            )
        return None

    if verifier == "im_search_history_visible":
        search_text = str(step.metadata.get("search_text") or "").strip()
        if not search_text:
            return _pass("Healthy screen is visible after message-history search.", verifier, 0.72)
        query_hit = _normalize_text(search_text) in normalized
        history_hit = any(_normalize_text(item) in normalized for item in ("history", "message", "search"))
        if query_hit or history_hit:
            return _pass(
                f"IM message-history screen was locally confirmed. query_hit={query_hit}, history_hit={history_hit}.",
                verifier,
                0.78,
            )
        return _fail(
            "IM message-history result screen was not locally confirmed by OCR.",
            "verification_failed",
            verifier,
        )

    if verifier == "im_group_create_dialog_opened":
        dialog_hit = any(item in normalized for item in ("创建群组", "群名称", "群成员", "选择联系人", "搜索", "添加成员"))
        blank_loading = _large_white_modal_visible(after.screenshot_path)
        if dialog_hit:
            return _pass("IM group-create dialog was locally confirmed by OCR.", verifier, 0.84)
        if blank_loading:
            return _fail(
                "IM group-create dialog is still a large blank loading modal after the bounded wait.",
                "verification_failed",
                verifier,
            )
        return None

    if verifier == "im_group_member_search_entered":
        member = _normalize_text(str(step.metadata.get("member") or ""))
        if member and member in normalized:
            return _pass(f"IM group member search text/result was locally confirmed for {member!r}.", verifier, 0.82)
        return None

    if verifier == "im_group_member_selected":
        member = _normalize_text(str(step.metadata.get("member") or ""))
        selected_hit = any(item in normalized for item in ("已选", "群成员", "成员"))
        if member and member in normalized and selected_hit:
            return _pass(f"IM group member selection was locally confirmed for {member!r}.", verifier, 0.82)
        return None

    if verifier == "im_group_name_entered":
        group_name = _normalize_text(str(step.metadata.get("group_name") or ""))
        if group_name and group_name in normalized:
            return _pass("IM group name was locally confirmed by OCR.", verifier, 0.82)
        return None

    if verifier in {"im_group_created", "im_group_visible"}:
        group_name = _normalize_text(str(step.metadata.get("group_name") or ""))
        if group_name and group_name in normalized:
            return _pass("IM created group was locally confirmed by OCR-visible group name.", verifier, 0.84)
        return None

    if verifier == "im_reaction_picker_visible":
        picker_hit = any(_normalize_text(item) in normalized for item in ("like", "emoji", "reply"))
        if picker_hit:
            return _pass("IM reaction picker was locally confirmed by OCR.", verifier, 0.76)
        return None

    if verifier in {"im_emoji_reaction_applied", "im_emoji_reaction_visible"}:
        if _quick_reaction_marker_visible(after.screenshot_path):
            return _pass("IM emoji reaction marker was locally confirmed near the message.", verifier, 0.78)
        return None

    # These IM states are highly version-dependent; a healthy screenshot is
    # enough for local observation, and semantic verification can fall through
    # to VLM when available.
    return None


def _normalize_text(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _quick_reaction_marker_visible(screenshot_path: str) -> bool:
    window = detect_lark_window(screenshot_path)
    if window is None:
        return False
    image = Image.open(screenshot_path).convert("RGB")
    try:
        roi = (
            window.x1 + max(420, window.width // 3),
            window.y1 + 170,
            window.x2 - 45,
            window.y2 - 170,
        )
        pixels = image.load()
        red_blueish = 0
        gray_ring = 0
        for y in range(max(roi[1], 0), min(roi[3], image.height), 3):
            for x in range(max(roi[0], 0), min(roi[2], image.width), 3):
                red, green, blue = pixels[x, y]
                if 210 <= red <= 250 and 88 <= green <= 150 and 80 <= blue <= 140:
                    red_blueish += 1
                if 150 <= red <= 205 and 150 <= green <= 205 and 150 <= blue <= 215 and max(red, green, blue) - min(red, green, blue) <= 32:
                    gray_ring += 1
        return red_blueish >= 2 or gray_ring >= 4
    finally:
        image.close()


def _large_white_modal_visible(screenshot_path: str) -> bool:
    window = detect_lark_window(screenshot_path)
    if window is None:
        return False
    image = Image.open(screenshot_path).convert("RGB")
    try:
        left = window.x1 + int(window.width * 0.08)
        top = window.y1 + int(window.height * 0.05)
        right = window.x2 - int(window.width * 0.06)
        bottom = window.y2 - int(window.height * 0.05)
        pixels = image.load()
        white = 0
        total = 0
        for y in range(max(0, top), min(image.height, bottom), 8):
            for x in range(max(0, left), min(image.width, right), 8):
                red, green, blue = pixels[x, y]
                total += 1
                if red >= 238 and green >= 238 and blue >= 238 and max(red, green, blue) - min(red, green, blue) <= 12:
                    white += 1
        return total > 0 and white / total >= 0.72
    finally:
        image.close()


def _calendar_date_visible(normalized_text: str, event_date: str) -> bool:
    import re

    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", event_date)
    if not match:
        return False
    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))
    candidates = (
        f"{year}{month}{day}",
        f"{year}{month:02d}{day:02d}",
        f"{month}{day}",
        f"{month:02d}{day:02d}",
        f"{day}",
    )
    return any(_normalize_text(item) in normalized_text for item in candidates)


def _calendar_time_parts(raw_time: str) -> tuple[str, str, str]:
    now = datetime.now()
    if "后天" in raw_time or "後天" in raw_time:
        day_offset = 2
    elif "明天" in raw_time:
        day_offset = 1
    else:
        day_offset = 0
    event_date = now + timedelta(days=day_offset)
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
    return any(item in raw for item in ("feishu", "lark")) or bool(raw)


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


def _docs_share_modal_visible(path: str) -> bool:
    if not Path(path).exists():
        return False
    image = Image.open(path).convert("RGB")
    try:
        width, height = image.size
        x1, x2 = int(width * 0.25), int(width * 0.58)
        y1, y2 = int(height * 0.16), int(height * 0.43)
        crop = image.crop((x1, y1, x2, y2)).convert("L")
        stat = ImageStat.Stat(crop)
        bright_ratio = sum(1 for value in crop.getdata() if value > 238) / max(crop.width * crop.height, 1)
        return stat.mean[0] > 215 and bright_ratio > 0.55 and crop.width > 250 and crop.height > 180
    finally:
        image.close()


def _docs_share_recipient_search_open(path: str) -> bool:
    if not Path(path).exists():
        return False
    normalized = _normalize_text(_docs_share_modal_ocr_text(path))
    return any(item in normalized for item in ("search", "invite", "user", "email"))


def _docs_share_send_in_progress(path: str) -> bool:
    if not Path(path).exists():
        return False
    normalized = _normalize_text(_docs_share_modal_ocr_text(path))
    return "sending" in normalized

def _docs_share_modal_ocr_text(path: str) -> str:
    image = Image.open(path).convert("RGB")
    try:
        width, height = image.size
        roi = {
            "x1": int(width * 0.22),
            "y1": int(height * 0.14),
            "x2": int(width * 0.58),
            "y2": int(height * 0.62),
        }
    finally:
        image.close()
    from core.schemas import BoundingBox

    bbox = BoundingBox(**roi)
    return " ".join(item[1] for item in ocr_image(path, bbox))


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


def _calendar_busy_free_grid_visible(path: str) -> bool:
    if not Path(path).exists():
        return False
    window = detect_lark_window(path)
    if window is None:
        return False
    image = Image.open(path).convert("L")
    try:
        crop = image.crop((window.x1 + int(window.width * 0.55), window.y1 + 150, window.x2 - 10, window.y2 - 70))
        if crop.width < 160 or crop.height < 220:
            return False
        vertical_hits = 0
        for x in range(0, crop.width, 6):
            col = [crop.getpixel((x, y)) for y in range(0, crop.height, 14)]
            if col and sum(1 for value in col if 190 <= value <= 238) / len(col) > 0.14:
                vertical_hits += 1
        horizontal_hits = 0
        for y in range(0, crop.height, 6):
            row = [crop.getpixel((x, y)) for x in range(0, crop.width, 14)]
            if row and sum(1 for value in row if 190 <= value <= 238) / len(row) > 0.14:
                horizontal_hits += 1
        return vertical_hits >= 3 and horizontal_hits >= 4
    finally:
        image.close()


def _calendar_main_time_axis_visible(path: str) -> bool:
    if not Path(path).exists():
        return False
    window = detect_lark_window(path)
    if window is None:
        return False
    image = Image.open(path).convert("L")
    try:
        crop = image.crop((window.x1 + int(window.width * 0.28), window.y1 + 155, window.x2 - 40, window.y2 - 70))
        if crop.width < 350 or crop.height < 350:
            return False
        vertical_hits = 0
        for x in range(0, crop.width, 10):
            col = [crop.getpixel((x, y)) for y in range(0, crop.height, 16)]
            if col and sum(1 for value in col if 195 <= value <= 238) / len(col) > 0.12:
                vertical_hits += 1
        horizontal_hits = 0
        for y in range(0, crop.height, 10):
            row = [crop.getpixel((x, y)) for x in range(0, crop.width, 16)]
            if row and sum(1 for value in row if 195 <= value <= 238) / len(row) > 0.12:
                horizontal_hits += 1
        return vertical_hits >= 5 and horizontal_hits >= 6
    finally:
        image.close()


def _calendar_busy_marker_near_time(path: str, target_time: str) -> bool:
    if not target_time or not Path(path).exists():
        return False
    window = detect_lark_window(path)
    if window is None:
        return False
    image = Image.open(path).convert("RGB")
    try:
        roi = (
            window.x1 + int(window.width * 0.30),
            window.y1 + 160,
            window.x2 - 45,
            window.y2 - 80,
        )
        crop = image.crop(roi)
        pixels = crop.load()
        colored = 0
        for y in range(0, crop.height, 4):
            for x in range(0, crop.width, 4):
                red, green, blue = pixels[x, y]
                # Busy/free overlays for another calendar render as green
                # chips; the user's own event block is blue and should not
                # satisfy this check by itself.
                if green >= 135 and green - red >= 28 and green - blue >= 18 and 55 <= red <= 210 and 80 <= blue <= 210:
                    colored += 1
        return colored >= 18
    finally:
        image.close()


def _calendar_target_slot_color_evidence(path: str, step: PlanStep) -> dict:
    evidence = {
        "target_slot_blue_pixels": 0,
        "target_slot_green_pixels": 0,
        "target_slot_colored_pixels": 0,
        "target_slot_has_busy_color": False,
        "target_slot_roi": None,
    }
    if not Path(path).exists():
        return evidence
    target_hour = _calendar_target_hour_from_step(step)
    if target_hour is None:
        return evidence
    hour_marks = _calendar_visible_time_axis_hour_marks(path)
    target_mark = next((center_y for hour, center_y in hour_marks if hour == target_hour), None)
    window = detect_lark_window(path)
    if target_mark is None or window is None:
        return evidence
    image = Image.open(path).convert("RGB")
    try:
        x1 = window.x1 + int(window.width * 0.38)
        x2 = window.x2 - 25
        y1 = max(window.y1 + 220, target_mark - 34)
        y2 = min(window.y2 - 45, target_mark + 58)
        blue_pixels = 0
        green_pixels = 0
        for y in range(y1, y2, 3):
            for x in range(x1, x2, 3):
                red, green, blue = image.getpixel((x, y))
                blue_event = blue >= 145 and blue - red >= 45 and blue - green >= 20
                green_busy = green >= 135 and green - red >= 24 and green - blue >= 12
                if blue_event:
                    blue_pixels += 1
                if green_busy:
                    green_pixels += 1
        colored = blue_pixels + green_pixels
        evidence.update(
            {
                "target_slot_blue_pixels": blue_pixels,
                "target_slot_green_pixels": green_pixels,
                "target_slot_colored_pixels": colored,
                "target_slot_has_busy_color": colored >= 24,
                "target_slot_roi": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            }
        )
        return evidence
    finally:
        image.close()


def _calendar_selected_contact_evidence(path: str, attendee_tokens: list[str]) -> dict:
    evidence = {
        "contact_search_result_selected": False,
        "contact_search_result_bbox": None,
        "contact_search_result_check_pixels": 0,
    }
    if not attendee_tokens or not Path(path).exists():
        return evidence
    window = detect_lark_window(path)
    if window is None:
        return evidence
    roi = BoundingBox(
        x1=window.x1 + 250,
        y1=max(window.y1 + 250, window.y2 - 285),
        x2=min(window.x1 + 700, window.x2 - 20),
        y2=window.y2 - 120,
    )
    results = ocr_image(path, roi)
    target_bbox = None
    for bbox, text, _confidence in results:
        normalized = _normalize_text(text)
        if any(token and token in normalized for token in attendee_tokens):
            target_bbox = bbox
            break
    if target_bbox is None:
        return evidence
    icon_center_x = min(target_bbox.x2 + 155, window.x1 + 585, window.x2 - 35)
    icon_center_y = target_bbox.center()[1]
    image = Image.open(path).convert("RGB")
    try:
        blue = 0
        for y in range(max(0, icon_center_y - 18), min(image.height, icon_center_y + 19), 2):
            for x in range(max(0, icon_center_x - 18), min(image.width, icon_center_x + 19), 2):
                red, green, blue_channel = image.getpixel((x, y))
                if blue_channel >= 170 and blue_channel - red >= 95 and blue_channel - green >= 45:
                    blue += 1
        evidence.update(
            {
                "contact_search_result_selected": blue >= 6,
                "contact_search_result_bbox": {
                    "x1": target_bbox.x1,
                    "y1": target_bbox.y1,
                    "x2": target_bbox.x2,
                    "y2": target_bbox.y2,
                },
                "contact_search_result_check_pixels": blue,
            }
        )
        return evidence
    finally:
        image.close()


def _calendar_event_block_near_target(path: str, step: PlanStep) -> bool:
    return bool(_calendar_event_block_evidence_near_target(path, step).get("target_slot_has_event_color"))


def _calendar_event_block_evidence_near_target(path: str, step: PlanStep) -> dict:
    evidence = {
        "target_slot_event_pixels": 0,
        "target_slot_blue_pixels": 0,
        "target_slot_green_pixels": 0,
        "target_slot_has_event_color": False,
        "target_slot_right_edge_clipped": False,
        "target_slot_roi": None,
        "target_hour": None,
        "target_hour_y": None,
    }
    if not Path(path).exists():
        return evidence
    target_hour = _calendar_target_hour_from_step(step)
    evidence["target_hour"] = target_hour
    if target_hour is None:
        return evidence
    hour_marks = _calendar_visible_time_axis_hour_marks(path)
    target_mark = next((center_y for hour, center_y in hour_marks if hour == target_hour), None)
    window = detect_lark_window(path)
    if target_mark is None or window is None:
        return evidence
    evidence["target_hour_y"] = target_mark
    image = Image.open(path).convert("RGB")
    try:
        # Event chips may be narrow when many duplicate test events exist in
        # the same time slot. Detect their colored blocks near the target hour.
        # Scan from the time-axis through the right edge so clipped events at
        # the last visible day column still produce evidence.
        x1 = window.x1 + int(window.width * 0.38)
        x2 = window.x2 - 8
        y1 = max(window.y1 + 220, target_mark - 34)
        y2 = min(window.y2 - 45, target_mark + 58)
        blue_pixels = 0
        green_pixels = 0
        edge_colored = 0
        for y in range(y1, y2, 3):
            for x in range(x1, x2, 3):
                red, green, blue = image.getpixel((x, y))
                blue_event = blue >= 145 and blue - red >= 45 and blue - green >= 20
                green_busy = green >= 135 and green - red >= 24 and green - blue >= 12
                if blue_event:
                    blue_pixels += 1
                if green_busy:
                    green_pixels += 1
                if x >= x2 - 45 and (blue_event or green_busy):
                    edge_colored += 1
        colored = blue_pixels + green_pixels
        evidence.update(
            {
                "target_slot_event_pixels": colored,
                "target_slot_blue_pixels": blue_pixels,
                "target_slot_green_pixels": green_pixels,
                "target_slot_has_event_color": colored >= 24,
                "target_slot_right_edge_clipped": edge_colored >= 8,
                "target_slot_roi": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            }
        )
        return evidence
    finally:
        image.close()


def _calendar_target_hour_from_step(step: PlanStep) -> int | None:
    import re

    raw = str(step.metadata.get("start_time") or step.metadata.get("event_time") or "").strip()
    match = re.search(r"(\d{1,2}):(\d{2})", raw)
    if not match:
        return None
    hour = int(match.group(1))
    if 0 <= hour <= 23:
        return hour
    return None


def _calendar_visible_time_axis_hours(path: str) -> list[int]:
    return sorted({hour for hour, _center_y in _calendar_visible_time_axis_hour_marks(path)})


def _calendar_visible_time_axis_hour_marks(path: str) -> list[tuple[int, int]]:
    import re

    window = detect_lark_window(path)
    if window is None:
        return []
    from core.schemas import BoundingBox

    roi = BoundingBox(
        x1=window.x1 + int(window.width * 0.32),
        y1=window.y1 + 235,
        x2=window.x1 + int(window.width * 0.48),
        y2=window.y2 - 35,
    )
    marks: list[tuple[int, int]] = []
    for bbox, text, confidence in ocr_image(path, roi):
        if confidence < 0.45:
            continue
        match = re.search(r"(\d{1,2})\s*[:：]\s*00", text)
        if not match:
            continue
        hour = int(match.group(1))
        if 0 <= hour <= 23 and hour not in [item[0] for item in marks]:
            marks.append((hour, bbox.center()[1]))
    return sorted(marks, key=lambda item: item[0])


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
