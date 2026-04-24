import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict


def _strip_quotes(value: str) -> str:
    raw = value.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    return raw


def _load_env_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip().lstrip("\ufeff")
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            continue
        # Shell environment variables have priority over file defaults.
        os.environ.setdefault(key, _strip_quotes(value))


def _load_default_env() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    configured = os.getenv("CUA_LARK_ENV_FILE")
    env_path = Path(configured) if configured else backend_root / ".env"
    _load_env_file(env_path)


_load_default_env()


class Settings(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    app_name: str = "CUA-Lark Backend"
    environment: str = os.getenv("CUA_LARK_ENV", "local")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "")
    openai_model_text: str = os.getenv("OPENAI_MODEL_TEXT", "qwen-plus")
    openai_model_vision: str = os.getenv("OPENAI_MODEL_VISION", "qwen-vl-max")
    model_provider: str = os.getenv("CUA_LARK_MODEL_PROVIDER", "auto")
    artifact_root: str = os.getenv("CUA_LARK_ARTIFACT_ROOT", "./runs")
    screenshot_dir: str = os.getenv("SCREENSHOT_DIR", "./runs/screenshots")
    report_dir: str = os.getenv("CUA_LARK_REPORT_DIR", "./runs/reports")
    monitor_index: int = int(os.getenv("CUA_LARK_MONITOR_INDEX", "1"))
    max_total_steps: int = int(os.getenv("MAX_TOTAL_STEPS", "40"))
    max_retry_per_subtask: int = int(os.getenv("MAX_RETRY_PER_SUBTASK", "2"))
    max_replans: int = int(os.getenv("CUA_LARK_MAX_REPLANS", "2"))
    wait_after_action_seconds: float = float(os.getenv("CUA_LARK_WAIT_AFTER_ACTION_SECONDS", "0.8"))
    dry_run: bool = os.getenv("DRY_RUN", "true").lower() == "true"
    step_by_step: bool = os.getenv("CUA_LARK_STEP_BY_STEP", "false").lower() == "true"
    auto_debug: bool = os.getenv("CUA_LARK_AUTO_DEBUG", "false").lower() == "true"
    abort_file: str = os.getenv("CUA_LARK_ABORT_FILE", "./runs/ABORT")
    use_mock_when_no_key: bool = os.getenv("CUA_LARK_USE_MOCK_WHEN_NO_KEY", "true").lower() == "true"
    allow_placeholder_screenshot: bool = os.getenv("CUA_LARK_PLACEHOLDER_SCREENSHOT", "true").lower() == "true"
    allow_unhealthy_screenshot: bool = os.getenv("CUA_LARK_ALLOW_UNHEALTHY_SCREENSHOT", "false").lower() == "true"
    allow_mock_real_execution: bool = os.getenv("CUA_LARK_ALLOW_MOCK_REAL_EXECUTION", "false").lower() == "true"
    auto_select_healthy_monitor: bool = os.getenv("CUA_LARK_AUTO_SELECT_HEALTHY_MONITOR", "true").lower() == "true"


settings = Settings()
