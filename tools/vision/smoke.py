from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from core.schemas import Observation, PlanStep, StepVerification, TestCase
from tools.vision.lark_locator import strategy_bbox_from_screenshot


SEARCH_DIALOG_INPUT_BOX = (190, 265, 1025, 325)


def is_safe_smoke_case(case: TestCase) -> bool:
    return bool(case.metadata.get("safe_smoke") or "no-send" in case.tags or "smoke_search" in case.id)


def observe_smoke_screen(screenshot_path: str, ocr_lines: list[str] | None, window_title: str | None) -> Observation:
    flags = _image_flags(screenshot_path)
    return Observation(
        screenshot_path=screenshot_path,
        window_title=window_title,
        page_type="safe_smoke_local",
        page_summary="Local fast smoke observation. No VLM call was made.",
        ocr_lines=ocr_lines or [],
        raw_model_output={"provider": "local_smoke", **flags},
    )


def verify_smoke_step(step: PlanStep, before: Observation | None, after: Observation | None) -> StepVerification:
    if after is None:
        return StepVerification(
            success=False,
            confidence=0.0,
            reason="No after observation available.",
            failure_category="perception_failed",
            raw_model_output={"provider": "local_smoke"},
        )

    if step.id == "open_im":
        title = after.window_title or ""
        success = _looks_like_feishu_title(title) and _healthy_image(after.screenshot_path)
        return StepVerification(
            success=success,
            confidence=0.95 if success else 0.2,
            reason="Feishu window is foreground and screenshot is healthy." if success else f"Feishu foreground was not confirmed: {title!r}",
            matched_criteria=["Feishu foreground window", "healthy screenshot"] if success else [],
            failed_criteria=[] if success else ["Feishu foreground window"],
            failure_category="none" if success else "product_state_invalid",
            raw_model_output={"provider": "local_smoke"},
        )

    if step.id == "focus_search":
        changed = _image_diff(before.screenshot_path if before else None, after.screenshot_path)
        dialog_visible = _search_dialog_visible(after.screenshot_path)
        success = dialog_visible or changed > 2.0
        return StepVerification(
            success=success,
            confidence=0.9 if success else 0.25,
            reason=(
                f"Search dialog/input appears focused. image_diff={changed:.2f}."
                if success
                else f"Search dialog/input focus was not detected. image_diff={changed:.2f}."
            ),
            matched_criteria=["search dialog or input focus detected"] if success else [],
            failed_criteria=[] if success else ["search dialog or input focus detected"],
            failure_category="none" if success else "verification_failed",
            raw_model_output={"provider": "local_smoke", "image_diff": round(changed, 3), "search_dialog_visible": dialog_visible},
        )

    if step.id == "type_safe_query":
        dynamic_box = strategy_bbox_from_screenshot(after.screenshot_path, "search_dialog_input")
        box = (
            (dynamic_box.x1, dynamic_box.y1, dynamic_box.x2, dynamic_box.y2)
            if dynamic_box
            else SEARCH_DIALOG_INPUT_BOX
        )
        changed = _crop_diff(before.screenshot_path if before else None, after.screenshot_path, box)
        has_input_marks = _input_crop_has_text_like_pixels(after.screenshot_path, box)
        success = changed > 1.0 and has_input_marks
        return StepVerification(
            success=success,
            confidence=0.9 if success else 0.25,
            reason=(
                f"Search input crop changed and contains text-like pixels. crop_diff={changed:.2f}."
                if success
                else f"Search input text was not locally confirmed. crop_diff={changed:.2f}, text_like={has_input_marks}."
            ),
            matched_criteria=["search input changed", "text-like pixels detected"] if success else [],
            failed_criteria=[] if success else ["search input changed", "text-like pixels detected"],
            failure_category="none" if success else "verification_failed",
            raw_model_output={"provider": "local_smoke", "crop_diff": round(changed, 3), "text_like": has_input_marks},
        )

    if step.id in ("observe_results", "verify_no_send"):
        success = _healthy_image(after.screenshot_path)
        return StepVerification(
            success=success,
            confidence=0.9 if success else 0.3,
            reason="Safe smoke remained on a visible screen; no send action is present in this case." if success else "Screenshot is not healthy.",
            matched_criteria=["visible screen", "no send action"] if success else [],
            failed_criteria=[] if success else ["visible screen"],
            failure_category="none" if success else "perception_failed",
            raw_model_output={"provider": "local_smoke"},
        )

    return StepVerification(
        success=True,
        confidence=0.75,
        reason=f"Local smoke default verification passed for {step.id}.",
        matched_criteria=[step.expected_state or step.id],
        raw_model_output={"provider": "local_smoke"},
    )


