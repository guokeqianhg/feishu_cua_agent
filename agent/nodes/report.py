from __future__ import annotations

import time

from agent.state import AgentState
from core.runtime import simulation_warning
from core.schemas import RunMetrics, TestRunReport
from storage.report_writer import ReportWriter
from storage.run_logger import RunLogger


logger = RunLogger()
writer = ReportWriter()


def report_node(state: AgentState) -> AgentState:
    ended_at = time.time()
    state.ended_at = ended_at
    passed = sum(1 for item in state.step_records if item.status == "pass")
    failed = sum(1 for item in state.step_records if item.status in ("fail", "error", "aborted"))
    skipped = sum(1 for item in state.step_records if item.status == "skipped")
    total = len(state.step_records)
    evidence_complete = all(item.before_screenshot and item.after_screenshot for item in state.step_records)
    screenshot_warning = any("Screenshot warning" in item for item in state.warnings)
    if screenshot_warning:
        evidence_complete = False
    product = state.plan.product if state.plan else state.test_case.product
    success_rate = (passed / total) if total else 0.0

    metrics = RunMetrics(
        total_steps=total,
        passed_steps=passed,
        failed_steps=failed,
        skipped_steps=skipped,
        retry_count=state.retry_count,
        replan_count=state.replan_count,
        success_rate=success_rate,
        product_coverage=[product],
        evidence_complete=evidence_complete,
    )
    if state.runtime:
        warning = simulation_warning(state.runtime)
        if warning and warning not in state.warnings:
            state.warnings.append(warning)

    stopped = f" Stopped at step={state.aborted_step_id}." if state.status == "aborted" and state.aborted_step_id else ""
    summary = (
        f"Run {state.status}: {passed}/{total} steps passed, {skipped} skipped. "
        f"Product={product}. Evidence complete={evidence_complete}."
        f"{stopped}"
    )
    report = TestRunReport(
        run_id=state.run_id,
        case_id=state.test_case.id,
        case_name=state.test_case.name,
        product=product,
        instruction=state.test_case.instruction,
        parsed_intent={
            key: value
            for key, value in state.test_case.metadata.items()
            if key
            in {
                "parsed_intent",
                "intent_confidence",
                "intent_reason",
                "intent_warnings",
                "plan_template",
                "target",
                "message",
                "search_text",
                "doc_title",
                "doc_body",
                "event_title",
                "event_time",
                "attendees",
                "safety_guard_required",
            }
        },
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
        runtime=state.runtime,
        warnings=state.warnings,
        screenshot_diagnostics=state.screenshot_diagnostics,
    )
    state.run_report = report
    state.report_summary = summary
    summary_json, summary_md, steps_jsonl = writer.write(report)
    state.summary_json_path = str(summary_json)
    state.summary_md_path = str(summary_md)
    state.steps_jsonl_path = str(steps_jsonl)
    logger.log(state, "report", "Report persisted", summary_json=str(summary_json), summary_md=str(summary_md))
    return state
