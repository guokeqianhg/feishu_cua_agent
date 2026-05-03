from __future__ import annotations

from pathlib import Path

from agent.state import AgentState
from app.config import settings
from core.schemas import ActionResult, LocatedTarget, PlanStep
from storage.run_logger import RunLogger
from tools.desktop.executor import ActionExecutor
from tools.desktop.window_manager import WindowManager
from tools.vision.docs_error_library import analyze_docs_screen
from tools.vision.im_error_library import analyze_im_screen
from tools.vision.vc_error_library import analyze_vc_screen


logger = RunLogger()
window = WindowManager()


def _abort_requested() -> bool:
    return Path(settings.abort_file).exists()


def _is_lark_title(title: str) -> bool:
    raw = (title or "").lower()
    if _is_known_non_lark_host_title(raw):
        return False
    return any(keyword.lower() in raw for keyword in ("飞书", "feishu", "lark"))


def _foreground_keywords(step: PlanStep) -> list[str]:
    raw = step.metadata.get("foreground_window_keywords")
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw if str(item).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def _title_matches_keywords(title: str, keywords: list[str]) -> bool:
    raw = (title or "").lower()
    if _is_known_non_lark_host_title(raw):
        return False
    return any(keyword.lower() in raw for keyword in keywords)


def _is_known_non_lark_host_title(raw_title: str) -> bool:
    return any(
        item in raw_title
        for item in (
            "visual studio code",
            "powershell",
            "windows terminal",
            "cmd.exe",
            "chatgpt",
            "google gemini",
            "github",
        )
    )


def _needs_focus(step: PlanStep, dry_run: bool | None) -> bool:
    if dry_run:
        return False
    if step.metadata.get("preserve_foreground"):
        return False
    return step.action in (
        "click",
        "conditional_click",
        "double_click",
        "right_click",
        "drag",
        "hover",
        "type_text",
        "hotkey",
        "conditional_hotkey",
    )


def _preview_text(state: AgentState, mode: str = "manual") -> str:
    step = state.current_step()
    target = state.last_located_target
    before = state.before_observation.screenshot_path if state.before_observation else None
    active_title = window.get_active_window_title()
    if step is None:
        return "No current step."
    warnings = target.warnings if target else []
    will_refocus = _will_refocus_before_execute(step, active_title, state.dry_run)
    return "\n".join(
        [
            "",
            f"即将执行步骤 / Action Preview ({mode})",
            f"- step: {step.id}",
            f"- action: {step.action}",
            f"- target: {step.target_description or ''}",
            f"- input_text: {step.input_text or ''}",
            f"- hotkeys: {'+'.join(step.hotkeys) if step.hotkeys else ''}",
            f"- candidate_center: {target.center if target else None}",
            f"- candidate_bbox: {target.bbox.model_dump() if target and target.bbox else None}",
            f"- locator_source: {target.source if target else None}",
            f"- confidence: {target.confidence if target else None}",
            f"- bbox_area_ratio: {target.bbox_area_ratio if target else None}",
            f"- warnings: {warnings}",
            f"- recommended_action: {target.recommended_action if target else 'continue'}",
            f"- active_window_title: {active_title}",
            f"- will_refocus_before_execute: {will_refocus}",
            f"- before_screenshot: {before}",
            "请选择: y=继续, n=跳过, q=终止, c x y=使用手动坐标执行本步"
            if mode == "manual"
            else "auto-debug: 将自动执行；如定位/窗口/动作/验证异常会自动中断。",
        ]
    )


def _ask_user(state: AgentState) -> tuple[str, tuple[int, int] | None]:
    print(_preview_text(state), flush=True)
    while True:
        answer = input("> ").strip().lower()
        if answer in ("y", "yes"):
            return "yes", None
        if answer in ("n", "no", "skip"):
            return "skip", None
        if answer in ("q", "quit", "abort"):
            return "abort", None
        parts = answer.split()
        if len(parts) == 3 and parts[0] == "c":
            try:
                return "manual_coordinate", (int(parts[1]), int(parts[2]))
            except ValueError:
                pass
        print("请输入 y / n / q，或 c x y（例如 c 120 300）。", flush=True)


