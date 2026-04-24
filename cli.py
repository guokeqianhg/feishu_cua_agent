from __future__ import annotations

import argparse
import json
import sys
from uuid import uuid4

from agent.graph import build_graph
from agent.state import AgentState
from app.config import settings
from core.runtime import runtime_context
from core.schemas import TestCase
from storage.artifact_store import ArtifactStore
from storage.case_loader import load_case
from agent.nodes.report import report_node
from tools.capture.diagnostics import check_configured_monitor, run_screenshot_diagnostics
from tools.capture.inspect import inspect_screen


def run_case(case: TestCase, step_by_step: bool | None = None) -> AgentState:
    run_id = uuid4().hex
    run_dir = ArtifactStore().create_run_dir(run_id)
    context = runtime_context()
    if step_by_step is not None:
        context.step_by_step = step_by_step
    diagnostics = None
    if not context.dry_run:
        diagnostics = check_configured_monitor()
        if (not diagnostics.healthy) and (not settings.allow_unhealthy_screenshot):
            print("真实桌面执行前截图健康检查失败，已阻止继续执行。", file=sys.stderr)
            print(f"诊断目录: {diagnostics.artifacts_dir}", file=sys.stderr)
            for warning in diagnostics.warnings:
                print(f"- {warning}", file=sys.stderr)
            print("可检查远程桌面、锁屏、权限、显示器编号、飞书所在显示器等问题。", file=sys.stderr)
            print("如确认风险可接受，可设置 CUA_LARK_ALLOW_UNHEALTHY_SCREENSHOT=true 强制继续。", file=sys.stderr)
            raise SystemExit(2)
    state = AgentState(
        run_id=run_id,
        test_case=case,
        artifacts_dir=str(run_dir),
        dry_run=context.dry_run,
        runtime=context,
        screenshot_diagnostics=diagnostics,
        step_by_step=context.step_by_step,
    )
    try:
        result = build_graph().invoke(state, config={"recursion_limit": max(settings.max_total_steps * 8, 100)})
        return result if isinstance(result, AgentState) else AgentState.model_validate(dict(result))
    except KeyboardInterrupt:
        state.status = "aborted"
        step = state.current_step()
        state.aborted_step_id = step.id if step else None
        state.error = "User interrupted with Ctrl+C."
        return report_node(state)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CUA-Lark test cases.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run a natural language instruction.")
    run.add_argument("--instruction", required=True)
    run.add_argument("--product", default="unknown")
    run.add_argument("--expected-result", default="")
    run.add_argument("--step-by-step", action="store_true", help="Preview every action and wait for y/n/q.")

    run_case_cmd = sub.add_parser("run-case", help="Run a YAML test case.")
    run_case_cmd.add_argument("path")
    run_case_cmd.add_argument("--step-by-step", action="store_true", help="Preview every action and wait for y/n/q.")

    diag = sub.add_parser("screenshot-diagnostics", help="Diagnose MSS screenshot capture.")
    diag.add_argument("--configured-only", action="store_true", help="Only capture CUA_LARK_MONITOR_INDEX.")
    diag.add_argument("--json", action="store_true", help="Print the full JSON diagnostic report.")

    inspect = sub.add_parser("inspect-screen", help="Capture the screen with coordinate grid overlay.")
    inspect.add_argument("--grid-size", type=int, default=100)

    args = parser.parse_args()
    if args.command == "inspect-screen":
        result = inspect_screen(grid_size=args.grid_size)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0)

    if args.command == "screenshot-diagnostics":
        report = run_screenshot_diagnostics(include_all_monitors=not args.configured_only)
        if args.json:
            print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
        else:
            print(f"healthy={report.healthy}")
            print(f"artifacts_dir={report.artifacts_dir}")
            print(f"monitors={len(report.monitors)}")
            for monitor in report.monitors:
                print(f"monitor {monitor.index}: left={monitor.left} top={monitor.top} width={monitor.width} height={monitor.height}")
            for analysis in report.analyses:
                print(
                    f"capture monitor {analysis.monitor_index}: path={analysis.path} "
                    f"mean={analysis.mean_luma} stdev={analysis.stdev_luma} suspicious={analysis.is_suspicious}"
                )
            if report.warnings:
                print("warnings:")
                for warning in report.warnings:
                    print(f"- {warning}")
                print("possible_causes:")
                for cause in report.possible_causes:
                    print(f"- {cause}")
        raise SystemExit(0)

    if args.command == "run":
        case = TestCase(
            id=f"manual_{uuid4().hex[:8]}",
            name="CLI natural-language run",
            product=args.product,
            instruction=args.instruction,
            expected_result=args.expected_result,
        )
    else:
        case = load_case(args.path)

    state = run_case(case, step_by_step=getattr(args, "step_by_step", False) or settings.step_by_step)
    print(state.report_summary)
    print(f"report_dir={state.artifacts_dir}")
    print(f"summary_json={state.summary_json_path}")
    print(f"summary_md={state.summary_md_path}")


if __name__ == "__main__":
    main()