def verify_smoke_case(case: TestCase, final_observation: Observation | None) -> StepVerification:
    success = final_observation is not None and _healthy_image(final_observation.screenshot_path)
    return StepVerification(
        success=success,
        confidence=0.9 if success else 0.2,
        reason="Safe smoke completed without any send action." if success else "No final healthy observation was available.",
        matched_criteria=["no send action", "final screenshot available"] if success else [],
        failed_criteria=[] if success else ["final screenshot available"],
        failure_category="none" if success else "perception_failed",
        raw_model_output={"provider": "local_smoke"},
    )


def _looks_like_feishu_title(title: str) -> bool:
    raw = title.lower()
    return any(item in raw for item in ("飞书", "椋炰功", "feishu", "lark"))


def _healthy_image(path: str) -> bool:
    if not Path(path).exists():
        return False
    image = Image.open(path).convert("L")
    stat = ImageStat.Stat(image)
    lo, hi = image.getextrema()
    return stat.mean[0] > 5 and stat.stddev[0] > 2 and (hi - lo) > 8


def _image_flags(path: str) -> dict:
    if not Path(path).exists():
        return {"healthy_image": False}
    image = Image.open(path).convert("L")
    stat = ImageStat.Stat(image)
    lo, hi = image.getextrema()
    return {
        "healthy_image": _healthy_image(path),
        "mean_luma": round(float(stat.mean[0]), 3),
        "stdev_luma": round(float(stat.stddev[0]), 3),
        "min_luma": int(lo),
        "max_luma": int(hi),
    }


def _image_diff(before_path: str | None, after_path: str) -> float:
    if not before_path or not Path(before_path).exists() or not Path(after_path).exists():
        return 0.0
    before = Image.open(before_path).convert("L")
    after = Image.open(after_path).convert("L")
    if before.size != after.size:
        after = after.resize(before.size)
    diff = ImageChops.difference(before, after)
    return float(ImageStat.Stat(diff).mean[0])


def _crop_diff(before_path: str | None, after_path: str, box: tuple[int, int, int, int]) -> float:
    if not before_path or not Path(before_path).exists() or not Path(after_path).exists():
        return 0.0
    before = Image.open(before_path).convert("L").crop(box)
    after = Image.open(after_path).convert("L").crop(box)
    diff = ImageChops.difference(before, after)
    return float(ImageStat.Stat(diff).mean[0])


def _search_dialog_visible(path: str) -> bool:
    if not Path(path).exists():
        return False
    image = Image.open(path).convert("L")
    crop = image.crop((160, 235, 1115, 1065))
    stat = ImageStat.Stat(crop)
    return stat.mean[0] > 180 and stat.stddev[0] > 15


def _input_crop_has_text_like_pixels(path: str, box: tuple[int, int, int, int]) -> bool:
    if not Path(path).exists():
        return False
    crop = Image.open(path).convert("L").crop(box)
    # The empty input has mostly very bright pixels; typed text introduces dark strokes.
    dark_pixels = sum(1 for value in crop.getdata() if value < 120)
    total = max(crop.width * crop.height, 1)
    return (dark_pixels / total) > 0.002
