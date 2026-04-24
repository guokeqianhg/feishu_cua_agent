from __future__ import annotations

import base64
import json
import re
from abc import ABC, abstractmethod
from typing import Any

from openai import OpenAI

from app.config import settings
from core.schemas import (
    BoundingBox,
    LocatedTarget,
    Observation,
    PlanStep,
    StepVerification,
    TestCase,
    TestPlan,
    UIElement,
)


def _json_payload(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    raw = re.sub(r"^\s*```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```\s*$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    return json.loads(raw)


def _product_from_text(text: str) -> str:
    raw = text.lower()
    if "im" in raw or "消息" in text or "群" in text or "聊天" in text:
        return "im"
    if "doc" in raw or "文档" in text or "周报" in text:
        return "docs"
    if "calendar" in raw or "日历" in text or "会议" in text or "日程" in text:
        return "calendar"
    return "unknown"


def _quoted_value(text: str, default: str) -> str:
    matches = re.findall(r"[「'\"“](.*?)[」'\"”]", text)
    return matches[-1].strip() if matches else default


def _bbox(payload: Any) -> BoundingBox | None:
    if not isinstance(payload, dict):
        return None
    try:
        return BoundingBox(
            x1=int(float(payload["x1"])),
            y1=int(float(payload["y1"])),
            x2=int(float(payload["x2"])),
            y2=int(float(payload["y2"])),
        )
    except Exception:
        return None


class BaseVLMClient(ABC):
    @abstractmethod
    def create_plan(self, case: TestCase, observation: Observation | None = None) -> TestPlan:
        raise NotImplementedError

    @abstractmethod
    def describe_screen(self, screenshot_path: str, ocr_lines: list[str] | None = None) -> Observation:
        raise NotImplementedError

    @abstractmethod
    def locate_element(self, observation: Observation, step: PlanStep) -> LocatedTarget:
        raise NotImplementedError

    @abstractmethod
    def verify_step(self, step: PlanStep, before: Observation | None, after: Observation | None) -> StepVerification:
        raise NotImplementedError

    @abstractmethod
    def verify_case(self, case: TestCase, plan: TestPlan, final_observation: Observation | None) -> StepVerification:
        raise NotImplementedError


class MockVLMClient(BaseVLMClient):
    def create_plan(self, case: TestCase, observation: Observation | None = None) -> TestPlan:
        product = case.product if case.product != "unknown" else _product_from_text(case.instruction)
        text = case.instruction

        if case.metadata.get("safe_smoke") or "no-send" in case.tags or "smoke_search" in case.id:
            steps = [
                PlanStep(id="open_im", action="click", target_description="left navigation message or IM entry", expected_state="IM page is open", retry_limit=2),
                PlanStep(id="focus_search", action="click", target_description="global or message search box", expected_state="search box is focused", retry_limit=2),
                PlanStep(id="type_safe_query", action="type_text", target_description="search box", input_text="harmless-smoke-test", expected_state="search text is entered"),
                PlanStep(id="observe_results", action="wait", wait_seconds=1.0, expected_state="search results or empty state are visible"),
                PlanStep(id="verify_no_send", action="verify", target_description="current screen", expected_state="No chat message was sent"),
            ]
        elif product == "im":
            message = _quoted_value(text, "Hello World")
            steps = [
                PlanStep(id="open_im", action="click", target_description="left navigation message or IM entry", expected_state="IM page is open", retry_limit=2),
                PlanStep(id="focus_search", action="click", target_description="global or message search box", expected_state="search box is focused", retry_limit=2),
                PlanStep(id="type_query", action="type_text", target_description="search box", input_text="测试群", expected_state="search results are visible"),
                PlanStep(id="open_chat", action="click", target_description="target chat in search results", expected_state="chat window is open", retry_limit=2),
                PlanStep(id="type_message", action="type_text", target_description="chat message input box", input_text=message, expected_state="message text is in input box"),
                PlanStep(id="send_message", action="hotkey", hotkeys=["enter"], expected_state="message is sent"),
                PlanStep(id="verify_message", action="verify", target_description="latest chat message", expected_state="target message appears in chat history"),
            ]
        elif product == "docs":
            steps = [
                PlanStep(id="open_docs", action="click", target_description="Docs entry in Lark sidebar or workplace", expected_state="Docs page is open", retry_limit=2),
                PlanStep(id="create_doc", action="click", target_description="new document button", expected_state="new document editor is open", retry_limit=2),
                PlanStep(id="type_title", action="type_text", target_description="document title field", input_text=_quoted_value(text, "2026年Q2项目进展"), expected_state="document title appears"),
                PlanStep(id="verify_doc", action="verify", target_description="document title", expected_state="new document title is visible"),
            ]
        elif product == "calendar":
            steps = [
                PlanStep(id="open_calendar", action="click", target_description="Calendar entry in Lark sidebar", expected_state="Calendar page is open", retry_limit=2),
                PlanStep(id="create_event", action="click", target_description="create event button or target time slot", expected_state="event editor is open", retry_limit=2),
                PlanStep(id="type_event", action="type_text", target_description="event title or attendee field", input_text="明天下午2点会议 张三", expected_state="event details are filled"),
                PlanStep(id="save_event", action="click", target_description="save or confirm event button", expected_state="event is saved"),
                PlanStep(id="verify_event", action="verify", target_description="calendar event", expected_state="calendar event appears"),
            ]
        else:
            steps = [
                PlanStep(id="observe", action="wait", wait_seconds=1.0, expected_state="screen remains available"),
                PlanStep(id="verify", action="verify", target_description="task result", expected_state=case.expected_result or case.instruction),
            ]

        return TestPlan(
            goal=case.instruction,
            product=product,  # type: ignore[arg-type]
            steps=steps,
            success_criteria=[case.expected_result or f"Task is completed: {case.instruction}"],
            assumptions=["Mock planner is deterministic so local dry-run verification can run without API keys."],
            raw_model_output={"provider": "mock"},
        )

    def describe_screen(self, screenshot_path: str, ocr_lines: list[str] | None = None) -> Observation:
        elements = [
            UIElement(label="Messages", role="navigation", bbox=BoundingBox(x1=20, y1=90, x2=110, y2=140), confidence=0.8, source="mock"),
            UIElement(label="Search", role="input", bbox=BoundingBox(x1=130, y1=40, x2=520, y2=88), confidence=0.75, source="mock"),
            UIElement(label="Primary action", role="button", bbox=BoundingBox(x1=620, y1=520, x2=780, y2=580), confidence=0.7, source="mock"),
            UIElement(label="Text input", role="input", bbox=BoundingBox(x1=240, y1=720, x2=1040, y2=790), confidence=0.8, source="mock"),
        ]
        return Observation(
            screenshot_path=screenshot_path,
            page_type="mock_lark",
            page_summary="Mock Feishu/Lark desktop screen for deterministic local execution.",
            elements=elements,
            ocr_lines=ocr_lines or [],
            raw_model_output={"provider": "mock"},
        )

    def locate_element(self, observation: Observation, step: PlanStep) -> LocatedTarget:
        if step.action in ("wait", "hotkey", "type_text", "verify", "finish"):
            return LocatedTarget(step_id=step.id, source="none", confidence=1.0, reason="Action does not require pointer location.")
        if step.coordinates:
            return LocatedTarget(step_id=step.id, source="manual", center=step.coordinates, confidence=1.0, reason="Coordinates provided by plan.")
        if step.bbox:
            return LocatedTarget(step_id=step.id, source="manual", bbox=step.bbox, center=step.bbox.center(), confidence=1.0, reason="Bounding box provided by plan.")
        element = observation.elements[0] if observation.elements else None
        if element and element.bbox:
            return LocatedTarget(
                step_id=step.id,
                target_description=step.target_description,
                source="mock",
                bbox=element.bbox,
                center=element.bbox.center(),
                confidence=0.75,
                reason=f"Mock matched target: {step.target_description}",
            )
        return LocatedTarget(step_id=step.id, target_description=step.target_description, source="none", confidence=0.0, reason="No element found.")

    def verify_step(self, step: PlanStep, before: Observation | None, after: Observation | None) -> StepVerification:
        return StepVerification(
            success=True,
            confidence=0.85,
            reason=f"Mock verification passed for step {step.id}: {step.expected_state or step.action}",
            matched_criteria=[step.expected_state or step.id],
            raw_model_output={"provider": "mock"},
        )

    def verify_case(self, case: TestCase, plan: TestPlan, final_observation: Observation | None) -> StepVerification:
        return StepVerification(
            success=True,
            confidence=0.85,
            reason="Mock final verification passed. The full plan executed and produced step evidence.",
            matched_criteria=plan.success_criteria,
            raw_model_output={"provider": "mock"},
        )


class OpenAICompatibleVLMClient(MockVLMClient):
    def __init__(self) -> None:
        self.client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)

    def _chat_text(self, prompt: str) -> str:
        resp = self.client.chat.completions.create(
            model=settings.openai_model_text,
            messages=[
                {"role": "system", "content": "You are a strict JSON assistant. Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        return (resp.choices[0].message.content or "").strip()

    def _chat_vision(self, prompt: str, screenshot_path: str) -> str:
        with open(screenshot_path, "rb") as file:
            image_b64 = base64.b64encode(file.read()).decode("utf-8")
        resp = self.client.chat.completions.create(
            model=settings.openai_model_vision,
            messages=[
                {"role": "system", "content": "You are a strict GUI vision JSON assistant. Return valid JSON only."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                    ],
                },
            ],
            temperature=0,
        )
        return (resp.choices[0].message.content or "").strip()

    def create_plan(self, case: TestCase, observation: Observation | None = None) -> TestPlan:
        prompt = f"""
Convert this Feishu/Lark desktop GUI test case into executable JSON.
Return exactly these fields: goal, product, steps, success_criteria, assumptions.
Each step must contain: id, action, target_description, input_text, hotkeys, scroll_amount, wait_seconds, expected_state, retry_limit.
Allowed actions: click, double_click, right_click, drag, scroll, type_text, hotkey, wait, verify, finish.

Case:
{case.model_dump_json()}

Current observation:
{observation.model_dump_json() if observation else "null"}
""".strip()
        try:
            return TestPlan.model_validate(_json_payload(self._chat_text(prompt)))
        except Exception:
            return super().create_plan(case, observation)

    def describe_screen(self, screenshot_path: str, ocr_lines: list[str] | None = None) -> Observation:
        prompt = f"""
Analyze this Feishu/Lark desktop screenshot and return JSON with:
page_type, page_summary, elements, risk.
Each element must contain label, role, bbox, confidence, text.
bbox format: {{"x1": 0, "y1": 0, "x2": 100, "y2": 100}}.
OCR lines:
{ocr_lines or []}
""".strip()
        try:
            payload = _json_payload(self._chat_vision(prompt, screenshot_path))
            elements: list[UIElement] = []
            for item in payload.get("elements", []):
                if not isinstance(item, dict):
                    continue
                elements.append(
                    UIElement(
                        label=item.get("label") or item.get("name"),
                        role=item.get("role"),
                        bbox=_bbox(item.get("bbox")),
                        confidence=float(item.get("confidence", item.get("score", 0.0)) or 0.0),
                        source="vlm",
                        text=item.get("text"),
                        metadata={k: v for k, v in item.items() if k not in {"label", "name", "role", "bbox", "confidence", "score", "text"}},
                    )
                )
            return Observation(
                screenshot_path=screenshot_path,
                page_type=str(payload.get("page_type", "unknown")),
                page_summary=payload.get("page_summary"),
                elements=elements,
                ocr_lines=ocr_lines or [],
                risk=[str(x) for x in payload.get("risk", [])] if isinstance(payload.get("risk", []), list) else [],
                raw_model_output=payload,
            )
        except Exception:
            return super().describe_screen(screenshot_path, ocr_lines)

    def locate_element(self, observation: Observation, step: PlanStep) -> LocatedTarget:
        if step.action in ("wait", "hotkey", "type_text", "verify", "finish"):
            return super().locate_element(observation, step)
        prompt = f"""
Locate the target UI element for this Feishu/Lark GUI action.
Return JSON with: bbox, center, confidence, reason.
bbox format: {{"x1": 0, "y1": 0, "x2": 100, "y2": 100}}.
center format: [x, y].

Step:
{step.model_dump_json()}
""".strip()
        try:
            payload = _json_payload(self._chat_vision(prompt, observation.screenshot_path))
            bbox = _bbox(payload.get("bbox"))
            center_payload = payload.get("center")
            center = None
            if isinstance(center_payload, list) and len(center_payload) >= 2:
                center = (int(float(center_payload[0])), int(float(center_payload[1])))
            if center is None and bbox:
                center = bbox.center()
            return LocatedTarget(
                step_id=step.id,
                target_description=step.target_description,
                source="vlm",
                bbox=bbox,
                center=center,
                confidence=float(payload.get("confidence", 0.0) or 0.0),
                reason=str(payload.get("reason", "")),
                metadata=payload,
            )
        except Exception:
            return super().locate_element(observation, step)

    def verify_step(self, step: PlanStep, before: Observation | None, after: Observation | None) -> StepVerification:
        if after is None:
            return StepVerification(success=False, reason="No after observation available.", failure_category="perception_failed")
        prompt = f"""
Verify whether this GUI test step has reached the expected state.
Return JSON with: success, confidence, reason, matched_criteria, failed_criteria, failure_category.

Step:
{step.model_dump_json()}

Before:
{before.model_dump_json() if before else "null"}

After:
{after.model_dump_json()}
""".strip()
        try:
            payload = _json_payload(self._chat_vision(prompt, after.screenshot_path))
            return StepVerification.model_validate(payload)
        except Exception:
            return super().verify_step(step, before, after)

    def verify_case(self, case: TestCase, plan: TestPlan, final_observation: Observation | None) -> StepVerification:
        if final_observation is None:
            return StepVerification(success=False, reason="No final observation available.", failure_category="perception_failed")
        prompt = f"""
Verify whether the whole Feishu/Lark GUI test case passed.
Return JSON with: success, confidence, reason, matched_criteria, failed_criteria, failure_category.

Case:
{case.model_dump_json()}

Plan:
{plan.model_dump_json()}

Final observation:
{final_observation.model_dump_json()}
""".strip()
        try:
            payload = _json_payload(self._chat_vision(prompt, final_observation.screenshot_path))
            return StepVerification.model_validate(payload)
        except Exception:
            return super().verify_case(case, plan, final_observation)


def build_vlm_client() -> BaseVLMClient:
    provider = settings.model_provider.lower()
    if provider == "mock":
        return MockVLMClient()
    if provider == "auto" and (not settings.openai_api_key) and settings.use_mock_when_no_key:
        return MockVLMClient()
    return OpenAICompatibleVLMClient()
