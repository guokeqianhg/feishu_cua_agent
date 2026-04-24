from __future__ import annotations

import time

import pyautogui
import pyperclip

from app.config import settings
from core.schemas import ActionResult, LocatedTarget, PlanStep


pyautogui.FAILSAFE = True


class ActionExecutor:
    def __init__(self, dry_run: bool | None = None) -> None:
        self.dry_run = settings.dry_run if dry_run is None else dry_run

    def execute(self, step: PlanStep, target: LocatedTarget | None = None) -> ActionResult:
        try:
            message = self._execute(step, target)
            return ActionResult(success=True, message=message, action=step.action, dry_run=self.dry_run)
        except Exception as exc:
            return ActionResult(
                success=False,
                message="action execution failed",
                action=step.action,
                dry_run=self.dry_run,
                error_message=str(exc),
            )

    def _execute(self, step: PlanStep, target: LocatedTarget | None = None) -> str:
        if self.dry_run:
            return f"[DRY_RUN] {step.action} target={step.target_description or ''}"

        center = self._center(step, target)
        if step.action == "click":
            self._require_center(center, step)
            pyautogui.moveTo(center[0], center[1], duration=0.15)
            pyautogui.click(center[0], center[1])
            return f"click at {center}"

        if step.action == "double_click":
            self._require_center(center, step)
            pyautogui.moveTo(center[0], center[1], duration=0.15)
            pyautogui.doubleClick(center[0], center[1])
            return f"double_click at {center}"

        if step.action == "right_click":
            self._require_center(center, step)
            pyautogui.moveTo(center[0], center[1], duration=0.15)
            pyautogui.rightClick(center[0], center[1])
            return f"right_click at {center}"

        if step.action == "drag":
            self._require_center(center, step)
            if not step.drag_to:
                raise ValueError("drag action requires drag_to")
            pyautogui.moveTo(center[0], center[1], duration=0.15)
            pyautogui.dragTo(step.drag_to[0], step.drag_to[1], duration=0.4, button="left")
            return f"drag from {center} to {step.drag_to}"

        if step.action == "type_text":
            if step.input_text is None:
                raise ValueError("type_text action requires input_text")
            pyperclip.copy(step.input_text)
            pyautogui.hotkey("ctrl", "v")
            return f"type_text length={len(step.input_text)}"

        if step.action == "hotkey":
            if not step.hotkeys:
                raise ValueError("hotkey action requires hotkeys")
            pyautogui.hotkey(*step.hotkeys)
            return f"hotkey {'+'.join(step.hotkeys)}"

        if step.action == "scroll":
            amount = step.scroll_amount if step.scroll_amount is not None else -3
            pyautogui.scroll(amount)
            return f"scroll {amount}"

        if step.action == "wait":
            seconds = step.wait_seconds if step.wait_seconds is not None else 1.0
            time.sleep(seconds)
            return f"wait {seconds}"

        if step.action in ("verify", "finish"):
            return f"{step.action} no-op"

        raise ValueError(f"unsupported action: {step.action}")

    @staticmethod
    def _center(step: PlanStep, target: LocatedTarget | None) -> tuple[int, int] | None:
        if step.coordinates:
            return step.coordinates
        if step.bbox:
            return step.bbox.center()
        if target and target.center:
            return target.center
        if target and target.bbox:
            return target.bbox.center()
        return None

    @staticmethod
    def _require_center(center: tuple[int, int] | None, step: PlanStep) -> None:
        if center is None:
            raise ValueError(f"{step.action} requires a located target")
