from __future__ import annotations

import time

from agent.state import AgentState
from storage.run_logger import RunLogger
from tools.vision.vlm_client import build_vlm_client


logger = RunLogger()
vlm = build_vlm_client()


def locate_node(state: AgentState) -> AgentState:
    step = state.current_step()
    if step is None:
        state.status = "fail"
        state.failure_category = "planning_failed"
        state.error = "No current step available."
        return state
    if state.before_observation is None:
        state.status = "fail"
        state.failure_category = "perception_failed"
        state.error = "No before observation available."
        return state

    state.current_step_started_at = time.time()
    located = vlm.locate_element(state.before_observation, step)
    state.last_located_target = located
    logger.log(state, "locate", "Target located", step_id=step.id, located=located.model_dump())
    if step.action in ("click", "double_click", "right_click", "drag") and located.confidence <= 0:
        state.status = "fail"
        state.failure_category = "location_failed"
        state.error = f"Could not locate target for step {step.id}: {step.target_description}"
    return state
