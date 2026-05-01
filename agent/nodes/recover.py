from __future__ import annotations

from agent.state import AgentState
from storage.run_logger import RunLogger
from tools.vision.calendar_error_library import analyze_calendar_screen
from tools.vision.docs_error_library import analyze_docs_screen
from tools.vision.im_error_library import analyze_im_screen
from tools.vision.vc_error_library import analyze_vc_screen


logger = RunLogger()


def recover_node(state: AgentState) -> AgentState:
    step = state.current_step()
    if step is None:
        state.status = "fail"
        state.failure_category = "planning_failed"
        state.error = "Cannot recover because there is no current step."
        return state

    state.retry_count += 1
    state.current_attempt += 1
    state.status = "running"
    state.error = None
    _apply_im_error_recovery(state)
    _apply_docs_error_recovery(state)
    _apply_calendar_error_recovery(state)
    _apply_vc_error_recovery(state)
    logger.log(state, "recover", "Retry scheduled", step_id=step.id, attempt=state.current_attempt)
    return state


def _apply_im_error_recovery(state: AgentState) -> None:
    step = state.current_step()
    if step is None or state.plan is None:
        return
    recover_to = str(step.metadata.get("recover_to_step_id") or "").strip()
    target = str(step.metadata.get("target") or "").strip()
    if not recover_to or not target:
        return
    route_key = f"{step.id}->{recover_to}:{target}"
    route_count = sum(1 for warning in state.warnings if route_key in warning)
    if route_count >= 1:
        return
    analysis = analyze_im_screen(state.after_observation, target)
    if analysis is None:
        return
    if analysis.is_target_chat:
        return
    for index, candidate in enumerate(state.plan.steps):
        if candidate.id == recover_to:
            state.current_step_idx = index
            state.current_attempt = 1
            state.last_located_target = None
            state.last_action_result = None
            state.last_verification = None
            state.skip_current_step = False
            warning = (
                f"IM recovery {route_key} routed from step {step.id} back to {recover_to}: "
                f"target_visible={analysis.target_visible}, wrong_state={analysis.wrong_state}."
            )
            if warning not in state.warnings:
                state.warnings.append(warning)
            logger.log(
                state,
                "recover",
                "IM error-state recovery routed to an earlier search step",
                from_step=step.id,
                to_step=recover_to,
                target=target,
                target_visible=analysis.target_visible,
                wrong_state=analysis.wrong_state,
            )
            return


def _apply_docs_error_recovery(state: AgentState) -> None:
    step = state.current_step()
    if step is None or state.plan is None:
        return
    analysis = analyze_docs_screen(
        state.after_observation,
        expected_recipient=str(step.metadata.get("share_recipient") or ""),
        expected_title=str(step.metadata.get("doc_title") or ""),
        expected_body=str(step.metadata.get("doc_body") or ""),
    )
    if analysis is None or analysis.wrong_state is None:
        return

    recover_to = _docs_recover_step_id(step.id, analysis.wrong_state)
    if not recover_to:
        return

    route_key = f"{step.id}->{recover_to}:{analysis.wrong_state}"
    route_count = sum(1 for warning in state.warnings if route_key in warning)
    if route_count >= 1:
        return

    for index, candidate in enumerate(state.plan.steps):
        if candidate.id != recover_to:
            continue
        state.current_step_idx = index
        state.current_attempt = 1
        state.last_located_target = None
        state.last_action_result = None
        state.last_verification = None
        state.skip_current_step = False
        warning = (
            f"Docs recovery {route_key} routed from step {step.id} back to {recover_to}: "
            f"wrong_state={analysis.wrong_state}."
        )
        if warning not in state.warnings:
            state.warnings.append(warning)
        logger.log(
            state,
            "recover",
            "Docs error-state recovery routed to an earlier editor step",
            from_step=step.id,
            to_step=recover_to,
            wrong_state=analysis.wrong_state,
        )
        return


def _docs_recover_step_id(step_id: str, wrong_state: str) -> str | None:
    if wrong_state in {"title_not_entered", "title_entered_in_body"}:
        return "type_doc_title"
    if wrong_state == "body_not_entered":
        if step_id == "type_doc_body":
            return "type_doc_body"
        return "move_to_doc_body"
    return None


