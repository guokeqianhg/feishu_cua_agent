from __future__ import annotations

from langgraph.graph import END, StateGraph

from agent.nodes.capture_screen import capture_after_node, capture_before_node, capture_initial_node
from agent.nodes.decide import locate_node
from agent.nodes.execute import execute_node
from agent.nodes.perceive import observe_after_node, observe_before_node, observe_initial_node
from agent.nodes.plan_task import plan_task_node
from agent.nodes.recover import recover_node
from agent.nodes.report import report_node
from agent.nodes.verify import final_verify_node, verify_step_node
from agent.state import AgentState


def route_after_plan(state: AgentState) -> str:
    if state.status in ("fail", "error"):
        return "report"
    return "capture_before"


def route_after_locate(state: AgentState) -> str:
    if state.status in ("fail", "error"):
        return "recover_or_report"
    return "execute"


def route_after_execute(state: AgentState) -> str:
    if state.status in ("fail", "error"):
        return "capture_after"
    return "capture_after"


def route_after_verify(state: AgentState) -> str:
    last_record = state.step_records[-1] if state.step_records else None
    if last_record and last_record.status == "pass":
        if state.plan and state.current_step_idx >= len(state.plan.steps):
            return "final_verify"
        return "capture_before"

    step = state.current_step()
    if step is None:
        return "final_verify"

    retry_limit = max(1, step.retry_limit)
    if state.current_attempt < retry_limit:
        return "recover"

    state.status = "fail"
    state.failure_category = "verification_failed"
    if state.last_verification:
        state.error = state.last_verification.reason
    return "report"


def route_after_recover_or_report(state: AgentState) -> str:
    step = state.current_step()
    if step and state.current_attempt < max(1, step.retry_limit):
        return "recover"
    return "report"


def route_after_recover(state: AgentState) -> str:
    if state.status in ("fail", "error"):
        return "report"
    return "capture_before"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("capture_initial", capture_initial_node)
    graph.add_node("observe_initial", observe_initial_node)
    graph.add_node("plan_task", plan_task_node)
    graph.add_node("capture_before", capture_before_node)
    graph.add_node("observe_before", observe_before_node)
    graph.add_node("locate", locate_node)
    graph.add_node("execute", execute_node)
    graph.add_node("capture_after", capture_after_node)
    graph.add_node("observe_after", observe_after_node)
    graph.add_node("verify_step", verify_step_node)
    graph.add_node("recover", recover_node)
    graph.add_node("final_verify", final_verify_node)
    graph.add_node("report", report_node)

    graph.set_entry_point("capture_initial")
    graph.add_edge("capture_initial", "observe_initial")
    graph.add_edge("observe_initial", "plan_task")
    graph.add_conditional_edges("plan_task", route_after_plan, {"capture_before": "capture_before", "report": "report"})
    graph.add_edge("capture_before", "observe_before")
    graph.add_edge("observe_before", "locate")
    graph.add_conditional_edges(
        "locate",
        route_after_locate,
        {"execute": "execute", "recover_or_report": "recover_or_report"},
    )
    graph.add_node("recover_or_report", lambda state: state)
    graph.add_conditional_edges(
        "recover_or_report",
        route_after_recover_or_report,
        {"recover": "recover", "report": "report"},
    )
    graph.add_conditional_edges("execute", route_after_execute, {"capture_after": "capture_after"})
    graph.add_edge("capture_after", "observe_after")
    graph.add_edge("observe_after", "verify_step")
    graph.add_conditional_edges(
        "verify_step",
        route_after_verify,
        {
            "capture_before": "capture_before",
            "recover": "recover",
            "final_verify": "final_verify",
            "report": "report",
        },
    )
    graph.add_conditional_edges("recover", route_after_recover, {"capture_before": "capture_before", "report": "report"})
    graph.add_edge("final_verify", "report")
    graph.add_edge("report", END)
    return graph.compile()
