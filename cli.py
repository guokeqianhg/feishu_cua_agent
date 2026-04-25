from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import yaml

from agent.graph import build_graph
from agent.state import AgentState
from app.config import settings
from core.runtime import mock_real_execution_block_reason, runtime_context
from core.schemas import TestCase
from intent.parser import enrich_case_with_intent, parse_instruction
from storage.artifact_store import ArtifactStore
from storage.case_loader import load_case
from agent.nodes.report import report_node
from tools.capture.diagnostics import check_configured_monitor, run_screenshot_diagnostics
from tools.capture.inspect import inspect_screen


def run_case(case: TestCase, step_by_step: bool | None = None, auto_debug: bool | None = None) -> AgentState:
    run_id = uuid4().hex
    run_dir = ArtifactStore().create_run_dir(run_id)
    context = runtime_context()
    if step_by_step is not None:
        context.step_by_step = step_by_step
    if auto_debug is not None:
        context.auto_debug = auto_debug
    if context.auto_debug:
        context.step_by_step = False
    block_reason = mock_real_execution_block_reason(context)
    if block_reason:
        print(block_reason, file=sys.stderr)
        raise SystemExit(2)
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
        auto_debug=context.auto_debug,
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


def _suite_case_paths(suite_path: Path) -> tuple[str, list[Path]]:
    payload = yaml.safe_load(suite_path.read_text(encoding="utf-8")) or {}
    suite_name = str(payload.get("name") or payload.get("id") or suite_path.stem)
    cases: list[Path] = []
    for item in payload.get("cases", []):
        raw_path = item.get("path") if isinstance(item, dict) else item
        if not raw_path:
            continue
        path = Path(str(raw_path))
        if not path.is_absolute():
            path = suite_path.parent / path
        cases.append(path)
    return suite_name, cases


def run_suite(path: str, step_by_step: bool | None = None, auto_debug: bool | None = None) -> dict:
    suite_path = Path(path)
    suite_name, case_paths = _suite_case_paths(suite_path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suite_dir = Path(settings.artifact_root) / "reports" / f"suite_{stamp}_{uuid4().hex[:8]}"
    suite_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for case_path in case_paths:
        try:
            state = run_case(load_case(str(case_path)), step_by_step=step_by_step, auto_debug=auto_debug)
            results.append(
                {
                    "case_path": str(case_path),
                    "case_id": state.test_case.id,
                    "product": state.run_report.product if state.run_report else state.test_case.product,
                    "status": state.status,
                    "summary": state.report_summary,
                    "report_dir": state.artifacts_dir,
                    "summary_json": state.summary_json_path,
                    "summary_md": state.summary_md_path,
                }
            )
        except SystemExit as exc:
            results.append({"case_path": str(case_path), "status": "error", "error": f"case exited with code {exc.code}"})
        except Exception as exc:
            results.append({"case_path": str(case_path), "status": "error", "error": str(exc)})

    total = len(results)
    passed = sum(1 for item in results if item.get("status") == "pass")
    failed = sum(1 for item in results if item.get("status") in {"fail", "error", "aborted"})
    products = sorted({str(item.get("product")) for item in results if item.get("product")})
    summary = {
        "suite_name": suite_name,
        "suite_path": str(suite_path),
        "status": "pass" if total and passed == total else "fail",
        "total": total,
        "passed": passed,
        "failed": failed,
        "products": products,
        "results": results,
        "suite_dir": str(suite_dir),
    }
    (suite_dir / "suite_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# CUA-Lark Suite Report",
        "",
        f"- Suite: {suite_name}",
        f"- Status: {summary['status']}",
        f"- Total: {total}",
        f"- Passed: {passed}",
        f"- Failed: {failed}",
        f"- Products: {', '.join(products)}",
        "",
        "| Case | Product | Status | Report | Summary |",
        "|---|---|---|---|---|",
    ]
    for item in results:
        lines.append(
            f"| {item.get('case_id') or item.get('case_path')} | {item.get('product', '')} | "
            f"{item.get('status')} | {item.get('summary_md') or item.get('report_dir') or ''} | "
            f"{item.get('summary') or item.get('error') or ''} |"
        )
    (suite_dir / "suite_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CUA-Lark test cases.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run a natural language instruction.")
    run.add_argument("--instruction", help="Natural language instruction. If omitted, CLI will prompt for it.")
    run.add_argument("--product", default="unknown")
    run.add_argument("--expected-result", default="")
    run.add_argument("--show-intent", action="store_true", help="Parse and print intent without executing the task.")
    run.add_argument("--step-by-step", action="store_true", help="Preview every action and wait for y/n/q or c x y.")
    run.add_argument("--auto-debug", action="store_true", help="Preview actions, execute automatically, and stop on unsafe state or failed verification.")

    run_case_cmd = sub.add_parser("run-case", help="Run a YAML test case.")
    run_case_cmd.add_argument("path")
    run_case_cmd.add_argument("--step-by-step", action="store_true", help="Preview every action and wait for y/n/q or c x y.")
    run_case_cmd.add_argument("--auto-debug", action="store_true", help="Preview actions, execute automatically, and stop on unsafe state or failed verification.")

    run_suite_cmd = sub.add_parser("run-suite", help="Run a YAML suite of test cases.")
    run_suite_cmd.add_argument("path")
    run_suite_cmd.add_argument("--step-by-step", action="store_true", help="Preview every action and wait for y/n/q or c x y.")
    run_suite_cmd.add_argument("--auto-debug", action="store_true", help="Preview actions, execute automatically, and stop on unsafe state or failed verification.")

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

    if args.command == "run-suite":
        summary = run_suite(
            args.path,
            step_by_step=getattr(args, "step_by_step", False) or settings.step_by_step,
            auto_debug=getattr(args, "auto_debug", False) or settings.auto_debug,
        )
        print(f"Suite {summary['status']}: {summary['passed']}/{summary['total']} cases passed. Products={summary['products']}")
        print(f"suite_dir={summary['suite_dir']}")
        print(f"suite_summary_json={Path(summary['suite_dir']) / 'suite_summary.json'}")
        print(f"suite_summary_md={Path(summary['suite_dir']) / 'suite_summary.md'}")
        raise SystemExit(0)

    if args.command == "run":
        instruction = args.instruction or input("请输入自然语言任务 / Instruction: ").strip()
        if not instruction:
            raise SystemExit("instruction cannot be empty")
        if getattr(args, "show_intent", False):
            parsed = parse_instruction(instruction, args.product)
            print(json.dumps(parsed.model_dump(), ensure_ascii=False, indent=2))
            raise SystemExit(0)
        case = TestCase(
            id=f"manual_{uuid4().hex[:8]}",
            name="CLI natural-language run",
            product=args.product,
            instruction=instruction,
            expected_result=args.expected_result,
        )
        case = enrich_case_with_intent(case)
    else:
        case = load_case(args.path)

    state = run_case(
        case,
        step_by_step=getattr(args, "step_by_step", False) or settings.step_by_step,
        auto_debug=getattr(args, "auto_debug", False) or settings.auto_debug,
    )
    print(state.report_summary)
    print(f"report_dir={state.artifacts_dir}")
    print(f"summary_json={state.summary_json_path}")
    print(f"summary_md={state.summary_md_path}")


if __name__ == "__main__":
    main()
