from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from core.schemas import (
    ActionResult,
    FailureCategory,
    LocatedTarget,
    Observation,
    PlanStep,
    RunStatus,
    StepRunRecord,
    StepVerification,
    RuntimeContext,
    ScreenshotDiagnosticReport,
    TestCase,
    TestPlan,
    TestRunReport,
)


class StepLog(BaseModel):
    step_index: int
    node: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class AgentState(BaseModel):
    run_id: str
    test_case: TestCase

    status: RunStatus = "running"
    dry_run: bool | None = None
    step_by_step: bool = False
    skip_current_step: bool = False
    runtime: RuntimeContext | None = None
    screenshot_diagnostics: ScreenshotDiagnosticReport | None = None
    warnings: list[str] = Field(default_factory=list)
    started_at: float = Field(default_factory=time.time)
    ended_at: float | None = None
    artifacts_dir: str = ""
    error: str | None = None
    aborted_step_id: str | None = None
    failure_category: FailureCategory = "none"

    initial_observation: Observation | None = None
    before_observation: Observation | None = None
    after_observation: Observation | None = None
    final_observation: Observation | None = None

    plan: TestPlan | None = None
    current_step_idx: int = 0
    current_attempt: int = 1
    current_step_started_at: float | None = None

    last_located_target: LocatedTarget | None = None
    last_action_result: ActionResult | None = None
    last_verification: StepVerification | None = None
    final_verification: StepVerification | None = None

    step_records: list[StepRunRecord] = Field(default_factory=list)
    retry_count: int = 0
    replan_count: int = 0
    run_report: TestRunReport | None = None
    report_summary: str | None = None
    summary_json_path: str | None = None
    summary_md_path: str | None = None
    steps_jsonl_path: str | None = None

    logs: list[StepLog] = Field(default_factory=list)

    @property
    def case_id(self) -> str:
        return self.test_case.id

    def current_step(self) -> PlanStep | None:
        if self.plan is None:
            return None
        if 0 <= self.current_step_idx < len(self.plan.steps):
            return self.plan.steps[self.current_step_idx]
        return None

    def total_steps(self) -> int:
        return len(self.plan.steps) if self.plan else 0
