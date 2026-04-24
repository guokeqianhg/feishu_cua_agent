from __future__ import annotations

from agent.state import AgentState
from storage.run_logger import RunLogger


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
    logger.log(state, "recover", "Retry scheduled", step_id=step.id, attempt=state.current_attempt)
    return state
