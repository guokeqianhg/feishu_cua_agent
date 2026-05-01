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
    if template in {"docs_create_doc_guarded", "docs_rich_edit_guarded"}:
        if settings.allow_doc_create:
            return None
        return (
            "Guarded Docs create task was blocked before any desktop action: "
            "CUA_LARK_ALLOW_DOC_CREATE is not true. Set CUA_LARK_ALLOW_DOC_CREATE=true only for harmless test documents."
        )
    if template == "docs_share_doc_guarded":
        recipient_reason = _doc_share_recipient_block_reason(state)
        if settings.allow_doc_create and settings.allow_doc_share and not recipient_reason:
            return None
        reasons = [] if not recipient_reason else [recipient_reason]
        if not settings.allow_doc_create:
            reasons.insert(0, "CUA_LARK_ALLOW_DOC_CREATE is not true")
        if not settings.allow_doc_share:
            reasons.insert(0, "CUA_LARK_ALLOW_DOC_SHARE is not true")
        return "Guarded Docs share task was blocked before any desktop action: " + "; ".join(reasons)
    if template == "calendar_create_event_guarded":
        if settings.allow_calendar_create:
            return None
        return (
            "Guarded Calendar create task was blocked before any desktop action: "
            "CUA_LARK_ALLOW_CALENDAR_CREATE is not true. Set CUA_LARK_ALLOW_CALENDAR_CREATE=true only for harmless test calendars."
        )
    if template == "calendar_invite_attendee_guarded":
        if settings.allow_calendar_create and settings.allow_calendar_invite:
            return None
        reasons = []
        if not settings.allow_calendar_create:
            reasons.append("CUA_LARK_ALLOW_CALENDAR_CREATE is not true")
        if not settings.allow_calendar_invite:
            reasons.append("CUA_LARK_ALLOW_CALENDAR_INVITE is not true")
        return "Guarded Calendar attendee-invite task was blocked before any desktop action: " + "; ".join(reasons)
    if template == "calendar_modify_event_time_guarded":
        if settings.allow_calendar_create and settings.allow_calendar_modify:
            return None
        reasons = []
        if not settings.allow_calendar_create:
            reasons.append("CUA_LARK_ALLOW_CALENDAR_CREATE is not true")
        if not settings.allow_calendar_modify:
            reasons.append("CUA_LARK_ALLOW_CALENDAR_MODIFY is not true")
        return "Guarded Calendar modify-time task was blocked before any desktop action: " + "; ".join(reasons)
    if template == "calendar_view_busy_free_guarded":
        return None
    if template == "vc_start_meeting_guarded":
        reasons = []
        if not settings.allow_vc_start:
            reasons.append("CUA_LARK_ALLOW_VC_START is not true")
        if _vc_device_state_requested(state) and not settings.allow_vc_device_toggle:
            reasons.append("CUA_LARK_ALLOW_VC_DEVICE_TOGGLE is not true")
        if not reasons:
            return None
        return "Guarded VC start task was blocked before any desktop action: " + "; ".join(reasons)
    if template == "vc_join_meeting_guarded":
        reasons = []
        if not settings.allow_vc_join:
            reasons.append("CUA_LARK_ALLOW_VC_JOIN is not true")
        if _vc_device_state_requested(state) and not settings.allow_vc_device_toggle:
            reasons.append("CUA_LARK_ALLOW_VC_DEVICE_TOGGLE is not true")
        if not reasons:
            return None
        return "Guarded VC join task was blocked before any desktop action: " + "; ".join(reasons)
    if template == "vc_toggle_devices_guarded":
        if settings.allow_vc_device_toggle:
            return None
        return (
            "Guarded VC device-toggle task was blocked before any desktop action: "
            "CUA_LARK_ALLOW_VC_DEVICE_TOGGLE is not true"
        )
    if template == "im_search_messages_guarded":
        return None
    if template == "im_send_image_guarded":
        target_reason = _target_block_reason(state)
        if settings.allow_send_image and not target_reason:
            return None
        reasons = [] if not target_reason else [target_reason]
        if not settings.allow_send_image:
            reasons.insert(0, "CUA_LARK_ALLOW_SEND_IMAGE is not true")
        return "Guarded IM image task was blocked before any desktop action: " + "; ".join(reasons)
    if template == "im_create_group_guarded":
        member_reason = _group_member_block_reason(state)
        if settings.allow_create_group and not member_reason:
            return None
        reasons = [] if not member_reason else [member_reason]
        if not settings.allow_create_group:
            reasons.insert(0, "CUA_LARK_ALLOW_CREATE_GROUP is not true")
        return "Guarded IM group-create task was blocked before any desktop action: " + "; ".join(reasons)
    if template == "im_emoji_reaction_guarded":
        target_reason = _target_block_reason(state)
        if settings.allow_emoji_reaction and not target_reason:
            return None
        reasons = [] if not target_reason else [target_reason]
        if not settings.allow_emoji_reaction:
            reasons.insert(0, "CUA_LARK_ALLOW_EMOJI_REACTION is not true")
        return "Guarded IM emoji task was blocked before any desktop action: " + "; ".join(reasons)
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


def _target_block_reason(state: AgentState) -> str | None:
    target = str(state.test_case.metadata.get("target") or "")
    allowed_target = settings.allowed_im_target.strip()
    if allowed_target and target and target != allowed_target:
        return f"parsed target {target!r} does not match CUA_LARK_ALLOWED_IM_TARGET"
    return None


def _group_member_block_reason(state: AgentState) -> str | None:
    allowed = settings.allowed_group_member.strip()
    if not allowed:
        return None
    raw = state.test_case.metadata.get("group_members") or []
    members = [raw] if isinstance(raw, str) else list(raw)
    blocked = [str(item) for item in members if str(item) and str(item) != allowed]
    if blocked:
        return f"group members {blocked!r} do not match CUA_LARK_ALLOWED_GROUP_MEMBER"
    return None


def _doc_share_recipient_block_reason(state: AgentState) -> str | None:
    allowed = settings.allowed_doc_share_recipient.strip()
    recipient = str(state.test_case.metadata.get("share_recipient") or "")
    if allowed and recipient and recipient != allowed:
        return f"share recipient {recipient!r} does not match CUA_LARK_ALLOWED_DOC_SHARE_RECIPIENT"
    return None


def _vc_device_state_requested(state: AgentState) -> bool:
    return (
        state.test_case.metadata.get("desired_camera_on") is not None
        or state.test_case.metadata.get("desired_mic_on") is not None
    )
