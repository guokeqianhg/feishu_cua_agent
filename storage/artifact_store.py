from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from app.config import settings


class ArtifactStore:
    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or settings.artifact_root)

    def create_run_dir(self, run_id: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = self.root / "reports" / f"run_{stamp}_{run_id[:8]}"
        (run_dir / "screenshots").mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        return run_dir

    @staticmethod
    def screenshot_path(run_dir: str | os.PathLike[str], name: str) -> Path:
        return Path(run_dir) / "screenshots" / f"{name}.png"

    @staticmethod
    def artifact_path(run_dir: str | os.PathLike[str], name: str) -> Path:
        return Path(run_dir) / "artifacts" / name

