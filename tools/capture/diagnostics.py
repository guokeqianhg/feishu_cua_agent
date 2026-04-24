from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

from mss import mss
from PIL import Image, ImageStat

from app.config import settings
from core.schemas import MonitorInfo, ScreenshotAnalysis, ScreenshotDiagnosticReport


POSSIBLE_SCREENSHOT_CAUSES = [
    "Remote desktop or virtual display is returning a protected/blank frame.",
    "The Windows session may be locked or minimized.",
    "Screen capture permission may be blocked by OS or security software.",
    "The selected monitor index may be wrong.",
    "The target application may be on a different display.",
    "GPU/driver acceleration may be preventing normal capture.",
]


def _diagnostic_dir() -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = Path(settings.artifact_root) / "diagnostics" / f"screenshot_{stamp}_{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _monitor_info(index: int, monitor: dict) -> MonitorInfo:
    return MonitorInfo(
        index=index,
        left=int(monitor.get("left", 0)),
        top=int(monitor.get("top", 0)),
        width=int(monitor.get("width", 0)),
        height=int(monitor.get("height", 0)),
    )


def analyze_image(path: str, monitor_index: int) -> ScreenshotAnalysis:
    image = Image.open(path).convert("L")
    stat = ImageStat.Stat(image)
    mean_luma = float(stat.mean[0])
    stdev_luma = float(stat.stddev[0])
    extrema = image.getextrema()
    min_luma = int(extrema[0])
    max_luma = int(extrema[1])
    is_black = mean_luma < 8 and max_luma < 20
    is_near_solid = stdev_luma < 2.5 or (max_luma - min_luma) < 8
    is_suspicious = is_black or is_near_solid
    warning = None
    if is_black:
        warning = "Screenshot is suspicious: it looks black or nearly black."
    elif is_near_solid:
        warning = "Screenshot is suspicious: it looks like a near-solid-color frame."
    return ScreenshotAnalysis(
        path=path,
        monitor_index=monitor_index,
        width=image.width,
        height=image.height,
        mean_luma=round(mean_luma, 2),
        stdev_luma=round(stdev_luma, 2),
        min_luma=min_luma,
        max_luma=max_luma,
        is_suspicious=is_suspicious,
        is_black=is_black,
        is_near_solid=is_near_solid,
        warning=warning,
    )


def run_screenshot_diagnostics(include_all_monitors: bool = True) -> ScreenshotDiagnosticReport:
    artifacts_dir = _diagnostic_dir()
    monitors: list[MonitorInfo] = []
    analyses: list[ScreenshotAnalysis] = []
    warnings: list[str] = []

    try:
        with mss() as sct:
            for index, monitor in enumerate(sct.monitors):
                monitors.append(_monitor_info(index, monitor))

            indices = range(len(sct.monitors)) if include_all_monitors else [settings.monitor_index]
            for index in indices:
                if index < 0 or index >= len(sct.monitors):
                    warnings.append(f"Monitor index {index} is not available.")
                    continue
                try:
                    monitor = sct.monitors[index]
                    shot = sct.grab(monitor)
                    image = Image.frombytes("RGB", shot.size, shot.rgb)
                    path = artifacts_dir / f"monitor_{index}.png"
                    image.save(path)
                    analysis = analyze_image(str(path), index)
                    analyses.append(analysis)
                    if analysis.warning:
                        warnings.append(f"monitor {index}: {analysis.warning}")
                except Exception as exc:
                    warnings.append(f"monitor {index}: capture failed: {exc}")
    except Exception as exc:
        warnings.append(f"mss initialization failed: {exc}")

    healthy = bool(analyses) and any(not item.is_suspicious for item in analyses)
    if not healthy:
        warnings.append("No healthy screenshot was found. Real desktop execution should not continue by default.")

    return ScreenshotDiagnosticReport(
        diagnostic_id=artifacts_dir.name,
        artifacts_dir=str(artifacts_dir),
        monitors=monitors,
        analyses=analyses,
        healthy=healthy,
        warnings=warnings,
        possible_causes=POSSIBLE_SCREENSHOT_CAUSES if warnings else [],
    )


def check_configured_monitor() -> ScreenshotDiagnosticReport:
    return run_screenshot_diagnostics(include_all_monitors=False)
