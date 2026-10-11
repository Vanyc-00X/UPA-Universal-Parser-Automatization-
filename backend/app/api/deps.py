"""Вспомогательные функции API: отслеживание времени старта, проверки подсистем."""

from __future__ import annotations

import platform
import time
from typing import Any

from app.core.config import Settings

_STARTED_AT = time.monotonic()


def uptime_seconds() -> float:
    """Сколько секунд приложение работает."""
    return round(time.monotonic() - _STARTED_AT, 3)


def python_version() -> str:
    return platform.python_version()


async def check_database(settings: Settings) -> tuple[str, str | None]:
    """Проверяет доступность БД одним запросом."""
    from sqlalchemy import text

    from app.core.db import get_session_factory

    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        return "ok", None
    except Exception as exc:  # noqa: BLE001 — состояние подсистемы, не ошибка логики
        return "down", str(exc)


async def check_llm(settings: Settings) -> dict[str, Any]:
    """Опрашивает настроенного провайдера ИИ и возвращает его состояние.

    Никогда не поднимает исключение: недоступная модель — это штатное состояние,
    при котором UPA обязан продолжать работать без ИИ.
    """
    from app.analyzer.llm import LLMGateway

    gateway = LLMGateway(settings)
    status = await gateway.status()
    return {
        "provider": status.provider,
        "available": status.available,
        "model": status.model,
        "models": status.models,
        "cloud_fallback_enabled": gateway.settings.llm_cloud_fallback,
        "detail": status.detail,
    }
