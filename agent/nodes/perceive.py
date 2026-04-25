from __future__ import annotations

from pathlib import Path

from PIL import Image

from agent.state import AgentState
from storage.run_logger import RunLogger
from tools.desktop.window_manager import WindowManager
from tools.vision.ocr import OCRClient
from tools.vision.vlm_client import build_vlm_client
from verification.registry import local_observe


logger = RunLogger()
ocr = OCRClient()
vlm = build_vlm_client()
window = WindowManager()


def _latest_screenshot(state: AgentState, suffix: str) -> str:
    screenshots = sorted(Path(state.artifacts_dir, "screenshots").glob(f"*{suffix}*.png"))
    if not screenshots:
        screenshots = sorted(Path(state.artifacts_dir, "screenshots").glob("*.png"))
    if not screenshots:
        raise ValueError("No screenshot found for observation.")
    return str(screenshots[-1])


def _observe(state: AgentState, screenshot_path: str):
    image = Image.open(screenshot_path)
    raw_text = ocr.extract_text(image)
    window_title = window.get_active_window_title()
    observation = local_observe(state.test_case, screenshot_path, raw_text, window_title)
    if observation is None:
        observation = vlm.describe_screen(screenshot_path, raw_text)
        observation.window_title = window_title
    logger.log(
        state,
        "perceive",
        "Observation completed",
        screenshot_path=screenshot_path,
        page_type=observation.page_type,
        elements=len(observation.elements),
    )
    return observation


def observe_initial_node(state: AgentState) -> AgentState:
    state.initial_observation = _observe(state, _latest_screenshot(state, "initial"))
    return state


def observe_before_node(state: AgentState) -> AgentState:
    state.before_observation = _observe(state, _latest_screenshot(state, "before"))
    return state


def observe_after_node(state: AgentState) -> AgentState:
    state.after_observation = _observe(state, _latest_screenshot(state, "after"))
    state.final_observation = state.after_observation
    return state
