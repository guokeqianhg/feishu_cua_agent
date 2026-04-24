from __future__ import annotations

import argparse
from uuid import uuid4

from agent.graph import build_graph
from agent.state import AgentState
from app.config import settings
from core.schemas import TestCase
from storage.artifact_store import ArtifactStore
from storage.case_loader import load_case


def run_case(case: TestCase) -> AgentState:
    run_id = uuid4().hex
    run_dir = ArtifactStore().create_run_dir(run_id)
    state = AgentState(run_id=run_id, test_case=case, artifacts_dir=str(run_dir))
    result = build_graph().invoke(state, config={"recursion_limit": max(settings.max_total_steps * 8, 100)})
    return result if isinstance(result, AgentState) else AgentState.model_validate(dict(result))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CUA-Lark test cases.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run a natural language instruction.")
    run.add_argument("--instruction", required=True)
    run.add_argument("--product", default="unknown")
    run.add_argument("--expected-result", default="")

    run_case_cmd = sub.add_parser("run-case", help="Run a YAML test case.")
    run_case_cmd.add_argument("path")

    args = parser.parse_args()
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

    state = run_case(case)
    print(state.report_summary)
    print(f"report_dir={state.artifacts_dir}")
    print(f"summary_json={state.summary_json_path}")
    print(f"summary_md={state.summary_md_path}")


if __name__ == "__main__":
    main()
