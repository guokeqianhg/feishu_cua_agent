from __future__ import annotations

import time

from agent.state import AgentState
from core.schemas import PlanStep, StepRunRecord, StepVerification
from storage.run_logger import RunLogger
from tools.vision.smoke import is_safe_smoke_case, verify_smoke_case, verify_smoke_step
from tools.vision.vlm_client import build_vlm_client


logger = RunLogger()
vlm = build_vlm_client()


def _is_real_execution(state: AgentState) -> bool:
    return bool(state.runtime and state.runtime.real_desktop_execution and state.runtime.effective_model_provider != "mock")


def _raw_provider(verification: StepVerification | None) -> str:
    if verification is None:
        return ""
    return str(verification.raw_model_output.get("provider", ""))


def _contains_text(observation_text: str, expected: str) -> bool:
    return expected.lower() in observation_text.lower()


def _observation_text(state: AgentState) -> str:
    if state.after_observation is None:
        return ""
    return state.after_observation.model_dump_json()


def _enforce_real_verification(state: AgentState, step: PlanStep, verification: StepVerification) -> StepVerification:
    if not _is_real_execution(state):
        return verification

    provider = _raw_provider(verification)
    after_provider = ""
    if state.after_observation is not None:
        after_provider = str(state.after_observation.raw_model_output.get("provider", ""))
    if after_provider == "mock":
        warning = f"Real execution perception warning: step {step.id} used mock screen observation."
        if warning not in state.warnings:
            state.warnings.append(warning)
        verification.success = False
        verification.confidence = 0.0
        verification.reason = warning
        verification.failure_category = "perception_failed"
        return verification

    if provider in ("mock", "vlm_error"):
        warning = f"Real execution verification warning: step {step.id} used {provider} result instead of real VLM verification."
        if warning not in state.warnings:
            state.warnings.append(warning)
        verification.success = False
        verification.confidence = 0.0
        verification.reason = warning
        verification.failure_category = "verification_failed"
        if step.expected_state:
            verification.failed_criteria.append(step.expected_state)
        return verification

    if step.id == "type_safe_query" and step.input_text:
        if not _contains_text(_observation_text(state), step.input_text):
            verification.success = False
            verification.confidence = min(verification.confidence, 0.2)
            verification.reason = (
                f"Search text {step.input_text!r} was not found in the after screenshot observation; "
                "do not treat this smoke step as verified."
            )
            verification.failure_category = "verification_failed"
            verification.failed_criteria.append(f"after observation contains {step.input_text!r}")
    return verification


def verify_step_node(state: AgentState) -> AgentState:
    step = state.current_step()
    if step is None:
        state.status = "fail"
        state.failure_category = "planning_failed"
        state.error = "No current step available."
        return state

    started_at = state.current_step_started_at or time.time()
    if state.status == "aborted":
        verification = None
        status = "aborted"
        error = state.error or f"Aborted at step {step.id}"
    elif state.skip_current_step or (state.last_action_result and state.last_action_result.skipped):
        verification = None
        status = "skipped"
        error = state.last_action_result.message if state.last_action_result else "Step skipped."
    elif state.last_action_result and not state.last_action_result.success:
        verification = None
        status = "fail"
        error = state.last_action_result.error_message or state.last_action_result.message
    else:
        if is_safe_smoke_case(state.test_case):
            verification = verify_smoke_step(step, state.before_observation, state.after_observation)
        else:
            verification = vlm.verify_step(step, state.before_observation, state.after_observation)
            verification = _enforce_real_verification(state, step, verification)
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
        before_window_title=state.before_observation.window_title if state.before_observation else None,
        after_window_title=state.after_observation.window_title if state.after_observation else None,
        error_message=error,
        user_confirmed=state.last_action_result.user_confirmed if state.last_action_result else None,
        user_decision=state.last_action_result.user_decision if state.last_action_result else None,
    )
    state.step_records.append(record)
    if status in ("pass", "skipped"):
        state.current_step_idx += 1
        state.current_attempt = 1
        state.last_located_target = None
        state.last_action_result = None
        state.last_verification = None
        state.skip_current_step = False
    elif status in ("fail", "error"):
        retry_limit = max(1, step.retry_limit)
        if state.current_attempt >= retry_limit:
            state.status = "fail"
            state.failure_category = verification.failure_category if verification else "verification_failed"
            state.error = error
    logger.log(state, "verify", "Step verified", step_id=step.id, status=status, attempt=state.current_attempt)
    return state


def final_verify_node(state: AgentState) -> AgentState:
    if state.status == "aborted":
        return state
    if state.plan is None:
        state.status = "fail"
        state.failure_category = "planning_failed"
        state.error = "No plan available for final verification."
        return state
    if is_safe_smoke_case(state.test_case):
        verification = verify_smoke_case(state.test_case, state.final_observation)
    else:
        verification = vlm.verify_case(state.test_case, state.plan, state.final_observation)
    if _is_real_execution(state) and _raw_provider(verification) in ("mock", "vlm_error"):
        warning = f"Real execution final verification warning: used {_raw_provider(verification)} result instead of real VLM verification."
        if warning not in state.warnings:
            state.warnings.append(warning)
        verification.success = False
        verification.confidence = 0.0
        verification.reason = warning
        verification.failure_category = "verification_failed"
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