def _apply_manual_coordinate(state: AgentState, coords: tuple[int, int]) -> None:
    step = state.current_step()
    if step is None:
        return
    if state.last_located_target is None:
        state.last_located_target = LocatedTarget(
            step_id=step.id,
            target_description=step.target_description,
            source="manual",
            center=coords,
            confidence=1.0,
            reason="Manual coordinate supplied in step-by-step mode.",
        )
        return
    state.last_located_target.center = coords
    state.last_located_target.source = "manual"
    state.last_located_target.confidence = 1.0
    state.last_located_target.reason = "Manual coordinate supplied in step-by-step mode."
    state.last_located_target.recommended_action = "continue"


def _auto_debug_precheck(state: AgentState, step: PlanStep) -> ActionResult | None:
    target = state.last_located_target
    if target is None:
        return None
    if step.action in {"conditional_click", "conditional_hotkey"} and (
        target.confidence <= 0 or target.recommended_action == "skip"
    ):
        return None
    if target.warnings or target.recommended_action != "continue":
        message = (
            f"Auto-debug blocked step {step.id}: recommended_action={target.recommended_action}, "
            f"warnings={target.warnings}"
        )
        return ActionResult(
            success=False,
            message=message,
            action=step.action,
            dry_run=bool(state.dry_run),
            coordinates=target.center,
            input_text=step.input_text,
            hotkeys=step.hotkeys,
            error_message=message,
        )
    return None


