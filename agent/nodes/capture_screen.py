from __future__ import annotations

from agent.state import AgentState
from storage.artifact_store import ArtifactStore
from storage.run_logger import RunLogger
from tools.capture.diagnostics import analyze_image
from tools.capture.mss_backend import MSSCaptureBackend
from tools.desktop.window_manager import WindowManager


logger = RunLogger()
capture_backend = MSSCaptureBackend()
window = WindowManager()


def _capture(state: AgentState, name: str) -> str:
    focused = window.focus_lark()
    active_title = window.get_active_window_title()
    if not focused:
        warning = f"Window focus warning: could not confirm Feishu/Lark is foreground. active_window={active_title!r}"
        if warning not in state.warnings:
            state.warnings.append(warning)
    path = ArtifactStore.screenshot_path(state.artifacts_dir, name)
    image = capture_backend.capture()
    image.save(path)
    analysis = analyze_image(str(path), monitor_index=-1)
    if capture_backend.last_warning:
        warning = f"Screenshot warning: {capture_backend.last_warning} path={path}"
        if warning not in state.warnings:
            state.warnings.append(warning)
    if capture_backend.last_backend == "placeholder":
        warning = f"Screenshot warning: placeholder screenshot was used path={path}"
        if warning not in state.warnings:
            state.warnings.append(warning)
    if analysis.is_suspicious:
        warning = f"Screenshot warning: {analysis.warning} path={path}"
        if warning not in state.warnings:
            state.warnings.append(warning)
    logger.log(
        state,
        "capture_screen",
        "Screenshot captured",
        path=str(path),
        capture_backend=capture_backend.last_backend,
        monitor_index=capture_backend.last_monitor_index,
        warning=capture_backend.last_warning,
        focused_lark=focused,
        active_window_title=active_title,
    )
    return str(path)


def capture_initial_node(state: AgentState) -> AgentState:
    _capture(state, "initial")
    return state


def capture_before_node(state: AgentState) -> AgentState:
    step = state.current_step()
    step_name = step.id if step else f"step_{state.current_step_idx + 1:03d}"
    _capture(state, f"{state.current_step_idx + 1:03d}_{step_name}_before_a{state.current_attempt}")
    return state


def capture_after_node(state: AgentState) -> AgentState:
    step = state.current_step()
    step_name = step.id if step else f"step_{state.current_step_idx + 1:03d}"
    _capture(state, f"{state.current_step_idx + 1:03d}_{step_name}_after_a{state.current_attempt}")
    return state
