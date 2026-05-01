from __future__ import annotations

import time
import re
import subprocess
from pathlib import Path

import pyautogui
import pyperclip
from PIL import Image

from app.config import settings
from core.schemas import ActionResult, LocatedTarget, PlanStep
from tools.desktop.window_manager import WindowManager


pyautogui.FAILSAFE = True


class ActionExecutor:
    def __init__(self, dry_run: bool | None = None) -> None:
        self.dry_run = settings.dry_run if dry_run is None else dry_run

    def execute(self, step: PlanStep, target: LocatedTarget | None = None) -> ActionResult:
        try:
            center = self._center(step, target)
            message = self._execute(step, target, center)
            return ActionResult(
                success=True,
                message=message,
                action=step.action,
                dry_run=self.dry_run,
                coordinates=center,
                drag_to=step.drag_to,
                input_text=step.input_text,
                hotkeys=step.hotkeys,
                scroll_amount=step.scroll_amount,
                wait_seconds=step.wait_seconds,
            )
        except Exception as exc:
            return ActionResult(
                success=False,
                message="action execution failed",
                action=step.action,
                dry_run=self.dry_run,
                coordinates=self._center(step, target),
                drag_to=step.drag_to,
                input_text=step.input_text,
                hotkeys=step.hotkeys,
                scroll_amount=step.scroll_amount,
                wait_seconds=step.wait_seconds,
                error_message=str(exc),
            )

    def _execute(self, step: PlanStep, target: LocatedTarget | None, center: tuple[int, int] | None) -> str:
        if self.dry_run:
            return f"[DRY_RUN] {step.action} target={step.target_description or ''} center={center}"

        if step.action == "click":
            self._require_center(center, step)
            pyautogui.moveTo(center[0], center[1], duration=0.15)
            pyautogui.click(center[0], center[1])
            return f"click at {center}"

        if step.action == "hover":
            self._require_center(center, step)
            pyautogui.moveTo(center[0], center[1], duration=0.15)
            time.sleep(step.wait_seconds if step.wait_seconds is not None else 0.4)
            return f"hover at {center}"

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
            if center is not None:
                pyautogui.moveTo(center[0], center[1], duration=0.1)
                pyautogui.click(center[0], center[1])
                time.sleep(0.15)
                if step.metadata.get("double_click_before_type"):
                    pyautogui.doubleClick(center[0], center[1])
                    time.sleep(0.15)
            if step.metadata.get("clear_before_type"):
                pyautogui.hotkey("ctrl", "a")
                time.sleep(0.05)
            text = self._input_text_for_step(step)
            if step.metadata.get("type_via_keyboard"):
                pyautogui.write(text, interval=0.03)
            else:
                pyperclip.copy(text)
                pyautogui.hotkey("ctrl", "v")
            if step.metadata.get("press_enter_after_type"):
                time.sleep(0.1)
                pyautogui.press("enter")
            return f"type_text length={len(text)}"

        if step.action == "paste_image":
            image_path = str(step.metadata.get("image_path") or step.input_text or "").strip()
            if not image_path:
                raise ValueError("paste_image action requires image_path metadata or input_text")
            self._copy_image_to_clipboard(self._resolve_image_path(image_path))
            pyautogui.hotkey("ctrl", "v")
            return f"paste_image path={image_path}"

        if step.action == "hotkey":
            if not step.hotkeys:
                raise ValueError("hotkey action requires hotkeys")
            if len(step.hotkeys) > 1 and all(len(key) > 1 or key in {"esc", "enter", "tab"} for key in step.hotkeys):
                for key in step.hotkeys:
                    pyautogui.press(key)
                    time.sleep(0.15)
                return f"press sequence {' then '.join(step.hotkeys)}"
            pyautogui.hotkey(*step.hotkeys)
            return f"hotkey {'+'.join(step.hotkeys)}"

        if step.action == "conditional_hotkey":
            if not step.hotkeys:
                raise ValueError("conditional_hotkey action requires hotkeys")
            pyautogui.hotkey(*step.hotkeys)
            return f"conditional_hotkey {'+'.join(step.hotkeys)}"

        if step.action == "conditional_click":
            self._require_center(center, step)
            pyautogui.moveTo(center[0], center[1], duration=0.15)
            pyautogui.click(center[0], center[1])
            return f"conditional_click at {center}"

        if step.action == "scroll":
            target_amount = target.metadata.get("scroll_amount") if target else None
            amount = int(target_amount) if target_amount is not None else (step.scroll_amount if step.scroll_amount is not None else -3)
            step.scroll_amount = amount
            if center is not None:
                pyautogui.moveTo(center[0], center[1], duration=0.1)
            pyautogui.scroll(amount)
            return f"scroll {amount}"

        if step.action == "wait":
            seconds = step.wait_seconds if step.wait_seconds is not None else 1.0
            time.sleep(seconds)
            return f"wait {seconds}"

        if step.action == "focus_window":
            if step.metadata.get("focus_vc_meeting"):
                manager = WindowManager()
                if manager.focus_lark_meeting():
                    return "focus Feishu/Lark meeting window"
                raise RuntimeError("Could not focus Feishu/Lark meeting window")
            if step.metadata.get("focus_docs_editor"):
                manager = WindowManager()
                if manager.focus_docs_editor():
                    return "focus Feishu Docs browser editor window"
                raise RuntimeError("Could not focus Feishu Docs browser editor window")
            keywords = step.metadata.get("foreground_window_keywords")
            manager = WindowManager()
            if keywords:
                if step.metadata.get("minimize_lark_before_focus"):
                    manager.minimize_active_window()
                    manager.minimize_lark()
                if manager.focus_window_by_keywords([str(item) for item in keywords]):
                    return f"focus window by title keywords={keywords}"
                raise RuntimeError(f"Could not focus window by title keywords={keywords}")
            if manager.focus_lark():
                return "focus Feishu/Lark window"
            raise RuntimeError("Could not focus Feishu/Lark window")

        if step.action in ("verify", "finish"):
            return f"{step.action} no-op"

        raise ValueError(f"unsupported action: {step.action}")

    @staticmethod
    def _copy_image_to_clipboard(path: Path) -> None:
        path = path.resolve()
        if not path.exists():
            raise FileNotFoundError(f"image file does not exist: {path}")
        image = Image.open(path).convert("RGB")
        try:
            import win32clipboard  # type: ignore[import-not-found]
            import win32con  # type: ignore[import-not-found]
        except Exception as exc:
            image.close()
            ActionExecutor._copy_image_to_clipboard_powershell(path)
            return
        from io import BytesIO

        output = BytesIO()
        try:
            image.save(output, "BMP")
            data = output.getvalue()[14:]
        finally:
            image.close()
            output.close()
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_DIB, data)
        finally:
            win32clipboard.CloseClipboard()

    @staticmethod
    def _copy_image_to_clipboard_powershell(path: Path) -> None:
        quoted = str(path).replace("'", "''")
        command = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "Add-Type -AssemblyName System.Drawing; "
            f"$img=[System.Drawing.Image]::FromFile('{quoted}'); "
            "try { [System.Windows.Forms.Clipboard]::SetImage($img) } finally { $img.Dispose() }"
        )
        completed = subprocess.run(
            [
                "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
                "-NoProfile",
                "-STA",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"PowerShell image clipboard fallback failed: {completed.stderr.strip()}")

    @staticmethod
    def _resolve_image_path(raw_path: str) -> Path:
        path = Path(raw_path)
        if path.is_absolute() or path.exists():
            return path
        backend_root = Path(__file__).resolve().parents[2]
        return backend_root / path

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

    @staticmethod
    def _input_text_for_step(step: PlanStep) -> str:
        if step.input_text is None:
            return ""
        if step.metadata.get("calendar_date_from_relative"):
            match = re.search(r"(\d{4})-(\d{2})-(\d{2})", step.input_text)
            if match:
                return f"{match.group(1)}年{int(match.group(2))}月{int(match.group(3))}日"
        if step.metadata.get("calendar_time_from_text"):
            match = re.search(r"(\d{1,2}):(\d{2})", step.input_text)
            if match:
                return f"{int(match.group(1)):02d}:{match.group(2)}"
        return step.input_text
