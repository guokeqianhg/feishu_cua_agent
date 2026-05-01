from __future__ import annotations

import time
import re

from PIL import Image

from agent.state import AgentState
from core.schemas import BoundingBox, LocatedTarget, Observation, PlanStep
from storage.run_logger import RunLogger
from tools.vision.lark_locator import detect_lark_window, locate_lark_target
from tools.vision.ocr_client import match_text_in_region, match_text_row_in_region, ocr_image
from tools.vision.vlm_client import build_vlm_client


logger = RunLogger()
vlm = build_vlm_client()


def _target_kind(step: PlanStep) -> str:
    explicit_kind = str(step.metadata.get("locator_kind") or "").strip().lower()
    if explicit_kind:
        return explicit_kind
    text = f"{step.id} {step.target_description or ''}".lower()
    strategy = str(step.metadata.get("locator_strategy") or "").lower()
    if step.action == "scroll":
        return "generic"
    if step.action == "type_text" or strategy in {"search_dialog_input", "message_input"}:
        return "text_input"
    if step.action == "paste_image":
        return "text_input"
    if step.id in {"type_query", "type_safe_query", "type_message"}:
        return "text_input"
    if "input" in text or "box" in text:
        return "text_input"
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


def _explicit_step_target(step: PlanStep) -> LocatedTarget | None:
    if step.metadata.get("use_current_focus") and step.action == "type_text":
        return LocatedTarget(
            step_id=step.id,
            target_description=step.target_description,
            source="none",
            confidence=1.0,
            reason="Workflow intentionally types into the currently focused field.",
            metadata={"strategy": "use_current_focus"},
        )
    if step.coordinates:
        return LocatedTarget(
            step_id=step.id,
            target_description=step.target_description,
            source="manual",
            center=step.coordinates,
            confidence=1.0,
            reason="Coordinates were provided by the product workflow plan.",
            metadata={"strategy": "explicit_step_coordinates"},
        )
    if step.bbox:
        return LocatedTarget(
            step_id=step.id,
            target_description=step.target_description,
            source="manual",
            bbox=step.bbox,
            center=step.bbox.center(),
            confidence=1.0,
            reason="Bounding box was provided by the product workflow plan.",
            metadata={"strategy": "explicit_step_bbox"},
        )
    return None


