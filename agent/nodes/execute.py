from __future__ import annotations

from pathlib import Path

from agent.state import AgentState
from app.config import settings
from core.schemas import ActionResult, LocatedTarget, PlanStep
from storage.run_logger import RunLogger
from tools.desktop.executor import ActionExecutor
from tools.desktop.window_manager import WindowManager


logger = RunLogger()
window = WindowManager()


def _abort_requested() -> bool:
    return Path(settings.abort_file).exists()


def _is_lark_title(title: str) -> bool:
    raw = (title or "").lower()
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
    return any(keyword.lower() in raw for keyword in keywords)


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
            f"- will_refocus_before_execute: {_needs_focus(step, state.dry_run)}",
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
    if not step.metadata.get("requires_send_guard") and not step.metadata.get("dangerous_send"):
        return None
    target = str(step.metadata.get("target") or "")
    allowed_target = settings.allowed_im_target.strip()
    reasons: list[str] = []
    if not settings.allow_send_message:
        reasons.append("CUA_LARK_ALLOW_SEND_MESSAGE is not true")
    if allowed_target and target and target != allowed_target:
        reasons.append(f"case target {target!r} does not match CUA_LARK_ALLOWED_IM_TARGET")
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


def _conditional_action_precheck(state: AgentState, step: PlanStep) -> ActionResult | None:
    if step.action not in {"conditional_click", "conditional_hotkey"}:
        return None
    target = state.last_located_target
    if target is not None and target.confidence > 0 and not target.warnings:
        return None
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
    focused = window.focus_window_by_keywords(keywords) if keywords else window.focus_lark()
    active_title = window.get_active_window_title()
    logger.log(
        state,
        "execute",
        "Foreground window checked before action",
        step_id=step.id,
        focused_lark=focused,
        foreground_window_keywords=keywords,
        active_window_title=active_title,
    )
    if focused or (_title_matches_keywords(active_title, keywords) if keywords else _is_lark_title(active_title)):
        return None

    message = (
        "Refocus target window before action failed. "
        f"Active window is {active_title!r}. Action was blocked to avoid operating the wrong window."
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
