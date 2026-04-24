from __future__ import annotations

from pathlib import Path

from agent.state import AgentState
from app.config import settings
from core.schemas import ActionResult
from storage.run_logger import RunLogger
from tools.desktop.executor import ActionExecutor


logger = RunLogger()


def _abort_requested() -> bool:
    return Path(settings.abort_file).exists()


def _preview_text(state: AgentState) -> str:
    step = state.current_step()
    target = state.last_located_target
    before = state.before_observation.screenshot_path if state.before_observation else None
    if step is None:
        return "No current step."
    return "\n".join(
        [
            "",
            "即将执行步骤",
            f"- step: {step.id}",
            f"- action: {step.action}",
            f"- target: {step.target_description or ''}",
            f"- input_text: {step.input_text or ''}",
            f"- hotkeys: {'+'.join(step.hotkeys) if step.hotkeys else ''}",
            f"- candidate_center: {target.center if target else None}",
            f"- candidate_bbox: {target.bbox.model_dump() if target and target.bbox else None}",
            f"- before_screenshot: {before}",
            "请选择: y=继续, n=跳过, q=终止",
        ]
    )


def _ask_user(state: AgentState) -> str:
    print(_preview_text(state), flush=True)
    while True:
        answer = input("> ").strip().lower()
        if answer in ("y", "yes"):
            return "yes"
        if answer in ("n", "no", "skip"):
            return "skip"
        if answer in ("q", "quit", "abort"):
            return "abort"
        print("请输入 y / n / q。", flush=True)


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
    if state.step_by_step:
        user_decision = _ask_user(state)
        user_confirmed = user_decision == "yes"
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

    result = ActionExecutor(dry_run=state.dry_run).execute(step, state.last_located_target)
    result.user_confirmed = user_confirmed
    result.user_decision = user_decision
    state.last_action_result = result
    logger.log(state, "execute", "Action executed", step_id=step.id, result=result.model_dump())
    if not result.success:
        state.status = "fail"
        state.failure_category = "action_failed"
        state.error = result.error_message or result.message
    return state
