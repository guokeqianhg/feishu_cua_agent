from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field


RunStatus = Literal["queued", "running", "pass", "fail", "error", "human_review"]
Product = Literal["im", "docs", "calendar", "base", "vc", "mail", "unknown"]
ActionType = Literal[
    "click",
    "double_click",
    "right_click",
    "drag",
    "scroll",
    "type_text",
    "hotkey",
    "wait",
    "verify",
    "finish",
]
FailureCategory = Literal[
    "none",
    "perception_failed",
    "planning_failed",
    "location_failed",
    "action_failed",
    "verification_failed",
    "timeout",
    "permission_denied",
    "product_state_invalid",
    "unknown_error",
]


class BoundingBox(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int

    def center(self) -> tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)


class TestCase(BaseModel):
    id: str
    name: str
    product: Product = "unknown"
    instruction: str
    preconditions: list[str] = Field(default_factory=list)
    expected_result: str = ""
    tags: list[str] = Field(default_factory=list)
    timeout_seconds: int = 300
    metadata: dict[str, Any] = Field(default_factory=dict)


class UIElement(BaseModel):
    id: str | None = None
    label: str | None = None
    role: str | None = None
    bbox: BoundingBox | None = None
    confidence: float = 0.0
    source: Literal["vlm", "ocr", "accessibility", "dom", "cv", "manual", "mock"] = "vlm"
    text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Observation(BaseModel):
    screenshot_path: str
    timestamp: float = Field(default_factory=time.time)
    app_name: str = "Lark/Feishu"
    window_title: str | None = None
    page_type: str = "unknown"
    page_summary: str | None = None
    elements: list[UIElement] = Field(default_factory=list)
    ocr_lines: list[str] = Field(default_factory=list)
    risk: list[str] = Field(default_factory=list)
    raw_model_output: dict[str, Any] = Field(default_factory=dict)


class PlanStep(BaseModel):
    id: str
    action: ActionType
    target_description: str | None = None
    input_text: str | None = None
    coordinates: tuple[int, int] | None = None
    bbox: BoundingBox | None = None
    drag_to: tuple[int, int] | None = None
    hotkeys: list[str] = Field(default_factory=list)
    scroll_amount: int | None = None
    wait_seconds: float | None = None
    expected_state: str | None = None
    retry_limit: int = 1
    fallback_hints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TestPlan(BaseModel):
    goal: str
    product: Product = "unknown"
    steps: list[PlanStep] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    raw_model_output: dict[str, Any] = Field(default_factory=dict)


class LocatedTarget(BaseModel):
    step_id: str
    target_description: str | None = None
    source: Literal["vlm", "ocr", "accessibility", "dom", "history", "manual", "mock", "none"] = "none"
    bbox: BoundingBox | None = None
    center: tuple[int, int] | None = None
    confidence: float = 0.0
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    success: bool
    message: str = ""
    action: ActionType
    executed_at: float = Field(default_factory=time.time)
    dry_run: bool = False
    error_message: str | None = None


class StepVerification(BaseModel):
    success: bool
    confidence: float = 0.0
    reason: str = ""
    matched_criteria: list[str] = Field(default_factory=list)
    failed_criteria: list[str] = Field(default_factory=list)
    failure_category: FailureCategory = "none"
    raw_model_output: dict[str, Any] = Field(default_factory=dict)


class StepRunRecord(BaseModel):
    step_id: str
    step_index: int
    attempt: int
    action: ActionType
    target_description: str | None = None
    status: Literal["pass", "fail", "skipped", "error"]
    started_at: float
    ended_at: float
    duration_seconds: float
    located_target: LocatedTarget | None = None
    action_result: ActionResult | None = None
    verification: StepVerification | None = None
    before_screenshot: str | None = None
    after_screenshot: str | None = None
    error_message: str | None = None


class RunMetrics(BaseModel):
    total_steps: int = 0
    passed_steps: int = 0
    failed_steps: int = 0
    skipped_steps: int = 0
    retry_count: int = 0
    replan_count: int = 0
    success_rate: float = 0.0
    product_coverage: list[Product] = Field(default_factory=list)
    evidence_complete: bool = False


class TestRunReport(BaseModel):
    run_id: str
    case_id: str
    case_name: str
    product: Product
    instruction: str
    status: RunStatus
    started_at: float
    ended_at: float
    duration_seconds: float
    metrics: RunMetrics
    step_records: list[StepRunRecord] = Field(default_factory=list)
    artifacts_dir: str
    summary: str
    failure_category: FailureCategory = "none"
    error_message: str | None = None
    final_verification: StepVerification | None = None

