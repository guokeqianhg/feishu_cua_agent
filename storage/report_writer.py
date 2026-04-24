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
            "## Runtime Mode",
        ]
        if report.runtime:
            lines.extend(
                [
                    f"- Model Provider: {report.runtime.model_provider}",
                    f"- Effective Model Provider: {report.runtime.effective_model_provider}",
                    f"- Dry Run: {report.runtime.dry_run}",
                    f"- Placeholder Screenshot Enabled: {report.runtime.placeholder_screenshot}",
                    f"- Real Desktop Execution: {report.runtime.real_desktop_execution}",
                    f"- Mock Verification: {report.runtime.mock_verification}",
                    f"- Step By Step: {report.runtime.step_by_step}",
                    f"- Abort File: {report.runtime.abort_file}",
                    f"- Allow Unhealthy Screenshot: {report.runtime.allow_unhealthy_screenshot}",
                    f"- Monitor Index: {report.runtime.monitor_index}",
                ]
            )
        else:
            lines.append("- Runtime metadata is not available.")

        lines.extend(
            [
                "",
                "## Warnings",
            ]
        )
        if report.warnings:
            lines.extend(f"- {warning}" for warning in report.warnings)
        else:
            lines.append("- No warnings.")

        if report.screenshot_diagnostics:
            lines.extend(
                [
                    "",
                    "## Screenshot Diagnostics",
                    f"- Healthy: {report.screenshot_diagnostics.healthy}",
                    f"- Artifacts: {report.screenshot_diagnostics.artifacts_dir}",
                    f"- Monitors: {len(report.screenshot_diagnostics.monitors)}",
                ]
            )
            if report.screenshot_diagnostics.warnings:
                lines.extend(f"- {warning}" for warning in report.screenshot_diagnostics.warnings)
            if report.screenshot_diagnostics.possible_causes:
                lines.append("- Possible causes: " + "; ".join(report.screenshot_diagnostics.possible_causes))

        lines.extend(
            [
                "",
            "## Metrics",
            f"- Total Steps: {report.metrics.total_steps}",
            f"- Passed Steps: {report.metrics.passed_steps}",
            f"- Failed Steps: {report.metrics.failed_steps}",
            f"- Skipped Steps: {report.metrics.skipped_steps}",
            f"- Retry Count: {report.metrics.retry_count}",
            f"- Replan Count: {report.metrics.replan_count}",
            f"- Success Rate: {report.metrics.success_rate:.2%}",
            f"- Evidence Complete: {report.metrics.evidence_complete}",
            "",
            "## Step Details",
            "| Step | Action | Target | Coords | Input/Keys | Confirm | Dry Run | Status | Duration | Screenshot | Reason |",
            "|---|---|---|---|---|---|---|---|---:|---|---|",
            ]
        )
        for record in report.step_records:
            screenshot = record.after_screenshot or record.before_screenshot or ""
            reason = ""
            if record.verification:
                reason = record.verification.reason
            elif record.error_message:
                reason = record.error_message
            coords = record.action_result.coordinates if record.action_result else None
            input_or_keys = ""
            if record.action_result:
                if record.action_result.input_text:
                    input_or_keys = record.action_result.input_text
                elif record.action_result.hotkeys:
                    input_or_keys = "+".join(record.action_result.hotkeys)
                elif record.action_result.scroll_amount is not None:
                    input_or_keys = str(record.action_result.scroll_amount)
            lines.append(
                f"| {record.step_id} | {record.action} | {record.target_description or ''} | "
                f"{coords or ''} | {input_or_keys} | {record.user_decision or ''} | "
                f"{record.action_result.dry_run if record.action_result else ''} | "
                f"{record.status} | {record.duration_seconds:.2f} | "
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
