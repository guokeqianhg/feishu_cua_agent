from __future__ import annotations

import json
from pathlib import Path

from core.schemas import TestRunReport


class ReportWriter:
    def write(self, report: TestRunReport) -> tuple[Path, Path, Path]:
        run_dir = Path(report.artifacts_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        summary_json = run_dir / "summary.json"
        summary_md = run_dir / "summary.md"
        steps_jsonl = run_dir / "steps.jsonl"

        summary_json.write_text(
            json.dumps(report.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        steps_jsonl.write_text(
            "\n".join(json.dumps(item.model_dump(), ensure_ascii=False) for item in report.step_records),
            encoding="utf-8",
        )
        summary_md.write_text(self._markdown(report), encoding="utf-8")
        return summary_json, summary_md, steps_jsonl

    def _markdown(self, report: TestRunReport) -> str:
        lines = [
            "# CUA-Lark Test Report",
            "",
            "## Basic Info",
            f"- Run ID: {report.run_id}",
            f"- Case ID: {report.case_id}",
            f"- Case Name: {report.case_name}",
            f"- Product: {report.product}",
            f"- Instruction: {report.instruction}",
            f"- Status: {report.status}",
            f"- Duration Seconds: {report.duration_seconds:.2f}",
            f"- Failure Category: {report.failure_category}",
            "",
            "## Metrics",
            f"- Total Steps: {report.metrics.total_steps}",
            f"- Passed Steps: {report.metrics.passed_steps}",
            f"- Failed Steps: {report.metrics.failed_steps}",
            f"- Retry Count: {report.metrics.retry_count}",
            f"- Replan Count: {report.metrics.replan_count}",
            f"- Success Rate: {report.metrics.success_rate:.2%}",
            f"- Evidence Complete: {report.metrics.evidence_complete}",
            "",
            "## Step Details",
            "| Step | Action | Target | Attempt | Status | Duration | Screenshot | Reason |",
            "|---|---|---|---:|---|---:|---|---|",
        ]
        for record in report.step_records:
            screenshot = record.after_screenshot or record.before_screenshot or ""
            reason = ""
            if record.verification:
                reason = record.verification.reason
            elif record.error_message:
                reason = record.error_message
            lines.append(
                f"| {record.step_id} | {record.action} | {record.target_description or ''} | "
                f"{record.attempt} | {record.status} | {record.duration_seconds:.2f} | "
                f"{screenshot} | {reason} |"
            )

        lines.extend(
            [
                "",
                "## Final Verification",
                report.final_verification.reason if report.final_verification else "Not available",
                "",
                "## Failure Analysis",
                report.error_message or "No failure.",
                "",
                "## Summary",
                report.summary,
                "",
            ]
        )
        return "\n".join(lines)
