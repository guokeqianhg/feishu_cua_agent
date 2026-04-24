from __future__ import annotations

from app.config import settings
from core.schemas import RuntimeContext


def effective_model_provider() -> str:
    provider = settings.model_provider.lower()
    if provider == "mock":
        return "mock"
    if provider == "auto" and (not settings.openai_api_key) and settings.use_mock_when_no_key:
        return "mock"
    return provider


def runtime_context(dry_run_override: bool | None = None) -> RuntimeContext:
    dry_run = settings.dry_run if dry_run_override is None else dry_run_override
    provider = effective_model_provider()
    return RuntimeContext(
        model_provider=settings.model_provider,
        effective_model_provider=provider,
        dry_run=dry_run,
        placeholder_screenshot=settings.allow_placeholder_screenshot,
        real_desktop_execution=not dry_run,
        mock_verification=(provider == "mock"),
        step_by_step=settings.step_by_step,
        abort_file=settings.abort_file,
        allow_unhealthy_screenshot=settings.allow_unhealthy_screenshot,
        monitor_index=settings.monitor_index,
    )


def simulation_warning(context: RuntimeContext) -> str | None:
    if context.dry_run or context.mock_verification:
        return "这是模拟验证，不代表真实飞书桌面操作成功。"
    return None
