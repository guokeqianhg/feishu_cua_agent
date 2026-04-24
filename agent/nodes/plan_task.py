from __future__ import annotations

from agent.state import AgentState
from storage.run_logger import RunLogger
from tools.vision.vlm_client import build_vlm_client


logger = RunLogger()
vlm = build_vlm_client()


def plan_task_node(state: AgentState) -> AgentState:
    plan = vlm.create_plan(state.test_case, state.initial_observation)
    state.plan = plan
    logger.log(
        state,
        "plan_task",
        "Plan generated",
        product=plan.product,
        steps=len(plan.steps),
        goal=plan.goal,
    )
    if not plan.steps:
        state.status = "fail"
        state.failure_category = "planning_failed"
        state.error = "Planner returned no executable steps."
    return state