def _apply_calendar_error_recovery(state: AgentState) -> None:
    step = state.current_step()
    if step is None or state.plan is None:
        return
    analysis = analyze_calendar_screen(
        state.after_observation,
        expected_title=str(step.metadata.get("event_title") or ""),
        expect_create_editor=bool(
            step.metadata.get("requires_calendar_create_guard")
            or step.id in {"click_create_event", "wait_event_editor", "type_event_title"}
        ),
    )
    if analysis is None or analysis.wrong_state is None:
        return

    recover_to = _calendar_recover_step_id(step.id, analysis.wrong_state)
    if not recover_to:
        return

    route_key = f"{step.id}->{recover_to}:{analysis.wrong_state}"
    route_count = sum(1 for warning in state.warnings if route_key in warning)
    if route_count >= 1:
        return

    for index, candidate in enumerate(state.plan.steps):
        if candidate.id != recover_to:
            continue
        state.current_step_idx = index
        state.current_attempt = 1
        state.last_located_target = None
        state.last_action_result = None
        state.last_verification = None
        state.skip_current_step = False
        warning = (
            f"Calendar recovery {route_key} routed from step {step.id} back to {recover_to}: "
            f"wrong_state={analysis.wrong_state}."
        )
        if warning not in state.warnings:
            state.warnings.append(warning)
        logger.log(
            state,
            "recover",
            "Calendar error-state recovery routed to an earlier step",
            from_step=step.id,
            to_step=recover_to,
            wrong_state=analysis.wrong_state,
        )
        return


def _calendar_recover_step_id(step_id: str, wrong_state: str) -> str | None:
    if wrong_state == "foreground_window_wrong":
        return "focus_lark"
    if wrong_state in {"event_detail_card_open", "add_participant_dialog_open", "create_confirmation_open"}:
        return "dismiss_calendar_blockers"
    if wrong_state == "create_editor_loading":
        return step_id if step_id == "wait_event_editor" else None
    if wrong_state == "create_editor_not_open":
        return "click_create_event"
    if wrong_state == "title_not_entered":
        return "type_event_title"
    if wrong_state == "not_calendar_screen":
        return "open_calendar"
    return None


def _apply_vc_error_recovery(state: AgentState) -> None:
    step = state.current_step()
    if step is None or state.plan is None:
        return
    template = str(state.test_case.metadata.get("plan_template") or "")
    if not template.startswith("vc_"):
        return
    analysis = analyze_vc_screen(state.after_observation)
    if analysis is None:
        return
    wrong_state = analysis.wrong_state
    if wrong_state is None and step.id == "type_vc_meeting_id":
        wrong_state = "meeting_id_not_entered"
    if wrong_state is None:
        return
    recover_to = _vc_recover_step_id(step.id, wrong_state)
    if not recover_to:
        return
    route_key = f"{step.id}->{recover_to}:{wrong_state}"
    route_count = sum(1 for warning in state.warnings if route_key in warning)
    if route_count >= 1:
        return
    for index, candidate in enumerate(state.plan.steps):
        if candidate.id != recover_to:
            continue
        state.current_step_idx = index
        state.current_attempt = 1
        state.last_located_target = None
        state.last_action_result = None
        state.last_verification = None
        state.skip_current_step = False
        warning = (
            f"VC recovery {route_key} routed from step {step.id} back to {recover_to}: "
            f"wrong_state={wrong_state}."
        )
        if warning not in state.warnings:
            state.warnings.append(warning)
        logger.log(
            state,
            "recover",
            "VC error-state recovery routed to an earlier step",
            from_step=step.id,
            to_step=recover_to,
            wrong_state=wrong_state,
        )
        return


def _vc_recover_step_id(step_id: str, wrong_state: str) -> str | None:
    if wrong_state == "not_vc_screen":
        return "open_vc"
    if wrong_state == "permission_prompt_open":
        return "allow_vc_permission"
    if wrong_state == "meeting_id_not_entered":
        return "type_vc_meeting_id"
    if wrong_state == "prejoin_not_confirmed":
        if step_id.startswith("confirm_"):
            return step_id
        return "confirm_join_meeting"
    if wrong_state == "meeting_not_joined":
        if step_id in {"confirm_start_meeting", "confirm_join_meeting"}:
            return step_id
        return "click_vc_start_meeting"
    if wrong_state == "device_controls_missing":
        return "verify_vc_started" if step_id != "verify_vc_started" else None
    return None
