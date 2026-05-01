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
        ]
        if report.parsed_intent:
            lines.extend(["", "## Parsed Intent"])
            lines.extend(f"- {key}: {value}" for key, value in report.parsed_intent.items())
        lines.extend(["", "## Runtime Mode"])
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
                    f"- Auto Debug: {report.runtime.auto_debug}",
                    f"- Abort File: {report.runtime.abort_file}",
                    f"- Allow Unhealthy Screenshot: {report.runtime.allow_unhealthy_screenshot}",
                    f"- Allow Mock Real Execution: {report.runtime.allow_mock_real_execution}",
                    f"- Allow Send Message: {report.runtime.allow_send_message}",
                    f"- Allowed IM Target: {report.runtime.allowed_im_target or ''}",
                    f"- Allow Send Image: {report.runtime.allow_send_image}",
                    f"- Allow Create Group: {report.runtime.allow_create_group}",
                    f"- Allow Emoji Reaction: {report.runtime.allow_emoji_reaction}",
                    f"- Allowed Group Member: {report.runtime.allowed_group_member or ''}",
                    f"- Allow Doc Create: {report.runtime.allow_doc_create}",
                    f"- Allow Calendar Create: {report.runtime.allow_calendar_create}",
                    f"- Allow Calendar Invite: {report.runtime.allow_calendar_invite}",
                    f"- Allow VC Start: {report.runtime.allow_vc_start}",
                    f"- Allow VC Join: {report.runtime.allow_vc_join}",
                    f"- Allow VC Device Toggle: {report.runtime.allow_vc_device_toggle}",
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
            "| Step | Action | Target | Coords | Input/Keys | Confirm | Manual | Dry Run | Window | Locator | Locate Warnings | Recommended | Status | Duration | Screenshot | Reason |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---:|---|---|",
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
            manual = record.action_result.manual_override if record.action_result else False
            dry_run = record.action_result.dry_run if record.action_result else ""
            locator = ""
            locate_warnings = ""
            recommended = ""
            if record.located_target:
                locator = (
                    f"{record.located_target.source}/"
                    f"{record.located_target.confidence:.2f}/"
                    f"{record.located_target.bbox_area_ratio}"
                )
                locate_warnings = "; ".join(record.located_target.warnings)
                recommended = record.located_target.recommended_action
            window_title = record.after_window_title or record.before_window_title or ""
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
                f"{manual} | {dry_run} | {window_title} | {locator} | {locate_warnings} | {recommended} | "
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
