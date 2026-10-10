"""Вспомогательные функции API: отслеживание времени старта, проверки подсистем."""

from __future__ import annotations

import platform
import time
from typing import Any

import httpx

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
    """Опрашивает локальную модель (Ollama) и возвращает её состояние.

    Никогда не поднимает исключение: недоступная модель — это штатное состояние,
    при котором UPA обязан продолжать работать без ИИ.
    """
    result: dict[str, Any] = {
        "provider": settings.llm_provider,
        "available": False,
        "model": None,
        "models": [],
        "cloud_fallback_enabled": settings.llm_cloud_fallback,
        "detail": None,
    }

    if settings.llm_provider == "none":
        result["detail"] = "ИИ отключён в настройках"
        return result

    if settings.llm_provider != "ollama":
        result["detail"] = f"Провайдер {settings.llm_provider} ещё не поддержан"
        return result

    url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001 — внешний сервис
        result["detail"] = f"Ollama недоступна: {type(exc).__name__}"
        return result

    models = [m.get("name", "") for m in payload.get("models", []) if m.get("name")]
    result["models"] = sorted(models)
    result["available"] = True
    # Модель считается выбранной, если она есть в списке либо список пуст.
    wanted = settings.ollama_model
    result["model"] = wanted if wanted in models or not models else wanted
    if models and wanted not in models:
        result["detail"] = f"Модель {wanted} не найдена локально"
    return result
