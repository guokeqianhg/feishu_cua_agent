from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from core.schemas import TestCase


def load_case(path: str) -> TestCase:
    payload: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return TestCase.model_validate(payload)