def _mutation_policy_precheck(state: AgentState, step: PlanStep) -> ActionResult | None:
    if state.dry_run:
        return None
    if step.metadata.get("requires_doc_create_guard"):
        docs_error = _docs_state_precheck(state, step)
        if docs_error is not None:
            return docs_error
        if settings.allow_doc_create:
            return None
        message = (
            f"Guarded Docs create workflow blocked step {step.id}: "
            "CUA_LARK_ALLOW_DOC_CREATE is not true."
        )
        return ActionResult(
            success=False,
            message=message,
            action=step.action,
            dry_run=bool(state.dry_run),
            coordinates=state.last_located_target.center if state.last_located_target else None,
            input_text=step.input_text,
            hotkeys=step.hotkeys,
            error_message=message,
        )
    if step.metadata.get("requires_doc_share_guard") or step.metadata.get("dangerous_doc_share"):
        docs_error = _docs_state_precheck(state, step)
        if docs_error is not None:
            return docs_error
        if settings.allow_doc_share and _doc_share_recipient_allowed(step):
            return None
        reasons = _doc_share_recipient_block_reasons(step)
        if not settings.allow_doc_share:
            reasons.insert(0, "CUA_LARK_ALLOW_DOC_SHARE is not true")
        message = f"Guarded Docs share workflow blocked step {step.id}: " + "; ".join(reasons)
        return ActionResult(
            success=False,
            message=message,
            action=step.action,
            dry_run=bool(state.dry_run),
            coordinates=state.last_located_target.center if state.last_located_target else None,
            input_text=step.input_text,
            hotkeys=step.hotkeys,
            error_message=message,
        )
    if step.metadata.get("requires_calendar_create_guard") or step.metadata.get("dangerous_calendar_create"):
        if settings.allow_calendar_create:
            return None
        message = (
            f"Guarded Calendar create workflow blocked step {step.id}: "
            "CUA_LARK_ALLOW_CALENDAR_CREATE is not true."
        )
        return ActionResult(
            success=False,
            message=message,
            action=step.action,
            dry_run=bool(state.dry_run),
            coordinates=state.last_located_target.center if state.last_located_target else None,
            input_text=step.input_text,
            hotkeys=step.hotkeys,
            error_message=message,
        )
    if step.metadata.get("requires_calendar_invite_guard"):
        if settings.allow_calendar_invite:
            return None
        message = (
            f"Guarded Calendar invite workflow blocked step {step.id}: "
            "CUA_LARK_ALLOW_CALENDAR_INVITE is not true."
        )
        return ActionResult(
            success=False,
            message=message,
            action=step.action,
            dry_run=bool(state.dry_run),
            coordinates=state.last_located_target.center if state.last_located_target else None,
            input_text=step.input_text,
            hotkeys=step.hotkeys,
            error_message=message,
        )
    if step.metadata.get("requires_calendar_modify_guard") or step.metadata.get("dangerous_calendar_modify"):
        if settings.allow_calendar_modify:
            return None
        message = (
            f"Guarded Calendar modify workflow blocked step {step.id}: "
            "CUA_LARK_ALLOW_CALENDAR_MODIFY is not true."
        )
        return ActionResult(
            success=False,
            message=message,
            action=step.action,
            dry_run=bool(state.dry_run),
            coordinates=state.last_located_target.center if state.last_located_target else None,
            input_text=step.input_text,
            hotkeys=step.hotkeys,
            error_message=message,
        )
    if step.metadata.get("requires_vc_start_guard") or step.metadata.get("dangerous_vc_start"):
        vc_error = _vc_state_precheck(state, step)
        if vc_error is not None:
            return vc_error
        if settings.allow_vc_start:
            return None
        message = f"Guarded VC start workflow blocked step {step.id}: CUA_LARK_ALLOW_VC_START is not true."
        return ActionResult(
            success=False,
            message=message,
            action=step.action,
            dry_run=bool(state.dry_run),
            coordinates=state.last_located_target.center if state.last_located_target else None,
            input_text=step.input_text,
            hotkeys=step.hotkeys,
            error_message=message,
        )
    if step.metadata.get("requires_vc_join_guard") or step.metadata.get("dangerous_vc_join"):
        vc_error = _vc_state_precheck(state, step)
        if vc_error is not None:
            return vc_error
        if settings.allow_vc_join:
            return None
        message = f"Guarded VC join workflow blocked step {step.id}: CUA_LARK_ALLOW_VC_JOIN is not true."
        return ActionResult(
            success=False,
            message=message,
            action=step.action,
            dry_run=bool(state.dry_run),
            coordinates=state.last_located_target.center if state.last_located_target else None,
            input_text=step.input_text,
            hotkeys=step.hotkeys,
            error_message=message,
        )
    if step.metadata.get("requires_vc_device_toggle_guard") or step.metadata.get("dangerous_vc_device_toggle"):
        vc_error = _vc_state_precheck(state, step)
        if vc_error is not None:
            return vc_error
        if settings.allow_vc_device_toggle:
            return None
        message = f"Guarded VC device workflow blocked step {step.id}: CUA_LARK_ALLOW_VC_DEVICE_TOGGLE is not true."
        return ActionResult(
            success=False,
            message=message,
            action=step.action,
            dry_run=bool(state.dry_run),
            coordinates=state.last_located_target.center if state.last_located_target else None,
            input_text=step.input_text,
            hotkeys=step.hotkeys,
            error_message=message,
        )
    if step.metadata.get("requires_image_send_guard") or step.metadata.get("dangerous_image_send"):
        chat_error = _im_current_chat_precheck(state, step)
        if chat_error is not None:
            return chat_error
        if settings.allow_send_image and _im_target_allowed(step):
            return None
        reasons = _im_target_block_reasons(step)
        if not settings.allow_send_image:
            reasons.insert(0, "CUA_LARK_ALLOW_SEND_IMAGE is not true")
        message = f"Guarded IM image workflow blocked step {step.id}: " + "; ".join(reasons)
        return ActionResult(
            success=False,
            message=message,
            action=step.action,
            dry_run=bool(state.dry_run),
            coordinates=state.last_located_target.center if state.last_located_target else None,
            input_text=step.input_text,
            hotkeys=step.hotkeys,
            error_message=message,
        )
    if step.metadata.get("requires_group_create_guard") or step.metadata.get("dangerous_group_create"):
        member_reasons = _group_member_block_reasons(step)
        if settings.allow_create_group and not member_reasons:
            return None
        reasons = member_reasons
        if not settings.allow_create_group:
            reasons.insert(0, "CUA_LARK_ALLOW_CREATE_GROUP is not true")
        message = f"Guarded IM group-create workflow blocked step {step.id}: " + "; ".join(reasons)
        return ActionResult(
            success=False,
            message=message,
            action=step.action,
            dry_run=bool(state.dry_run),
            coordinates=state.last_located_target.center if state.last_located_target else None,
            input_text=step.input_text,
            hotkeys=step.hotkeys,
            error_message=message,
        )
    if step.metadata.get("requires_emoji_reaction_guard") or step.metadata.get("dangerous_emoji_reaction"):
        chat_error = _im_current_chat_precheck(state, step)
        if chat_error is not None:
            return chat_error
        if settings.allow_emoji_reaction and _im_target_allowed(step):
            return None
        reasons = _im_target_block_reasons(step)
        if not settings.allow_emoji_reaction:
            reasons.insert(0, "CUA_LARK_ALLOW_EMOJI_REACTION is not true")
        message = f"Guarded IM emoji workflow blocked step {step.id}: " + "; ".join(reasons)
        return ActionResult(
            success=False,
            message=message,
            action=step.action,
            dry_run=bool(state.dry_run),
            coordinates=state.last_located_target.center if state.last_located_target else None,
            input_text=step.input_text,
            hotkeys=step.hotkeys,
            error_message=message,
        )
    if not step.metadata.get("requires_send_guard") and not step.metadata.get("dangerous_send"):
        return None
    chat_error = _im_current_chat_precheck(state, step)
    if chat_error is not None:
        return chat_error
    reasons = _im_target_block_reasons(step)
    if not settings.allow_send_message:
        reasons.insert(0, "CUA_LARK_ALLOW_SEND_MESSAGE is not true")
    if not reasons:
        return None
    message = (
        f"Guarded IM send workflow blocked step {step.id}: "
        + "; ".join(reasons)
        + ". CUA_LARK_ALLOWED_IM_TARGET is optional; when configured, it limits real sends to that exact target."
    )
    return ActionResult(
        success=False,
        message=message,
        action=step.action,
        dry_run=bool(state.dry_run),
        coordinates=state.last_located_target.center if state.last_located_target else None,
        input_text=step.input_text,
        hotkeys=step.hotkeys,
        error_message=message,
    )


