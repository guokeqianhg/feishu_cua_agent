from __future__ import annotations

import base64
import json
import re
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from openai import OpenAI
from PIL import Image

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
from verification.registry import local_verify_step


def _json_payload(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    raw = re.sub(r"^\s*```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```\s*$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        repaired = _repair_json_payload(raw)
        return json.loads(repaired)


def _repair_json_payload(raw: str) -> str:
    # Some vision models occasionally emit {"bbox": {"x1": 1, 2, 3, 4}}.
    # Keep the repair narrow so genuinely invalid output still fails safely.
    number = r"-?\d+(?:\.\d+)?"
    bbox_pattern = re.compile(
        rf'("bbox"\s*:\s*)\{{\s*"x1"\s*:\s*({number})\s*,\s*({number})\s*,\s*({number})\s*,\s*({number})\s*\}}'
    )
    repaired = bbox_pattern.sub(r'\1{"x1": \2, "y1": \3, "x2": \4, "y2": \5}', raw)
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired


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
    if isinstance(payload, list) and len(payload) >= 4:
        try:
            return BoundingBox(
                x1=int(float(payload[0])),
                y1=int(float(payload[1])),
                x2=int(float(payload[2])),
                y2=int(float(payload[3])),
            )
        except Exception:
            return None
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


def _image_size(path: str) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def _resized_copy_for_model(path: str, max_side: int = 1280) -> tuple[str, tuple[int, int], tuple[int, int]]:
    original_size = _image_size(path)
    original_w, original_h = original_size
    longest = max(original_w, original_h)
    if longest <= max_side:
        return path, original_size, original_size

    scale = max_side / longest
    resized_size = (max(1, round(original_w * scale)), max(1, round(original_h * scale)))
    with Image.open(path) as image:
        resized = image.convert("RGB").resize(resized_size, Image.Resampling.LANCZOS)
        tmp = tempfile.NamedTemporaryFile(prefix="cua_vlm_", suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()
        resized.save(tmp_path)
    return tmp_path, original_size, resized_size


def _project_point_to_original(point: tuple[int, int] | None, original_size: tuple[int, int], model_size: tuple[int, int]) -> tuple[int, int] | None:
    if point is None:
        return None
    if original_size == model_size:
        return point
    sx = original_size[0] / max(model_size[0], 1)
    sy = original_size[1] / max(model_size[1], 1)
    return (round(point[0] * sx), round(point[1] * sy))


def _project_bbox_to_original(bbox: BoundingBox | None, original_size: tuple[int, int], model_size: tuple[int, int]) -> BoundingBox | None:
    if bbox is None or original_size == model_size:
        return bbox
    sx = original_size[0] / max(model_size[0], 1)
    sy = original_size[1] / max(model_size[1], 1)
    return BoundingBox(
        x1=round(bbox.x1 * sx),
        y1=round(bbox.y1 * sy),
        x2=round(bbox.x2 * sx),
        y2=round(bbox.y2 * sy),
    )


def _normalize_verification_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed_categories = {
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
    }
    if payload.get("failure_category") is None:
        payload["failure_category"] = "none"
    elif payload.get("failure_category") not in allowed_categories:
        payload["failure_category"] = "verification_failed"
    for key in ("matched_criteria", "failed_criteria"):
        value = payload.get(key)
        if value is None:
            payload[key] = []
        elif not isinstance(value, list):
            payload[key] = [str(value)]
    if payload.get("reason") is None:
        payload["reason"] = ""
    if payload.get("confidence") is None:
        payload["confidence"] = 0.0
    payload["raw_model_output"] = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "success",
            "confidence",
            "reason",
            "matched_criteria",
            "failed_criteria",
            "failure_category",
            "raw_model_output",
        }
    }
    return payload


def _calendar_busy_free_payload_is_valid(payload: dict[str, Any]) -> bool:
    if not bool(payload.get("success")):
        return True
    checks = {
        "calendar_visible": payload.get("calendar_visible"),
        "contact_selected": payload.get("contact_selected"),
        "target_date_visible": payload.get("target_date_visible"),
        "target_time_visible": payload.get("target_time_visible"),
    }
    availability = str(payload.get("availability_state") or "").lower()
    if any(value is None for value in checks.values()):
        return False
    if not all(bool(value) for value in checks.values()):
        return False
    if availability not in {"busy", "free"}:
        return False
    return True


def _normalize_calendar_busy_free_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_verification_payload(payload)
    if not _calendar_busy_free_payload_is_valid(payload):
        payload["success"] = False
        payload["confidence"] = min(float(payload.get("confidence") or 0.0), 0.35)
        payload["failure_category"] = "verification_failed"
        payload["reason"] = (
            "Calendar busy/free VLM output failed structured gate: "
            f"calendar_visible={payload.get('calendar_visible')}, "
            f"contact_selected={payload.get('contact_selected')}, "
            f"target_date_visible={payload.get('target_date_visible')}, "
            f"target_time_visible={payload.get('target_time_visible')}, "
            f"availability_state={payload.get('availability_state')}. "
            f"Original reason: {payload.get('reason') or ''}"
        )
        failed = payload.get("failed_criteria")
        if isinstance(failed, list):
            failed.append("structured_busy_free_gate")
        else:
            payload["failed_criteria"] = ["structured_busy_free_gate"]
    return payload


def _calendar_time_parts(raw_time: str) -> tuple[str, str, str]:
    now = datetime.now()
    if "后天" in raw_time or "寰屽ぉ" in raw_time:
        day_offset = 2
    elif "明天" in raw_time or "鏄庡ぉ" in raw_time:
        day_offset = 1
    else:
        day_offset = 0
    event_date = now + timedelta(days=day_offset)
    start_hour = 10
    start_minute = 0
    match = re.search(r"(\d{1,2}):(\d{2})", raw_time)
    if match:
        start_hour = int(match.group(1))
        start_minute = int(match.group(2))
    start_dt = event_date.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end_dt = start_dt + timedelta(minutes=30)
    return start_dt.strftime("%Y-%m-%d"), start_dt.strftime("%H:%M"), end_dt.strftime("%H:%M")


def _verification_prompt(step: PlanStep, before: Observation | None, after: Observation) -> str:
    verifier = str(step.metadata.get("local_verifier") or "")
    if verifier == "calendar_busy_free_visible" or step.id == "verify_busy_free_timeline":
        return f"""
You are verifying a real Feishu/Lark Calendar busy/free lookup from the screenshot.
Return JSON only. Required fields:
- success: boolean
- confidence: number from 0 to 1
- reason: string
- matched_criteria: string[]
- failed_criteria: string[]
- failure_category: string
- calendar_visible: boolean
- contact_selected: boolean
- target_date_visible: boolean
- target_time_visible: boolean
- availability_state: "busy" | "free" | "unknown"
- evidence_region: string describing the exact visual region used
- compressed_event_cards: boolean

Task-specific rule:
- This is NOT an event-creation verification. The workflow should only observe availability and must not save a new event.
- Feishu may show a searched/contact calendar by checking a contact row in the left panel and overlaying that person's availability on the existing week/day grid. It does not have to create a separate standalone "contact timeline" panel.
- If the search result row for the requested contact shows a blue checkmark or selected state, count that as contact_selected even when the left "my calendars" or "subscribed" area is ambiguous.
- Pass if the screenshot shows Calendar open, the requested contact is selected/checked or visibly present as a selected contact calendar, the target time range is visible/readable, and the grid shows either a busy/free colored block or a clear empty available slot at that target time for the selected contact.
- If a colored block near the target time contains partial text from an event or contact, treat it as busy/free evidence. Do not confuse this with failure merely because the card is narrow or overlaps other events.
- Fail if the contact was only typed in the search box but not selected/checked, if the target time is not visible, if a create-event/editor/dialog is open, or if the screen is not Calendar.
- If the local evidence below says the target hour is readable and target_slot_has_busy_color is true, inspect that exact target slot ROI first. Use the full screenshot to confirm contact selection and date context.
- Prefer local_evidence.contact_search_result_selected and local_evidence.contact_search_result_check_pixels when deciding contact_selected.
- Do not pass with availability_state="unknown". If the slot is visually empty for the selected contact, use availability_state="free"; if colored/busy blocks overlap the target slot, use "busy". If the contact is selected and the target slot is visible but empty, "free" is the correct outcome, not "unknown".

Expected busy/free lookup:
- contact(s): {step.metadata.get("attendees") or []}
- event_date: {step.metadata.get("event_date") or ""}
- start_time: {step.metadata.get("start_time") or step.metadata.get("event_time") or ""}
- local_evidence: {step.metadata.get("busy_free_local_evidence") or {}}

Step:
{step.model_dump_json()}

Before observation:
{before.model_dump_json() if before else "null"}

After observation:
{after.model_dump_json()}
""".strip()

    if verifier in {"calendar_event_visible", "calendar_case"} or step.id in {"verify_event", "final_calendar_event_visible"}:
        return f"""
You are verifying a real Feishu/Lark Calendar GUI test from the screenshot.
Return JSON only with: success, confidence, reason, matched_criteria, failed_criteria, failure_category.

Task-specific rule:
- Do not require OCR-readable title text inside the week grid. If multiple events share the same time, event cards may be narrow.
- Use visual understanding of the Calendar week/day view: date columns, time-axis labels, colored event blocks, and whether the target time slot contains a meeting/event.
- Pass only if the screenshot shows the target date/time area and a visible Calendar event/meeting block at or very near that time.
- Fail if the view is on the wrong product/window, wrong date, wrong time range, no event block near the target time, or a modal/dialog is still blocking completion.
- If the event title is visible, use it as strong evidence. If not visible because cards are narrow, use the event block at the requested date/time as evidence and explain that limitation.
- The expected date below is authoritative. When the week grid shows adjacent date columns, identify the column whose day number matches event_date. Do not describe or pass a neighboring column such as May 1 when event_date is May 2.
- If you mention a date in the reason, it must match event_date exactly or clearly say the event block is on the event_date column.

Expected Calendar event:
- title: {step.metadata.get("event_title") or ""}
- event_date: {step.metadata.get("event_date") or ""}
- start_time: {step.metadata.get("start_time") or step.metadata.get("event_time") or ""}
- end_time: {step.metadata.get("end_time") or ""}
- attendees: {step.metadata.get("attendees") or []}
- local_evidence: {step.metadata.get("calendar_event_local_evidence") or {}}

When local_evidence.target_slot_has_event_color is true, inspect local_evidence.target_slot_roi first.
If local_evidence.target_slot_right_edge_clipped is true, the event card may be truncated by the visible window edge; do not fail only because the full title is not readable.

Step:
{step.model_dump_json()}

Before observation:
{before.model_dump_json() if before else "null"}

After observation:
{after.model_dump_json()}
""".strip()

    return f"""
Verify whether this GUI test step has reached the expected state.
Return JSON with: success, confidence, reason, matched_criteria, failed_criteria, failure_category.

Step:
{step.model_dump_json()}

Before:
{before.model_dump_json() if before else "null"}

After:
{after.model_dump_json()}
""".strip()


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
    @staticmethod
    def _is_safe_smoke(case: TestCase) -> bool:
        return bool(case.metadata.get("safe_smoke") or "no-send" in case.tags or "smoke_search" in case.id)

    def create_plan(self, case: TestCase, observation: Observation | None = None) -> TestPlan:
        product = case.product if case.product != "unknown" else _product_from_text(case.instruction)
        text = case.instruction

        if self._is_safe_smoke(case):
            steps = [
                PlanStep(id="open_im", action="verify", target_description="current Feishu IM or messages page", expected_state="If IM is already open, continue; otherwise use step-by-step to skip and open Feishu manually.", retry_limit=1),
                PlanStep(id="focus_search", action="click", target_description="left sidebar search box", expected_state="Feishu sidebar search box is focused", retry_limit=1),
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
        if step.action in ("wait", "hotkey", "type_text", "paste_image", "focus_window", "verify", "finish"):
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

    def _chat_vision_resized(self, prompt: str, screenshot_path: str) -> tuple[str, dict[str, Any]]:
        model_path, original_size, model_size = _resized_copy_for_model(screenshot_path)
        metadata = {
            "original_size": {"width": original_size[0], "height": original_size[1]},
            "model_image_size": {"width": model_size[0], "height": model_size[1]},
            "coordinate_space": "model_image",
            "resized_for_model": model_path != screenshot_path,
        }
        try:
            text = self._chat_vision(prompt, model_path)
            return text, metadata
        finally:
            if model_path != screenshot_path:
                try:
                    Path(model_path).unlink(missing_ok=True)
                except Exception:
                    pass

    def create_plan(self, case: TestCase, observation: Observation | None = None) -> TestPlan:
        if self._is_safe_smoke(case):
            return super().create_plan(case, observation)

        prompt = f"""
Convert this Feishu/Lark desktop GUI test case into executable JSON.
Return exactly these fields: goal, product, steps, success_criteria, assumptions.
Each step must contain: id, action, target_description, input_text, hotkeys, scroll_amount, wait_seconds, expected_state, retry_limit.
Allowed actions: click, double_click, right_click, drag, scroll, type_text, hotkey, wait, focus_window, verify, finish.

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
        except Exception as exc:
            if not settings.dry_run:
                return Observation(
                    screenshot_path=screenshot_path,
                    page_type="unknown",
                    page_summary="Real VLM describe_screen failed.",
                    elements=[],
                    ocr_lines=ocr_lines or [],
                    risk=[f"Real VLM describe_screen failed; mock observation is disabled during real execution: {exc}"],
                    raw_model_output={"provider": "vlm_error", "error": str(exc)},
                )
            observation = super().describe_screen(screenshot_path, ocr_lines)
            observation.risk.append(f"Real VLM describe_screen failed and fell back to mock observation: {exc}")
            observation.raw_model_output = {"provider": "mock", "fallback_error": str(exc)}
            return observation

    def locate_element(self, observation: Observation, step: PlanStep) -> LocatedTarget:
        if step.action in ("wait", "hotkey", "paste_image", "focus_window", "verify", "finish"):
            return super().locate_element(observation, step)
        original_size = _image_size(observation.screenshot_path)
        model_max_side = 1280
        prompt = f"""
You are a UI element locator for Feishu/Lark desktop client.
Your task is to locate the target UI element from the screenshot and return ONLY a valid JSON object, NO other text or explanation.

REQUIRED JSON FIELDS:
- "bbox": Bounding box of the element, format: {{"x1": integer, "y1": integer, "x2": integer, "y2": integer}}.
- "center": Center coordinate of the element, format: [x_integer, y_integer]
- "confidence": Float between 0 and 1, how confident you are that this is the correct target
- "reason": Short string explaining your detection
- "target_absent": Boolean, true if the target is not visible in the screenshot

RULES:
1. ONLY return the JSON object, NO markdown, NO code blocks, NO extra text before or after
2. Use double quotes for all JSON keys and string values
3. All numbers must be integers, no floats in coordinates
4. If target is not visible / search results are empty: return {{"bbox": null, "center": null, "confidence": 0, "target_absent": true, "reason": "target not visible"}}
5. Only locate clickable elements that are clearly visible in the screenshot
6. For search results, locate the FIRST result row that matches the target name
7. Coordinates must be relative to the image you are given. The original screenshot is {original_size[0]}x{original_size[1]}; this image may be resized to max side {model_max_side}. Do not compensate for scaling yourself.

Target element to locate: {step.target_description}
Step action: {step.action}
""".strip()
        try:
            text, coordinate_metadata = self._chat_vision_resized(prompt, observation.screenshot_path)
            payload = _json_payload(text)
            bbox = _bbox(payload.get("bbox"))
            center_payload = payload.get("center")
            center = None
            if isinstance(center_payload, list) and len(center_payload) >= 2:
                center = (int(float(center_payload[0])), int(float(center_payload[1])))
            if center is None and bbox:
                center = bbox.center()
            model_size = (
                int(coordinate_metadata["model_image_size"]["width"]),
                int(coordinate_metadata["model_image_size"]["height"]),
            )
            bbox = _project_bbox_to_original(bbox, original_size, model_size)
            center = _project_point_to_original(center, original_size, model_size)
            confidence = float(payload.get("confidence", 0.0) or 0.0)
            target_absent = bool(payload.get("target_absent"))
            warnings = []
            recommended_action = "continue"
            if target_absent or center is None or confidence < 0.45:
                warnings.append("VLM could not confidently locate a visible target; action is unsafe.")
                recommended_action = "abort"
            return LocatedTarget(
                step_id=step.id,
                target_description=step.target_description,
                source="vlm",
                bbox=bbox,
                center=center,
                confidence=confidence,
                reason=str(payload.get("reason", "")),
                warnings=warnings,
                recommended_action=recommended_action,
                metadata={**payload, **coordinate_metadata, "returned_coordinate_space": "original_screenshot"},
            )
        except Exception as exc:
            if not settings.dry_run:
                return LocatedTarget(
                    step_id=step.id,
                    target_description=step.target_description,
                    source="none",
                    confidence=0.0,
                    reason="Real VLM locate_element failed; heuristic fallback is disabled during real desktop execution.",
                    warnings=[f"Real VLM locate_element failed: {exc}"],
                    recommended_action="abort",
                    metadata={"provider": "vlm_error", "error": str(exc)},
                )
            located = super().locate_element(observation, step)
            located.warnings.append(f"Real VLM locate_element failed and fell back to mock locator: {exc}")
            located.metadata["fallback_error"] = str(exc)
            return located

    def verify_step(self, step: PlanStep, before: Observation | None, after: Observation | None) -> StepVerification:
        if after is None:
            return StepVerification(success=False, reason="No after observation available.", failure_category="perception_failed")
        prompt = _verification_prompt(step, before, after)
        try:
            raw_payload = _json_payload(self._chat_vision(prompt, after.screenshot_path))
            if str(step.metadata.get("local_verifier") or "") == "calendar_busy_free_visible" or step.id == "verify_busy_free_timeline":
                payload = _normalize_calendar_busy_free_payload(raw_payload)
            else:
                payload = _normalize_verification_payload(raw_payload)
            return StepVerification.model_validate(payload)
        except Exception as exc:
            if not settings.dry_run:
                return StepVerification(
                    success=False,
                    confidence=0.0,
                    reason=f"Real VLM verification failed; mock fallback is disabled during real desktop execution: {exc}",
                    failed_criteria=[step.expected_state or step.id],
                    failure_category="verification_failed",
                    raw_model_output={"provider": "vlm_error", "error": str(exc)},
                )
            return super().verify_step(step, before, after)

    def _generic_verify_step(self, step: PlanStep, before: Observation | None, after: Observation | None) -> StepVerification:
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
            payload = _normalize_verification_payload(_json_payload(self._chat_vision(prompt, after.screenshot_path)))
            return StepVerification.model_validate(payload)
        except Exception as exc:
            if not settings.dry_run:
                return StepVerification(
                    success=False,
                    confidence=0.0,
                    reason=f"Real VLM verification failed; mock fallback is disabled during real desktop execution: {exc}",
                    failed_criteria=[step.expected_state or step.id],
                    failure_category="verification_failed",
                    raw_model_output={"provider": "vlm_error", "error": str(exc)},
                )
            return super().verify_step(step, before, after)

    def verify_case(self, case: TestCase, plan: TestPlan, final_observation: Observation | None) -> StepVerification:
        if final_observation is None:
            return StepVerification(success=False, reason="No final observation available.", failure_category="perception_failed")
        template = str(case.metadata.get("plan_template") or "")
        if case.product == "calendar" or template.startswith("calendar_"):
            event_time = str(case.metadata.get("new_event_time") or case.metadata.get("event_time") or "")
            event_date, start_time, end_time = _calendar_time_parts(event_time)
            if template == "calendar_view_busy_free_guarded":
                step = PlanStep(
                    id="verify_busy_free_timeline",
                    action="verify",
                    expected_state=case.expected_result or case.instruction,
                    metadata={
                        "local_verifier": "calendar_busy_free_visible",
                        "event_time": event_time,
                        "event_date": event_date,
                        "start_time": start_time,
                        "end_time": end_time,
                        "attendees": case.metadata.get("attendees") or [],
                    },
                )
                local_verify_step(case, step, None, final_observation)
            else:
                step = PlanStep(
                    id="final_calendar_event_visible",
                    action="verify",
                    expected_state=case.expected_result or case.instruction,
                    metadata={
                        "local_verifier": "calendar_case",
                        "event_title": str(case.metadata.get("event_title") or ""),
                        "event_time": event_time,
                        "event_date": event_date,
                        "start_time": start_time,
                        "end_time": end_time,
                        "attendees": case.metadata.get("attendees") or [],
                    },
                )
            prompt = _verification_prompt(step, None, final_observation)
        else:
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
            raw_payload = _json_payload(self._chat_vision(prompt, final_observation.screenshot_path))
            if case.product == "calendar" and str(case.metadata.get("plan_template") or "") == "calendar_view_busy_free_guarded":
                payload = _normalize_calendar_busy_free_payload(raw_payload)
            else:
                payload = _normalize_verification_payload(raw_payload)
            return StepVerification.model_validate(payload)
        except Exception as exc:
            if not settings.dry_run:
                return StepVerification(
                    success=False,
                    confidence=0.0,
                    reason=f"Real VLM final verification failed; mock fallback is disabled during real desktop execution: {exc}",
                    failed_criteria=plan.success_criteria,
                    failure_category="verification_failed",
                    raw_model_output={"provider": "vlm_error", "error": str(exc)},
                )
            return super().verify_case(case, plan, final_observation)


def build_vlm_client() -> BaseVLMClient:
    provider = settings.model_provider.lower()
    if provider == "mock":
        return MockVLMClient()
    if provider == "auto" and (not settings.openai_api_key) and settings.use_mock_when_no_key:
        return MockVLMClient()
    return OpenAICompatibleVLMClient()
