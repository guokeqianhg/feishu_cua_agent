from __future__ import annotations

import time

from agent.state import AgentState
from core.schemas import RunMetrics, TestRunReport
from storage.report_writer import ReportWriter
from storage.run_logger import RunLogger


logger = RunLogger()
writer = ReportWriter()


def report_node(state: AgentState) -> AgentState:
    ended_at = time.time()
    state.ended_at = ended_at
    passed = sum(1 for item in state.step_records if item.status == "pass")
    failed = sum(1 for item in state.step_records if item.status in ("fail", "error"))
    total = len(state.step_records)
    evidence_complete = all(item.before_screenshot and item.after_screenshot for item in state.step_records)
    product = state.plan.product if state.plan else state.test_case.product
    success_rate = (passed / total) if total else 0.0

    metrics = RunMetrics(
        total_steps=total,
        passed_steps=passed,
        failed_steps=failed,
        retry_count=state.retry_count,
        replan_count=state.replan_count,
        success_rate=success_rate,
        product_coverage=[product],
        evidence_complete=evidence_complete,
    )
    summary = (
        f"Run {state.status}: {passed}/{total} steps passed. "
        f"Product={product}. Evidence complete={evidence_complete}."
    )
    report = TestRunReport(
        run_id=state.run_id,
        case_id=state.test_case.id,
        case_name=state.test_case.name,
        product=product,
        instruction=state.test_case.instruction,
        status=state.status,
        started_at=state.started_at,
        ended_at=ended_at,
        duration_seconds=ended_at - state.started_at,
        metrics=metrics,
        step_records=state.step_records,
        artifacts_dir=state.artifacts_dir,
        summary=summary,
        failure_category=state.failure_category,
        error_message=state.error,
        final_verification=state.final_verification,
    )
    state.run_report = report
    state.report_summary = summary
    summary_json, summary_md, steps_jsonl = writer.write(report)
    state.summary_json_path = str(summary_json)
    state.summary_md_path = str(summary_md)
    state.steps_jsonl_path = str(steps_jsonl)
    logger.log(state, "report", "Report persisted", summary_json=str(summary_json), summary_md=str(summary_md))
    return state
