from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.schemas import Product, RunStatus, ScreenshotDiagnosticReport, TestPlan, TestRunReport


class RunRequest(BaseModel):
    task: str
    product: Product = "unknown"
    case_id: str | None = None
    case_name: str | None = None
    expected_result: str | None = None
    preconditions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    timeout_seconds: int = 300
    dry_run: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunCaseRequest(BaseModel):
    path: str
    dry_run: bool | None = None


class RunResponse(BaseModel):
    run_id: str
    case_id: str
    status: RunStatus
    summary: str
    steps: int
    report_dir: str
    summary_json: str | None = None
    summary_md: str | None = None


class RunStatusResponse(BaseModel):
    run_id: str
    status: RunStatus
    report: TestRunReport | None = None


class PlanRequest(BaseModel):
    task: str
    product: Product = "unknown"


class PlanResponse(BaseModel):
    plan: TestPlan


class ObserveResponse(BaseModel):
    screenshot_path: str
    page_summary: str | None = None
    elements: int
    ocr_lines: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ScreenshotDiagnosticsResponse(BaseModel):
    report: ScreenshotDiagnosticReport
