from __future__ import annotations

import time

from agent.state import AgentState
from core.schemas import StepRunRecord
from storage.run_logger import RunLogger
from tools.vision.vlm_client import build_vlm_client


logger = RunLogger()
vlm = build_vlm_client()


def verify_step_node(state: AgentState) -> AgentState:
    step = state.current_step()
    if step is None:
        state.status = "fail"
        state.failure_category = "planning_failed"
        state.error = "No current step available."
        return state

    started_at = state.current_step_started_at or time.time()
    if state.last_action_result and not state.last_action_result.success:
        verification = None
        status = "fail"
        error = state.last_action_result.error_message or state.last_action_result.message
    else:
        verification = vlm.verify_step(step, state.before_observation, state.after_observation)
        state.last_verification = verification
        status = "pass" if verification.success else "fail"
        error = None if verification.success else verification.reason

    ended_at = time.time()
    record = StepRunRecord(
        step_id=step.id,
        step_index=state.current_step_idx + 1,
        attempt=state.current_attempt,
        action=step.action,
        target_description=step.target_description,
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=ended_at - started_at,
        located_target=state.last_located_target,
        action_result=state.last_action_result,
        verification=verification,
        before_screenshot=state.before_observation.screenshot_path if state.before_observation else None,
        after_screenshot=state.after_observation.screenshot_path if state.after_observation else None,
        error_message=error,
    )
    state.step_records.append(record)
    if status == "pass":
        state.current_step_idx += 1
        state.current_attempt = 1
        state.last_located_target = None
        state.last_action_result = None
        state.last_verification = None
    logger.log(state, "verify", "Step verified", step_id=step.id, status=status, attempt=state.current_attempt)
    return state


def final_verify_node(state: AgentState) -> AgentState:
    if state.plan is None:
        state.status = "fail"
        state.failure_category = "planning_failed"
        state.error = "No plan available for final verification."
        return state
    verification = vlm.verify_case(state.test_case, state.plan, state.final_observation)
    state.final_verification = verification
    if verification.success:
        state.status = "pass"
        state.failure_category = "none"
    else:
        state.status = "fail"
        state.failure_category = verification.failure_category or "verification_failed"
        state.error = verification.reason
    logger.log(state, "final_verify", "Final verification completed", verification=verification.model_dump())
    return state
