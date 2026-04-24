from __future__ import annotations

from agent.state import AgentState
from storage.artifact_store import ArtifactStore
from storage.run_logger import RunLogger
from tools.capture.mss_backend import MSSCaptureBackend
from tools.desktop.window_manager import WindowManager


logger = RunLogger()
capture_backend = MSSCaptureBackend()
window = WindowManager()


def _capture(state: AgentState, name: str) -> str:
    window.focus_lark()
    path = ArtifactStore.screenshot_path(state.artifacts_dir, name)
    image = capture_backend.capture()
    image.save(path)
    logger.log(state, "capture_screen", "Screenshot captured", path=str(path))
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