def _dry_run_simulated_target(state: AgentState, step: PlanStep) -> LocatedTarget | None:
    if not state.dry_run:
        return None
    if not _needs_visual_location(step):
        return None
    if not (step.metadata.get("force_vlm_locator") or step.metadata.get("dry_run_simulated_target")):
        return None
    return LocatedTarget(
        step_id=step.id,
        target_description=step.target_description,
        source="mock",
        confidence=1.0,
        reason="Dry-run simulated visual target for a VLM-only guarded workflow step.",
        recommended_action="continue",
        metadata={"strategy": "dry_run_force_vlm_simulation"},
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
    if kind == "text_input" and area_ratio > 0.16:
        warnings.append(f"bbox_area_ratio={area_ratio:.4f} is too large for a text input.")
    if kind == "search_box" and area_ratio > 0.20:
        warnings.append(f"bbox_area_ratio={area_ratio:.4f} is too large for a search box.")
    strategy = str(step.metadata.get("locator_strategy") or "").lower()
    if kind == "message_entry" and strategy != "im_message_row_by_text" and center[0] > width * 0.30:
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


def _point_in_window(point: tuple[int, int], window) -> bool:
    return window.x1 <= point[0] <= window.x2 and window.y1 <= point[1] <= window.y2


def _point_in_bbox(point: tuple[int, int] | None, bbox: BoundingBox | None) -> bool:
    if point is None or bbox is None:
        return False
    return bbox.x1 <= point[0] <= bbox.x2 and bbox.y1 <= point[1] <= bbox.y2


def _maybe_correct_scaled_vlm_target(observation: Observation, located: LocatedTarget) -> LocatedTarget:
    if located.source != "vlm" or located.center is None:
        return located
    window = detect_lark_window(observation.screenshot_path)
    if window is None or _point_in_window(located.center, window):
        return located

    # 自适应检测缩放比例：尝试常见的缩放因子 1.5x, 2x, 2.5x, 3x
    scale_factors = [1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
    best_scale = None
    best_scaled_center = None

    for scale in scale_factors:
        scaled_center = (
            round(located.center[0] * scale),
            round(located.center[1] * scale)
        )
        if _point_in_window(scaled_center, window):
            best_scale = scale
            best_scaled_center = scaled_center
            break

    if best_scale is None or best_scaled_center is None:
        return located

    # 缩放bbox
    if located.bbox:
        located.bbox = BoundingBox(
            x1=round(located.bbox.x1 * best_scale),
            y1=round(located.bbox.y1 * best_scale),
            x2=round(located.bbox.x2 * best_scale),
            y2=round(located.bbox.y2 * best_scale),
        )

    located.metadata["coordinate_scale_correction"] = {
        "factor": best_scale,
        "original_center": located.center,
        "scaled_center": best_scaled_center,
        "reason": f"VLM coordinate was outside the Feishu window; {best_scale}x scaled coordinate falls inside the detected window.",
    }
    located.center = best_scaled_center
    located.reason = (located.reason + " " if located.reason else "") + f"Applied {best_scale}x VLM coordinate correction."
    return located


def _safe_click_in_text_row(text_bbox: BoundingBox, row_bbox: BoundingBox) -> tuple[int, int]:
    """Click on the matched row, near the text but not on extreme row edges."""
    text_cx, text_cy = text_bbox.center()
    row_left_pad = max(16, min(52, (row_bbox.x2 - row_bbox.x1) // 8))
    x = max(row_bbox.x1 + row_left_pad, min(text_cx, row_bbox.x2 - 16))
    y = max(row_bbox.y1 + 8, min(text_cy, row_bbox.y2 - 8))
    return (x, y)


def _safe_click_in_search_result_row(text_bbox: BoundingBox, row_bbox: BoundingBox) -> tuple[int, int]:
    """Click the left text area of a search result, away from right-side snippets/actions."""
    _text_cx, text_cy = text_bbox.center()
    row_width = max(row_bbox.x2 - row_bbox.x1, 1)
    left_safe = row_bbox.x1 + max(34, min(84, row_width // 10))
    right_limit = row_bbox.x1 + min(row_width - 24, max(160, row_width // 3))
    x = max(row_bbox.x1 + 16, min(left_safe, right_limit))
    y = max(row_bbox.y1 + 10, min(text_cy, row_bbox.y2 - 10))
    return (x, y)


def _normalize_match_text(text: str) -> str:
    return re.sub(r"[\s，,。；;：:'\"“”‘’「」『』（）()【】\[\]\-_/\\|·•]+", "", (text or "").lower())


def _looks_like_search_snippet(text: str) -> bool:
    raw = text or ""
    return any(token in raw for token in ("包含", "群消息", "消息更新于", "聊天记录", "相关结果"))


def _find_exact_ocr_target_row(image_path: str, target_text: str, roi: BoundingBox) -> LocatedTarget | None:
    """Prefer exact contact/name rows over search snippets like '包含：吴佳园'."""
    results = ocr_image(image_path, roi)
    target_norm = _normalize_match_text(target_text)
    if not results or not target_norm:
        return None

    exact: list[tuple[BoundingBox, str, float]] = []
    contains: list[tuple[BoundingBox, str, float]] = []
    for bbox, text, confidence in results:
        text_norm = _normalize_match_text(text)
        if text_norm == target_norm:
            exact.append((bbox, text, confidence))
        elif target_norm in text_norm and not _looks_like_search_snippet(text):
            contains.append((bbox, text, confidence))

    pool = exact or contains
    if not pool:
        return None
    match_bbox, match_text, confidence = max(pool, key=lambda item: item[2])
    row_bbox = BoundingBox(
        x1=max(roi.x1, roi.x1 + 28),
        y1=max(roi.y1, match_bbox.y1 - 22),
        x2=min(roi.x2, roi.x2 - 28),
        y2=min(roi.y2, match_bbox.y2 + 28),
    )
    center = _safe_click_in_search_result_row(match_bbox, row_bbox)
    return LocatedTarget(
        step_id="open_chat",
        target_description=target_text,
        source="hybrid",
        bbox=row_bbox,
        center=center,
        confidence=min(0.98, max(0.82, float(confidence))),
        reason=f"OCR found exact target row {match_text!r}; clicking safe row point {center}.",
        metadata={
            "strategy": "ocr_exact_contact_row",
            "ocr": {
                "text": match_text,
                "confidence": float(confidence),
                "text_bbox": match_bbox.model_dump(),
                "row_bbox": row_bbox.model_dump(),
                "click_strategy": "exact_text_row",
            },
            "roi": roi.model_dump(),
        },
    )


def _ocr_confirmed_target(
    image_path: str,
    target_text: str,
    roi: BoundingBox,
    source_label: str,
    semantic: LocatedTarget | None = None,
    threshold: float = 0.52,
) -> LocatedTarget | None:
    row_bbox, row_text, row_conf = match_text_row_in_region(image_path, target_text, roi, threshold=threshold)
    text_bbox, text, text_conf = match_text_in_region(image_path, target_text, roi, threshold=threshold)
    if row_bbox is None and text_bbox is None:
        return None
    if _looks_like_search_snippet(row_text) or _looks_like_search_snippet(text):
        return None
    safe_bbox = row_bbox or text_bbox
    matched_bbox = text_bbox or row_bbox
    if safe_bbox is None or matched_bbox is None:
        return None
    center = _safe_click_in_text_row(matched_bbox, safe_bbox)
    confidence = max(row_conf, text_conf)
    metadata = {
        "strategy": "vlm_ocr_safe_row_click",
        "ocr": {
            "row_text": row_text,
            "text": text,
            "confidence": confidence,
            "row_bbox": row_bbox.model_dump() if row_bbox else None,
            "text_bbox": text_bbox.model_dump() if text_bbox else None,
            "click_strategy": "safe_text_row",
        },
        "roi": roi.model_dump(),
        "source_label": source_label,
    }
    if semantic is not None:
        metadata["semantic_vlm"] = {
            "bbox": semantic.bbox.model_dump() if semantic.bbox else None,
            "center": semantic.center,
            "confidence": semantic.confidence,
            "reason": semantic.reason,
            "metadata": semantic.metadata,
        }
    return LocatedTarget(
        step_id=semantic.step_id if semantic else "open_chat",
        target_description=semantic.target_description if semantic else target_text,
        source="hybrid",
        bbox=safe_bbox,
        center=center,
        confidence=min(0.97, max(0.7, confidence)),
        reason=f"OCR confirmed target {target_text!r} in {source_label}; clicking safe row point {center}.",
        metadata=metadata,
    )


def _needs_visual_location(step: PlanStep) -> bool:
    return step.action in (
        "click",
        "conditional_click",
        "double_click",
        "right_click",
        "drag",
        "scroll",
        "hover",
        "type_text",
        "paste_image",
        "conditional_hotkey",
    )


def _use_real_vlm_locator(state: AgentState, step: PlanStep) -> bool:
    runtime = state.runtime
    if runtime is None:
        return False
    if not runtime.real_desktop_execution or runtime.mock_verification:
        return False
    if not _needs_visual_location(step):
        return False
    return bool(step.metadata.get("force_vlm_locator"))


def _locate_open_chat(state: AgentState, step: PlanStep) -> LocatedTarget:
    deterministic = locate_lark_target(state.before_observation, step)
    if deterministic is not None and (
        deterministic.recommended_action != "continue"
        or deterministic.confidence >= 0.85
        or deterministic.source in {"ocr", "hybrid"}
    ):
        return deterministic

    semantic = vlm.locate_element(state.before_observation, step)
    if semantic.warnings or semantic.recommended_action != "continue" or semantic.confidence < 0.45:
        return semantic
    semantic = _maybe_correct_scaled_vlm_target(state.before_observation, semantic)

    # 提取搜索目标文本（去掉前缀，只保留要搜索的名称）
    if step.id == "select_mention_candidate":
        target_text = step.metadata.get("mention_user", "") or step.metadata.get("target", "")
    elif step.id == "select_group_member":
        target_text = step.metadata.get("member", "") or step.metadata.get("target", "")
    else:
        target_text = step.metadata.get("target", "") or step.metadata.get("member") or step.metadata.get("mention_user", "")
    if not target_text:
        # 从target_description中提取目标名称
        if "for " in step.target_description:
            target_text = step.target_description.split("for ")[-1].strip()

    screenshot_path = state.before_observation.screenshot_path
    cv_candidate = deterministic or locate_lark_target(state.before_observation, step)
    size = _screen_size(state.before_observation)
    broad_roi = None
    if size:
        width, height = size
        broad_roi = BoundingBox(
            x1=max(0, round(width * 0.18)),
            y1=max(0, round(height * 0.44)),
            x2=min(width, round(width * 0.62)),
            y2=min(height, round(height * 0.78)),
        )

    # Prefer a direct exact-name OCR row anywhere in the visible result list.
    if target_text and broad_roi:
        located = _find_exact_ocr_target_row(screenshot_path, target_text, broad_roi)
        if located is not None:
            located.target_description = step.target_description
            located.metadata["semantic_vlm"] = {
                "bbox": semantic.bbox.model_dump() if semantic.bbox else None,
                "center": semantic.center,
                "confidence": semantic.confidence,
                "reason": semantic.reason,
                "metadata": semantic.metadata,
            }
            return located

    # 第一层：VLM识别区域OCR校验。VLM 负责缩小候选区，OCR 必须确认文字。
    if semantic.bbox and target_text:
        located = _ocr_confirmed_target(
            screenshot_path,
            target_text,
            semantic.bbox,
            "VLM candidate bbox",
            semantic=semantic,
            threshold=0.52,
        )
        if located is not None:
            return located

    # 第二层：布局候选区 OCR 校验。只有目标文字在候选区出现才允许点击。
    if cv_candidate and cv_candidate.bbox and target_text:
        located = _ocr_confirmed_target(
            screenshot_path,
            target_text,
            cv_candidate.bbox,
            "window-relative search result bbox",
            semantic=semantic,
            threshold=0.52,
        )
        if located is not None:
            located.confidence = min(0.97, max(located.confidence, cv_candidate.confidence, semantic.confidence))
            return located

    # 第三层：如果 VLM 坐标落在布局候选结果行内，但 OCR 没确认，仍然 fail-safe。
    if cv_candidate and _point_in_bbox(semantic.center, cv_candidate.bbox):
        semantic.warnings.append(
            f"VLM coordinate is inside the first result row, but OCR did not confirm target {target_text!r}; blocking click to avoid opening the wrong chat."
        )
    else:
        semantic.warnings.append(
            f"OCR did not confirm target {target_text!r} in VLM/CV candidate regions; blocking click to avoid opening the wrong chat."
        )
    semantic.recommended_action = "abort"
    semantic.confidence = min(semantic.confidence, 0.35)
    semantic.metadata["cv_candidate"] = cv_candidate.model_dump() if cv_candidate else None
    semantic.metadata["ocr_required_for_click"] = True
    return semantic


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
    explicit = _explicit_step_target(step)
    dry_run_target = _dry_run_simulated_target(state, step)
    if explicit is not None:
        located = explicit
    elif dry_run_target is not None:
        located = dry_run_target
    elif state.runtime and state.runtime.real_desktop_execution and step.id in {"open_chat", "select_group_member", "select_mention_candidate"}:
        located = _locate_open_chat(state, step)
    elif step.action in {"conditional_click", "conditional_hotkey"}:
        located = locate_lark_target(state.before_observation, step) or LocatedTarget(
            step_id=step.id,
            target_description=step.target_description,
            source="none",
            confidence=0.0,
            reason="Optional conditional target was not visible in the current screenshot.",
            recommended_action="skip",
            metadata={"strategy": str(step.metadata.get("locator_strategy") or "")},
        )
    elif _use_real_vlm_locator(state, step):
        # In real desktop execution, do not let layout heuristics invent a
        # click target. If VLM cannot see the target, fail safely before click.
        located = vlm.locate_element(state.before_observation, step)
    else:
        located = locate_lark_target(state.before_observation, step) or _static_safe_smoke_target(step, state.before_observation)
        if located is None and step.metadata.get("require_lark_locator"):
            located = LocatedTarget(
                step_id=step.id,
                target_description=step.target_description,
                source="none",
                confidence=0.0,
                reason="Required Feishu OCR/layout locator did not confirm this target; VLM fallback is disabled for this step.",
                recommended_action="abort",
                metadata={"strategy": str(step.metadata.get("locator_strategy") or ""), "require_lark_locator": True},
            )
        if located is None:
            located = vlm.locate_element(state.before_observation, step)
    located = _maybe_correct_scaled_vlm_target(state.before_observation, located)
    located = _add_locator_safety(step, state.before_observation, located)
    if step.action in {"conditional_click", "conditional_hotkey"} and located.confidence <= 0:
        located.recommended_action = "skip"
        located.reason = located.reason or "Conditional target was not visible; skip the optional recovery action."
    state.last_located_target = located
    logger.log(state, "locate", "Target located", step_id=step.id, located=located.model_dump())
    if (
        step.action in ("click", "double_click", "right_click", "drag")
        and located.confidence <= 0
        and not located.warnings
    ):
        state.status = "fail"
        state.failure_category = "location_failed"
        state.error = f"Could not locate target for step {step.id}: {step.target_description}"
    return state