def _im_target_allowed(step: PlanStep) -> bool:
    return not _im_target_block_reasons(step)


def _doc_share_recipient_allowed(step: PlanStep) -> bool:
    return not _doc_share_recipient_block_reasons(step)


def _doc_share_recipient_block_reasons(step: PlanStep) -> list[str]:
    recipient = str(step.metadata.get("share_recipient") or "")
    allowed = settings.allowed_doc_share_recipient.strip()
    if allowed and recipient and recipient != allowed:
        return [f"share recipient {recipient!r} does not match CUA_LARK_ALLOWED_DOC_SHARE_RECIPIENT"]
    return []


def _im_target_block_reasons(step: PlanStep) -> list[str]:
    target = str(step.metadata.get("target") or "")
    allowed_target = settings.allowed_im_target.strip()
    if allowed_target and target and target != allowed_target:
        return [f"case target {target!r} does not match CUA_LARK_ALLOWED_IM_TARGET"]
    return []


def _group_member_block_reasons(step: PlanStep) -> list[str]:
    allowed = settings.allowed_group_member.strip()
    if not allowed:
        return []
    raw_members = step.metadata.get("group_members") or step.metadata.get("members") or []
    if isinstance(raw_members, str):
        members = [raw_members]
    else:
        members = [str(item) for item in raw_members]
    blocked = [member for member in members if member and member != allowed]
    if blocked:
        return [f"group members {blocked!r} do not match CUA_LARK_ALLOWED_GROUP_MEMBER"]
    return []


