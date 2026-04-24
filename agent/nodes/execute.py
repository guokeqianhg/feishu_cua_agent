from __future__ import annotations

from agent.state import AgentState
from storage.run_logger import RunLogger
from tools.desktop.executor import ActionExecutor


logger = RunLogger()


def execute_node(state: AgentState) -> AgentState:
    step = state.current_step()
    if step is None:
        state.status = "fail"
        state.failure_category = "planning_failed"
        state.error = "No current step available."
        return state
    result = ActionExecutor(dry_run=state.dry_run).execute(step, state.last_located_target)
    state.last_action_result = result
    logger.log(state, "execute", "Action executed", step_id=step.id, result=result.model_dump())
    if not result.success:
        state.status = "fail"
        state.failure_category = "action_failed"
        state.error = result.error_message or result.message
    return state
