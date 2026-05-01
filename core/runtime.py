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
        auto_debug=settings.auto_debug,
        abort_file=settings.abort_file,
        allow_unhealthy_screenshot=settings.allow_unhealthy_screenshot,
        allow_mock_real_execution=settings.allow_mock_real_execution,
        allow_send_message=settings.allow_send_message,
        allowed_im_target=settings.allowed_im_target or None,
        allow_send_image=settings.allow_send_image,
        allow_create_group=settings.allow_create_group,
        allow_emoji_reaction=settings.allow_emoji_reaction,
        allowed_group_member=settings.allowed_group_member or None,
        allow_doc_create=settings.allow_doc_create,
        allow_calendar_create=settings.allow_calendar_create,
        allow_calendar_invite=settings.allow_calendar_invite,
        allow_vc_start=settings.allow_vc_start,
        allow_vc_join=settings.allow_vc_join,
        allow_vc_device_toggle=settings.allow_vc_device_toggle,
        monitor_index=settings.monitor_index,
    )


def simulation_warning(context: RuntimeContext) -> str | None:
    if context.dry_run or context.mock_verification:
        return "这是模拟验证，不代表真实飞书桌面操作成功。"
    return None


def mock_real_execution_block_reason(context: RuntimeContext) -> str | None:
    if context.dry_run:
        return None
    if context.effective_model_provider != "mock":
        return None
    if settings.allow_mock_real_execution:
        return None
    return (
        "DRY_RUN=false，但 effective_model_provider=mock。为了避免模型失败回退到 mock 后仍继续真实点击，"
        "当前已默认阻止真实桌面执行。请配置真实模型，或在确认风险后显式设置 "
        "CUA_LARK_ALLOW_MOCK_REAL_EXECUTION=true。"
    )
