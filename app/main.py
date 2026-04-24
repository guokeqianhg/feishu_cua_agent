from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException

from agent.graph import build_graph
from agent.state import AgentState
from app.config import settings
from app.schemas import (
    ObserveResponse,
    PlanRequest,
    PlanResponse,
    RunCaseRequest,
    RunRequest,
    RunResponse,
    RunStatusResponse,
    ScreenshotDiagnosticsResponse,
)
from core.runtime import runtime_context
from core.schemas import TestCase
from storage.artifact_store import ArtifactStore
from storage.case_loader import load_case
from tools.capture.diagnostics import check_configured_monitor, run_screenshot_diagnostics
from tools.capture.mss_backend import MSSCaptureBackend
from tools.vision.ocr import OCRClient
from tools.vision.vlm_client import build_vlm_client


app = FastAPI(title=settings.app_name)
graph = build_graph()
artifact_store = ArtifactStore()


def _invoke(case: TestCase, dry_run: bool | None = None) -> AgentState:
    run_id = uuid4().hex
    run_dir = artifact_store.create_run_dir(run_id)
    context = runtime_context(dry_run)
    diagnostics = None
    if not context.dry_run:
        diagnostics = check_configured_monitor()
        if (not diagnostics.healthy) and (not settings.allow_unhealthy_screenshot):
            causes = "; ".join(diagnostics.possible_causes)
            raise HTTPException(
                status_code=409,
                detail=(
                    "Screenshot health check failed before real desktop execution. "
                    f"Diagnostics: {diagnostics.artifacts_dir}. Warnings: {diagnostics.warnings}. "
                    f"Possible causes: {causes}. Set CUA_LARK_ALLOW_UNHEALTHY_SCREENSHOT=true to force continue."
                ),
            )
    state = AgentState(
        run_id=run_id,
        test_case=case,
        artifacts_dir=str(run_dir),
        dry_run=context.dry_run,
        runtime=context,
        screenshot_diagnostics=diagnostics,
    )
    result = graph.invoke(state, config={"recursion_limit": max(settings.max_total_steps * 8, 100)})
    final_state = result if isinstance(result, AgentState) else AgentState.model_validate(dict(result))
    return final_state


def _response(state: AgentState) -> RunResponse:
    if state.run_report is None:
        raise HTTPException(status_code=500, detail="run finished without report")
    return RunResponse(
        run_id=state.run_id,
        case_id=state.test_case.id,
        status=state.status,
        summary=state.report_summary or "",
        steps=len(state.step_records),
        report_dir=state.artifacts_dir,
        summary_json=state.summary_json_path,
        summary_md=state.summary_md_path,
    )


@app.get("/health")
def health() -> dict:
    context = runtime_context()
    return {
        "status": "ok",
        "app": settings.app_name,
        "dry_run": settings.dry_run,
        "model_provider": settings.model_provider,
        "effective_model_provider": context.effective_model_provider,
        "placeholder_screenshot": settings.allow_placeholder_screenshot,
        "real_desktop_execution": context.real_desktop_execution,
        "mock_verification": context.mock_verification,
        "step_by_step": context.step_by_step,
        "abort_file": context.abort_file,
    }


@app.post("/runs", response_model=RunResponse)
def run_agent(req: RunRequest) -> RunResponse:
    if not req.task.strip():
        raise HTTPException(status_code=400, detail="task cannot be empty")
    case = TestCase(
        id=req.case_id or f"manual_{uuid4().hex[:8]}",
        name=req.case_name or "Manual natural-language run",
        product=req.product,
        instruction=req.task,
        preconditions=req.preconditions,
        expected_result=req.expected_result or "",
        tags=req.tags,
        timeout_seconds=req.timeout_seconds,
        metadata=req.metadata,
    )
    return _response(_invoke(case, req.dry_run))


@app.post("/run", response_model=RunResponse)
def run_agent_compat(req: RunRequest) -> RunResponse:
    return run_agent(req)


@app.post("/run-case", response_model=RunResponse)
def run_case(req: RunCaseRequest) -> RunResponse:
    path = Path(req.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"case file not found: {req.path}")
    return _response(_invoke(load_case(str(path)), req.dry_run))


@app.post("/plan", response_model=PlanResponse)
def plan(req: PlanRequest) -> PlanResponse:
    case = TestCase(id=f"plan_{uuid4().hex[:8]}", name="Plan preview", product=req.product, instruction=req.task)
    return PlanResponse(plan=build_vlm_client().create_plan(case))


@app.post("/observe", response_model=ObserveResponse)
def observe() -> ObserveResponse:
    run_id = uuid4().hex
    run_dir = artifact_store.create_run_dir(run_id)
    screenshot_path = ArtifactStore.screenshot_path(run_dir, "observe")
    image = MSSCaptureBackend().capture()
    image.save(screenshot_path)
    ocr_lines = OCRClient().extract_text(image)
    observation = build_vlm_client().describe_screen(str(screenshot_path), ocr_lines)
    return ObserveResponse(
        screenshot_path=str(screenshot_path),
        page_summary=observation.page_summary,
        elements=len(observation.elements),
        ocr_lines=observation.ocr_lines,
        warnings=observation.risk,
    )


@app.get("/diagnostics/screenshot", response_model=ScreenshotDiagnosticsResponse)
def screenshot_diagnostics() -> ScreenshotDiagnosticsResponse:
    return ScreenshotDiagnosticsResponse(report=run_screenshot_diagnostics(include_all_monitors=True))


@app.get("/runs/{run_id}", response_model=RunStatusResponse)
def get_run(run_id: str) -> RunStatusResponse:
    report_root = Path(settings.artifact_root) / "reports"
    matches = sorted(report_root.glob(f"run_*_{run_id[:8]}/summary.json"))
    if not matches:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    from core.schemas import TestRunReport

    report = TestRunReport.model_validate_json(matches[-1].read_text(encoding="utf-8"))
    return RunStatusResponse(run_id=run_id, status=report.status, report=report)
