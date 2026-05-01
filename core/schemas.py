from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


RunStatus = Literal["queued", "running", "pass", "fail", "error", "human_review", "aborted"]
Product = Literal["im", "docs", "calendar", "base", "vc", "mail", "unknown"]
ActionType = Literal[
    "click",
    "double_click",
    "right_click",
    "drag",
    "scroll",
    "hover",
    "type_text",
    "paste_image",
    "hotkey",
    "wait",
    "focus_window",
    "conditional_hotkey",
    "conditional_click",
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
    source: Literal["vlm", "ocr", "accessibility", "dom", "history", "manual", "cv", "hybrid", "mock", "none"] = "none"
    bbox: BoundingBox | None = None
    center: tuple[int, int] | None = None
    confidence: float = 0.0
    reason: str = ""
    bbox_area_ratio: float | None = None
    warnings: list[str] = Field(default_factory=list)
    recommended_action: Literal["continue", "skip", "abort", "manual_coordinate"] = "continue"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    success: bool
    message: str = ""
    action: ActionType
    executed_at: float = Field(default_factory=time.time)
    dry_run: bool = False
    coordinates: tuple[int, int] | None = None
    drag_to: tuple[int, int] | None = None
    input_text: str | None = None
    hotkeys: list[str] = Field(default_factory=list)
    scroll_amount: int | None = None
    wait_seconds: float | None = None
    user_confirmed: bool | None = None
    user_decision: Literal["yes", "skip", "abort", "auto", "manual_coordinate"] = "auto"
    skipped: bool = False
    manual_override: bool = False
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
    status: Literal["pass", "fail", "skipped", "error", "aborted"]
    started_at: float
    ended_at: float
    duration_seconds: float
    located_target: LocatedTarget | None = None
    action_result: ActionResult | None = None
    verification: StepVerification | None = None
    before_screenshot: str | None = None
    after_screenshot: str | None = None
    before_window_title: str | None = None
    after_window_title: str | None = None
    error_message: str | None = None
    user_confirmed: bool | None = None
    user_decision: str | None = None


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


class RuntimeContext(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_provider: str
    effective_model_provider: str
    dry_run: bool
    placeholder_screenshot: bool
    real_desktop_execution: bool
    mock_verification: bool
    step_by_step: bool = False
    auto_debug: bool = False
    abort_file: str | None = None
    allow_unhealthy_screenshot: bool = False
    allow_mock_real_execution: bool = False
    allow_send_message: bool = False
    allowed_im_target: str | None = None
    allow_send_image: bool = False
    allow_create_group: bool = False
    allow_emoji_reaction: bool = False
    allowed_group_member: str | None = None
    allow_doc_create: bool = False
    allow_calendar_create: bool = False
    allow_calendar_invite: bool = False
    allow_vc_start: bool = False
    allow_vc_join: bool = False
    allow_vc_device_toggle: bool = False
    monitor_index: int | None = None


class ScreenshotAnalysis(BaseModel):
    path: str
    monitor_index: int
    width: int
    height: int
    mean_luma: float
    stdev_luma: float
    min_luma: int
    max_luma: int
    is_suspicious: bool
    is_black: bool
    is_near_solid: bool
    warning: str | None = None


class MonitorInfo(BaseModel):
    index: int
    left: int
    top: int
    width: int
    height: int


class ScreenshotDiagnosticReport(BaseModel):
    diagnostic_id: str
    created_at: float = Field(default_factory=time.time)
    artifacts_dir: str
    monitors: list[MonitorInfo] = Field(default_factory=list)
    analyses: list[ScreenshotAnalysis] = Field(default_factory=list)
    healthy: bool = False
    warnings: list[str] = Field(default_factory=list)
    possible_causes: list[str] = Field(default_factory=list)


class TestRunReport(BaseModel):
    run_id: str
    case_id: str
    case_name: str
    product: Product
    instruction: str
    parsed_intent: dict[str, Any] = Field(default_factory=dict)
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
    runtime: RuntimeContext | None = None
    warnings: list[str] = Field(default_factory=list)
    screenshot_diagnostics: ScreenshotDiagnosticReport | None = None