def _im_current_chat_precheck(state: AgentState, step: PlanStep) -> ActionResult | None:
    if step.metadata.get("guard_phase") == "open_chat":
        return None
    if step.id in {"open_im", "focus_search", "type_query", "type_safe_query", "type_history_query"}:
        return None
    target = str(step.metadata.get("target") or "").strip()
    if not target:
        return None
    analysis = analyze_im_screen(state.before_observation, target)
    if analysis is None:
        return None
    if analysis.is_target_chat:
        return None
    if analysis.reference_match:
        reason = f"known IM error reference matched: {analysis.reference_match} ({analysis.reference_similarity:.2f})"
    elif analysis.wrong_state:
        reason = f"wrong IM state detected: {analysis.wrong_state}"
    else:
        reason = f"target chat {target!r} is not visible before guarded IM action"
    message = (
        f"Guarded IM workflow blocked step {step.id}: {reason}. "
        "Reopen the allowed target chat before drafting, sending, image upload, mention, or reaction."
    )
    return ActionResult(
        success=False,
        message=message,
        action=step.action,
        dry_run=bool(state.dry_run),
        coordinates=state.last_located_target.center if state.last_located_target else None,
        input_text=step.input_text,
        hotkeys=step.hotkeys,
        error_message=message,
    )


def _docs_state_precheck(state: AgentState, step: PlanStep) -> ActionResult | None:
    if step.id in {
        "click_create_doc",
        "click_blank_doc",
        "click_blank_doc_card",
        "focus_docs_editor_window",
        "wait_doc_editor",
        "type_doc_title",
        "move_to_doc_body",
        "type_doc_body",
    }:
        return None
    analysis = analyze_docs_screen(
        state.before_observation,
        expected_recipient=str(step.metadata.get("share_recipient") or ""),
        expected_title=str(step.metadata.get("doc_title") or ""),
        expected_body=str(step.metadata.get("doc_body") or ""),
    )
    if analysis is None or analysis.wrong_state is None:
        return None
    if analysis.wrong_state == "share_target_not_confirmed" and step.id not in {
        "select_doc_share_recipient",
        "add_doc_share_recipient",
        "confirm_doc_share",
    }:
        return None
    message = (
        f"Guarded Docs workflow blocked step {step.id}: "
        f"wrong Docs state detected: {analysis.wrong_state}. "
        "Recover or fail instead of continuing blind UI actions."
    )
    return ActionResult(
        success=False,
        message=message,
        action=step.action,
        dry_run=bool(state.dry_run),
        coordinates=state.last_located_target.center if state.last_located_target else None,
        input_text=step.input_text,
        hotkeys=step.hotkeys,
        error_message=message,
    )


def _vc_state_precheck(state: AgentState, step: PlanStep) -> ActionResult | None:
    if step.id in {
        "open_vc",
        "wait_vc_screen",
        "click_vc_start_meeting",
        "click_vc_join_meeting",
        "type_vc_meeting_id",
        "type_vc_meeting_title",
        "allow_vc_permission",
        "set_vc_camera_state",
        "set_vc_mic_state",
        "confirm_start_meeting",
        "confirm_join_meeting",
    }:
        return None
    analysis = analyze_vc_screen(state.before_observation)
    if analysis is None or analysis.wrong_state is None:
        return None
    message = (
        f"Guarded VC workflow blocked step {step.id}: wrong VC state detected: {analysis.wrong_state}. "
        "Recover or fail instead of continuing blind UI actions."
    )
    return ActionResult(
        success=False,
        message=message,
        action=step.action,
        dry_run=bool(state.dry_run),
        coordinates=state.last_located_target.center if state.last_located_target else None,
        input_text=step.input_text,
        hotkeys=step.hotkeys,
        error_message=message,
    )


