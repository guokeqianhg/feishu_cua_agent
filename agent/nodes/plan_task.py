from __future__ import annotations

from agent.state import AgentState
from app.config import settings
from products.workflows import build_product_plan
from storage.run_logger import RunLogger
from tools.vision.vlm_client import build_vlm_client


logger = RunLogger()
vlm = build_vlm_client()


def plan_task_node(state: AgentState) -> AgentState:
    plan = build_product_plan(state.test_case) or vlm.create_plan(state.test_case, state.initial_observation)
    state.plan = plan
    logger.log(
        state,
        "plan_task",
        "Plan generated",
        product=plan.product,
        steps=len(plan.steps),
        goal=plan.goal,
    )
    guard_reason = _mutation_guard_block_reason(state)
    if guard_reason:
        state.status = "fail"
        state.failure_category = "permission_denied"
        state.error = guard_reason
        logger.log(state, "plan_task", "Guarded mutation blocked before desktop actions", reason=guard_reason)
        return state
    if not plan.steps:
        state.status = "fail"
        state.failure_category = "planning_failed"
        state.error = "Planner returned no executable steps."
    return state


def _mutation_guard_block_reason(state: AgentState) -> str | None:
    if not state.test_case.metadata.get("safety_guard_required"):
        return None
    if state.runtime and state.runtime.dry_run:
        return None
    template = str(state.test_case.metadata.get("plan_template") or "")
    if template == "docs_create_doc_guarded":
        if settings.allow_doc_create:
            return None
        return (
            "Guarded Docs create task was blocked before any desktop action: "
            "CUA_LARK_ALLOW_DOC_CREATE is not true. Set CUA_LARK_ALLOW_DOC_CREATE=true only for harmless test documents."
        )
    if template == "calendar_create_event_guarded":
        if settings.allow_calendar_create:
            return None
        return (
            "Guarded Calendar create task was blocked before any desktop action: "
            "CUA_LARK_ALLOW_CALENDAR_CREATE is not true. Set CUA_LARK_ALLOW_CALENDAR_CREATE=true only for harmless test calendars."
        )
    target = str(state.test_case.metadata.get("target") or "")
    allowed_target = settings.allowed_im_target.strip()
    reasons: list[str] = []
    if not settings.allow_send_message:
        reasons.append("CUA_LARK_ALLOW_SEND_MESSAGE is not true")
    if allowed_target and target and target != allowed_target:
        reasons.append(f"parsed target {target!r} does not match CUA_LARK_ALLOWED_IM_TARGET")
    if not reasons:
        return None
    return (
        "Guarded send task was blocked before any desktop action: "
        + "; ".join(reasons)
        + ". Set CUA_LARK_ALLOW_SEND_MESSAGE=true before real message sending; "
        "optionally set CUA_LARK_ALLOWED_IM_TARGET to enforce a fixed test target."
    )
