from __future__ import annotations

import time

from PIL import Image

from agent.state import AgentState
from core.schemas import BoundingBox, LocatedTarget, Observation, PlanStep
from storage.run_logger import RunLogger
from tools.vision.vlm_client import build_vlm_client


logger = RunLogger()
vlm = build_vlm_client()


def _target_kind(step: PlanStep) -> str:
    text = f"{step.id} {step.target_description or ''}".lower()
    if "message" in text or "im" in text or "消息" in text:
        return "message_entry"
    if "search" in text or "搜索" in text:
        return "search_box"
    if "button" in text or "按钮" in text:
        return "button"
    return "generic"


def _static_safe_smoke_target(step: PlanStep, observation: Observation) -> LocatedTarget | None:
    if step.id not in ("focus_search", "type_safe_query"):
        return None
    size = _screen_size(observation)
    if size is None:
        return None
    width, height = size
    if width < 400 or height < 300:
        return None
    if step.id == "focus_search":
        bbox = BoundingBox(x1=60, y1=235, x2=265, y2=295)
        reason = "Safe smoke static target for Feishu left sidebar search box."
    else:
        bbox = BoundingBox(x1=190, y1=265, x2=1025, y2=325)
        reason = "Safe smoke static target for Feishu search dialog input box."
    return LocatedTarget(
        step_id=step.id,
        target_description=step.target_description,
        source="manual",
        bbox=bbox,
        center=bbox.center(),
        confidence=0.9,
        reason=reason,
        metadata={"strategy": "safe_smoke_static_search_box"},
    )


def _screen_size(observation: Observation) -> tuple[int, int] | None:
    try:
        image = Image.open(observation.screenshot_path)
        return image.size
    except Exception:
        return None


def _add_locator_safety(step: PlanStep, observation: Observation, located: LocatedTarget) -> LocatedTarget:
    if located.bbox is None:
        return located

    size = _screen_size(observation)
    if size is None:
        return located

    width, height = size
    screen_area = max(width * height, 1)
    bbox_width = max(located.bbox.x2 - located.bbox.x1, 0)
    bbox_height = max(located.bbox.y2 - located.bbox.y1, 0)
    area_ratio = (bbox_width * bbox_height) / screen_area
    located.bbox_area_ratio = round(area_ratio, 6)
    center = located.center or located.bbox.center()
    kind = _target_kind(step)

    warnings: list[str] = []
    if kind in ("message_entry", "button") and area_ratio > 0.08:
        warnings.append(f"bbox_area_ratio={area_ratio:.4f} is too large for {kind}.")
    if kind == "search_box" and area_ratio > 0.20:
        warnings.append(f"bbox_area_ratio={area_ratio:.4f} is too large for a search box.")
    if kind == "message_entry" and center[0] > width * 0.30:
        warnings.append("candidate_center is not in the expected left navigation area for the message entry.")
    if kind == "search_box" and center[1] > height * 0.45:
        warnings.append("candidate_center is lower than expected for a search box/global search control.")

    if warnings:
        located.warnings.extend(warnings)
        if step.id == "open_im":
            located.recommended_action = "skip"
        elif step.action in ("click", "double_click", "right_click"):
            located.recommended_action = "manual_coordinate"
        else:
            located.recommended_action = "abort"
    return located


def locate_node(state: AgentState) -> AgentState:
    step = state.current_step()
    if step is None:
        state.status = "fail"
        state.failure_category = "planning_failed"
        state.error = "No current step available."
        return state
    if state.before_observation is None:
        state.status = "fail"
        state.failure_category = "perception_failed"
        state.error = "No before observation available."
        return state

    state.current_step_started_at = time.time()
    located = _static_safe_smoke_target(step, state.before_observation) or vlm.locate_element(state.before_observation, step)
    located = _add_locator_safety(step, state.before_observation, located)
    state.last_located_target = located
    logger.log(state, "locate", "Target located", step_id=step.id, located=located.model_dump())
    if step.action in ("click", "double_click", "right_click", "drag") and located.confidence <= 0:
        state.status = "fail"
        state.failure_category = "location_failed"
        state.error = f"Could not locate target for step {step.id}: {step.target_description}"
    return state