def _conditional_action_precheck(state: AgentState, step: PlanStep) -> ActionResult | None:
    if step.action not in {"conditional_click", "conditional_hotkey"}:
        return None
    target = state.last_located_target
    if target is not None and target.confidence > 0 and not target.warnings:
        return None
    skip_reason = str((target.metadata if target else {}).get("skip_reason") or "").strip()
    if skip_reason:
        message = f"Conditional step {step.id} skipped: {skip_reason}. {target.reason if target else ''}".strip()
    else:
        message = f"Conditional step {step.id} skipped because its visual condition is not present."
    return ActionResult(
        success=True,
        message=message,
        action=step.action,
        dry_run=bool(state.dry_run),
        coordinates=target.center if target else None,
        input_text=step.input_text,
        hotkeys=step.hotkeys,
        skipped=True,
    )


def _focus_before_execute(state: AgentState, step: PlanStep) -> ActionResult | None:
    if not _needs_focus(step, state.dry_run):
        return None

    keywords = _foreground_keywords(step)
    active_title_before = window.get_active_window_title()
    if step.metadata.get("focus_vc_meeting"):
        already_focused = _title_matches_keywords(
            active_title_before,
            ["飞书会议", "Feishu Meeting", "Lark Meeting"],
        )
    else:
        already_focused = _title_matches_keywords(active_title_before, keywords) if keywords else _is_lark_title(active_title_before)
    if already_focused:
        logger.log(
            state,
            "execute",
            "Foreground window already matches before action",
            step_id=step.id,
            foreground_window_keywords=keywords,
            active_window_title=active_title_before,
        )
        return None

    if step.metadata.get("focus_vc_meeting"):
        focused = window.focus_lark_meeting()
    else:
        focused = window.focus_window_by_keywords(keywords) if keywords else window.focus_lark()
    active_title_after = window.get_active_window_title()
    logger.log(
        state,
        "execute",
        "Foreground window checked before action",
        step_id=step.id,
        focused_lark=focused,
        foreground_window_keywords=keywords,
        active_window_title_before=active_title_before,
        active_window_title=active_title_after,
    )
    if step.metadata.get("focus_vc_meeting"):
        if focused or _title_matches_keywords(active_title_after, ["飞书会议", "Feishu Meeting", "Lark Meeting"]):
            return None
    elif focused or (_title_matches_keywords(active_title_after, keywords) if keywords else _is_lark_title(active_title_after)):
        return None

    message = (
        "Refocus target window before action failed. "
        f"Active window is {active_title_after!r}. Action was blocked to avoid operating the wrong window."
    )
    return ActionResult(
        success=False,
        message=message,
        action=step.action,
        dry_run=bool(state.dry_run),
        coordinates=state.last_located_target.center if state.last_located_target else None,
        input_text=step.input_text,
        hotkeys=step.hotkeys,
        error_message=message,
    )


def _will_refocus_before_execute(step: PlanStep, active_title: str, dry_run: bool | None) -> bool:
    if not _needs_focus(step, dry_run):
        return False
    keywords = _foreground_keywords(step)
    if step.metadata.get("focus_vc_meeting"):
        return not _title_matches_keywords(active_title, ["飞书会议", "Feishu Meeting", "Lark Meeting"])
    return not (_title_matches_keywords(active_title, keywords) if keywords else _is_lark_title(active_title))


