"""Проверка и подтягивание локальной модели Ollama."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)


async def ensure_ollama_model(
    settings: Settings,
    *,
    pull: bool = False,
    timeout_s: float = 600.0,
) -> dict[str, Any]:
    """Проверяет Ollama и при необходимости запускает ``pull`` модели.

    Возвращает структуру, совместимую с :func:`app.api.deps.check_llm`, плюс поля
    ``pulled`` / ``action``. Никогда не бросает наружу сетевые ошибки — только
    описывает состояние: UPA обязана работать без ИИ.
    """
    result: dict[str, Any] = {
        "provider": settings.llm_provider,
        "available": False,
        "model": settings.ollama_model if settings.llm_provider == "ollama" else None,
        "models": [],
        "cloud_fallback_enabled": settings.llm_cloud_fallback,
        "detail": None,
        "pulled": False,
        "action": "none",
    }

    if settings.llm_provider == "none":
        result["detail"] = "ИИ отключён в настройках — работайте вручную"
        result["action"] = "disabled"
        return result

    if settings.llm_provider != "ollama":
        result["detail"] = f"Провайдер {settings.llm_provider} ещё не поддержан"
        result["action"] = "unsupported"
        return result

    base = settings.ollama_base_url.rstrip("/")
    wanted = settings.ollama_model

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            tags = await client.get(f"{base}/api/tags")
            tags.raise_for_status()
            payload = tags.json()
    except Exception as exc:  # noqa: BLE001
        result["detail"] = (
            f"Ollama недоступна ({type(exc).__name__}). "
            "Установите Ollama и запустите её, либо продолжайте без ИИ."
        )
        result["action"] = "start_ollama"
        return result

    models = [m.get("name", "") for m in payload.get("models", []) if m.get("name")]
    result["models"] = sorted(models)
    result["available"] = True
    result["model"] = wanted

    if wanted in models or any(name.startswith(f"{wanted}:") for name in models):
        result["detail"] = f"Модель {wanted} готова"
        result["action"] = "ready"
        return result

    if not pull:
        result["detail"] = (
            f"Модель {wanted} не найдена. Запросите pull или выполните: ollama pull {wanted}"
        )
        result["action"] = "needs_pull"
        # Ollama жива, но нужной модели нет — available остаётся True (сервис доступен).
        return result

    log.info("llm.pull_started", model=wanted)
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(f"{base}/api/pull", json={"name": wanted, "stream": False})
            response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        result["detail"] = f"Не удалось загрузить модель {wanted}: {type(exc).__name__}: {exc}"
        result["action"] = "pull_failed"
        return result

    # Повторно читаем список моделей.
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            tags = await client.get(f"{base}/api/tags")
            tags.raise_for_status()
            models = [
                m.get("name", "") for m in tags.json().get("models", []) if m.get("name")
            ]
    except Exception:  # noqa: BLE001
        models = list(result["models"])

    result["models"] = sorted(models)
    result["pulled"] = True
    if wanted in models or any(name.startswith(f"{wanted}:") for name in models):
        result["detail"] = f"Модель {wanted} загружена"
        result["action"] = "pulled"
    else:
        result["detail"] = f"Pull завершён, но модель {wanted} не появилась в списке"
        result["action"] = "pull_uncertain"
    log.info("llm.pull_finished", model=wanted, action=result["action"])
    return result
