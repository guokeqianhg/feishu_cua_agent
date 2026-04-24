from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    raw = re.sub(r"^\s*```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```\s*$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    return json.loads(raw)


def extract_json_array(text: str) -> list[Any]:
    raw = (text or "").strip()
    raw = re.sub(r"^\s*```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```\s*$", "", raw)
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("JSON payload is not an array")
    return payload