def execute_node(state: AgentState) -> AgentState:
    step = state.current_step()
    if step is None:
        state.status = "fail"
        state.failure_category = "planning_failed"
        state.error = "No current step available."
        return state

    if _abort_requested():
        state.status = "aborted"
        state.aborted_step_id = step.id
        state.error = f"Abort file detected before step {step.id}: {settings.abort_file}"
        logger.log(state, "execute", "Execution aborted by ABORT file", step_id=step.id, abort_file=settings.abort_file)
        return state

    user_decision = "auto"
    user_confirmed = None
    manual_coords = None
    if state.step_by_step:
        user_decision, manual_coords = _ask_user(state)
        user_confirmed = user_decision in ("yes", "manual_coordinate")
        if user_decision == "abort":
            state.status = "aborted"
            state.aborted_step_id = step.id
            state.error = f"User aborted before step {step.id}."
            state.last_action_result = ActionResult(
                success=False,
                message=state.error,
                action=step.action,
                dry_run=bool(state.dry_run),
                coordinates=state.last_located_target.center if state.last_located_target else None,
                input_text=step.input_text,
                hotkeys=step.hotkeys,
                user_confirmed=False,
                user_decision="abort",
                error_message=state.error,
            )
            logger.log(state, "execute", "Execution aborted by user", step_id=step.id)
            return state
        if user_decision == "skip":
            state.skip_current_step = True
            state.last_action_result = ActionResult(
                success=True,
                message=f"Step {step.id} skipped by user.",
                action=step.action,
                dry_run=bool(state.dry_run),
                coordinates=state.last_located_target.center if state.last_located_target else None,
                input_text=step.input_text,
                hotkeys=step.hotkeys,
                user_confirmed=False,
                user_decision="skip",
                skipped=True,
            )
            logger.log(state, "execute", "Step skipped by user", step_id=step.id)
            return state
        if manual_coords is not None:
            _apply_manual_coordinate(state, manual_coords)
    elif state.auto_debug:
        print(_preview_text(state, mode="auto"), flush=True)
        precheck_error = _auto_debug_precheck(state, step)
        if precheck_error is not None:
            precheck_error.user_decision = "auto"
            state.last_action_result = precheck_error
            state.status = "fail"
            state.failure_category = "action_failed"
            state.error = precheck_error.error_message or precheck_error.message
            logger.log(state, "execute", "Auto-debug precheck blocked action", step_id=step.id, result=precheck_error.model_dump())
            return state

    mutation_policy_error = _mutation_policy_precheck(state, step)
    if mutation_policy_error is not None:
        mutation_policy_error.user_confirmed = user_confirmed
        mutation_policy_error.user_decision = user_decision
        state.last_action_result = mutation_policy_error
        state.status = "fail"
        state.failure_category = "permission_denied"
        state.error = mutation_policy_error.error_message or mutation_policy_error.message
        logger.log(state, "execute", "Guarded mutation policy blocked action", step_id=step.id, result=mutation_policy_error.model_dump())
        return state

    conditional_skip = _conditional_action_precheck(state, step)
    if conditional_skip is not None:
        conditional_skip.user_confirmed = user_confirmed
        conditional_skip.user_decision = user_decision
        state.skip_current_step = True
        state.last_action_result = conditional_skip
        logger.log(state, "execute", "Conditional action skipped", step_id=step.id, result=conditional_skip.model_dump())
        return state

    focus_error = _focus_before_execute(state, step)
    if focus_error is not None:
        focus_error.user_confirmed = user_confirmed
        focus_error.user_decision = user_decision
        focus_error.manual_override = manual_coords is not None
        state.last_action_result = focus_error
        state.status = "fail"
        state.failure_category = "action_failed"
        state.error = focus_error.error_message or focus_error.message
        logger.log(state, "execute", "Action blocked because refocus failed", step_id=step.id, result=focus_error.model_dump())
        return state

    result = ActionExecutor(dry_run=state.dry_run).execute(step, state.last_located_target)
    if state.dry_run and step.action == "focus_window":
        step.metadata["dry_run_simulated_focus"] = True
    result.user_confirmed = user_confirmed
    result.user_decision = user_decision
    result.manual_override = manual_coords is not None
    if manual_coords is not None:
        result.coordinates = manual_coords
    state.last_action_result = result
    logger.log(state, "execute", "Action executed", step_id=step.id, result=result.model_dump())
    if not result.success:
        state.status = "fail"
        state.failure_category = "action_failed"
        state.error = result.error_message or result.message
    return state
