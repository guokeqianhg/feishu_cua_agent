from __future__ import annotations

from agent.state import AgentState
from intent.parser import enrich_case_with_intent
from storage.run_logger import RunLogger


logger = RunLogger()


def parse_task_node(state: AgentState) -> AgentState:
    original_metadata = dict(state.test_case.metadata)
    state.test_case = enrich_case_with_intent(state.test_case)
    if state.test_case.metadata != original_metadata:
        logger.log(
            state,
            "parse_task",
            "Natural language intent parsed",
            parsed_intent=state.test_case.metadata.get("parsed_intent"),
            plan_template=state.test_case.metadata.get("plan_template"),
            target=state.test_case.metadata.get("target"),
            safety_guard_required=state.test_case.metadata.get("safety_guard_required"),
        )
    return state
