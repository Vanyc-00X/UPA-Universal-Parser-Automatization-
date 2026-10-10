"""Шлюз к ИИ-модели: локальная Ollama, облачный фолбэк, отказ без ИИ.

Ключевое требование: приложение обязано работать без модели. Поэтому шлюз
никогда не бросает исключение наружу из :meth:`enrich` — если модель недоступна
или ответ бессмысленный, анализ остаётся детерминированным, а в отчёт попадает
пометка. ИИ здесь усилитель, а не зависимость.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.analyzer.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_user_prompt,
    response_schema_json,
)
from app.analyzer.roles import Role
from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Сколько элементов отправляем модели за один раз. Больше — точнее контекст, но
# медленнее; меньше — быстрее, но модель теряет общую картину.
BATCH_SIZE = 40
# Во сколько раз можно «расширить» бюджет токенов под ответ модели.
MAX_RESPONSE_TOKENS = 2000


@dataclass
class LLMStatus:
    """Состояние модели."""

    provider: str
    available: bool
    model: str | None = None
    detail: str | None = None
    models: list[str] = field(default_factory=list)


@dataclass
class LLMEnrichment:
    """Результат обогащения карты элементов моделью."""

    used: bool = False
    provider: str | None = None
    model: str | None = None
    prompt_version: str = PROMPT_VERSION
    summary: str | None = None
    roles: dict[int, dict[str, Any]] = field(default_factory=dict)
    detail: str | None = None
    latency_ms: int = 0
    from_cache: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "used": self.used,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "summary": self.summary,
            "roles_described": len(self.roles),
            "detail": self.detail,
            "latency_ms": self.latency_ms,
            "from_cache": self.from_cache,
        }


def _cache_key(provider: str, model: str, prompt: str) -> str:
    """Ключ кэша ответа модели."""
    digest = hashlib.sha256(f"{provider}|{model}|{PROMPT_VERSION}|{prompt}".encode())
    return digest.hexdigest()[:32]


def extract_json(text: str) -> dict[str, Any] | None:
    """Достаёт JSON из ответа модели.

    Локальные модели любят обернуть ответ в ```json … ``` или добавить фразу до
    и после. Поэтому сначала пробуем честный разбор, затем ищем первую
    сбалансированную фигурную скобку.
    """
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start == -1:
        return None
    depth = 0
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(cleaned[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


KNOWN_ROLES = {role.value for role in Role}


def validate_response(
    payload: dict[str, Any], valid_indexes: set[int]
) -> tuple[str | None, dict[int, dict[str, Any]], list[str]]:
    """Проверяет ответ модели и отбрасывает бессмысленные части.

    Возвращает описание страницы, разобранные роли и список замечаний. Модель
    может выдумать несуществующий номер элемента или роль — такое отбрасывается,
    а не попадает в карту.
    """
    problems: list[str] = []
    summary = payload.get("summary")
    if summary is not None and not isinstance(summary, str):
        problems.append("поле summary не строка")
        summary = None

    roles: dict[int, dict[str, Any]] = {}
    items = payload.get("items")
    if not isinstance(items, list):
        problems.append("поле items не список")
        return summary, roles, problems

    for item in items:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int) or index not in valid_indexes:
            problems.append(f"неизвестный номер элемента: {index!r}")
            continue
        role = item.get("role")
        if not isinstance(role, str) or role not in KNOWN_ROLES:
            problems.append(f"неизвестная роль у элемента {index}: {role!r}")
            continue
        description = item.get("description")
        confidence = item.get("confidence")
        roles[index] = {
            "role": role,
            "description": description if isinstance(description, str) else None,
            "confidence": (
                float(confidence)
                if isinstance(confidence, (int, float)) and 0 <= float(confidence) <= 1
                else None
            ),
        }
    return summary, roles, problems


class LLMGateway:
    """Единая точка общения с моделью."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache: dict[str, dict[str, Any]] = {}
        self._last_from_cache = False

    # --- Состояние ----------------------------------------------------------

    async def status(self) -> LLMStatus:
        """Проверяет доступность провайдера, не поднимая исключений."""
        if self.settings.llm_provider == "none":
            return LLMStatus(provider="none", available=False, detail="ИИ отключён в настройках")

        if self.settings.llm_provider == "ollama":
            url = f"{self.settings.ollama_base_url.rstrip('/')}/api/tags"
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    payload = response.json()
            except Exception as exc:  # noqa: BLE001 — внешний сервис
                return LLMStatus(
                    provider="ollama",
                    available=False,
                    model=self.settings.ollama_model,
                    detail=f"Ollama недоступна: {type(exc).__name__}",
                )
            models = [
                item.get("name", "") for item in payload.get("models", []) if item.get("name")
            ]
            wanted = self.settings.ollama_model
            available = bool(models)
            detail = None
            if models and wanted not in models:
                detail = f"Модель {wanted} не найдена локально"
            return LLMStatus(
                provider="ollama",
                available=available,
                model=wanted,
                detail=detail,
                models=sorted(models),
            )

        if self.settings.llm_provider == "openai_compatible":
            if not self.settings.llm_cloud_base_url or not self.settings.llm_cloud_api_key:
                return LLMStatus(
                    provider="openai_compatible",
                    available=False,
                    detail="Не заданы адрес и ключ облачного провайдера",
                )
            return LLMStatus(
                provider="openai_compatible",
                available=True,
                model=self.settings.llm_cloud_model or None,
            )

        return LLMStatus(
            provider=self.settings.llm_provider, available=False, detail="неизвестный провайдер"
        )

    # --- Работа с моделью ---------------------------------------------------

    async def complete(
        self, system: str, user: str, *, json_mode: bool = True
    ) -> tuple[str | None, str | None]:
        """Запрос к модели.

        Возвращает ``(текст ответа, описание ошибки)``. Один из элементов всегда
        ``None``. Ответы кэшируются по хэшу входа: повторный анализ той же
        страницы не должен снова занимать локальную модель.
        """
        provider = self.settings.llm_provider
        if provider == "none":
            return None, "ИИ отключён в настройках"

        prompt_hash = _cache_key(provider, self._model_name(), user)
        cached = self._cache.get(prompt_hash)
        if cached is not None:
            self._last_from_cache = True
            return cached.get("text"), None

        try:
            if provider == "ollama":
                text = await self._complete_ollama(system, user, json_mode=json_mode)
            elif provider == "openai_compatible":
                text = await self._complete_openai(system, user, json_mode=json_mode)
            else:
                return None, f"провайдер {provider} не поддержан"
        except httpx.TimeoutException:
            return None, "модель не ответила за отведённое время"
        except Exception as exc:  # noqa: BLE001 — любая ошибка внешнего сервиса
            log.warning(
                "llm.request_failed", provider=provider, error=f"{type(exc).__name__}: {exc}"
            )
            return None, f"{type(exc).__name__}: {exc}"

        self._cache[prompt_hash] = {"text": text}
        self._last_from_cache = False
        return text, None

    def _model_name(self) -> str:
        if self.settings.llm_provider == "ollama":
            return self.settings.ollama_model
        return self.settings.llm_cloud_model or "unknown"

    async def _complete_ollama(self, system: str, user: str, *, json_mode: bool) -> str | None:
        url = f"{self.settings.ollama_base_url.rstrip('/')}/api/chat"
        payload: dict[str, Any] = {
            "model": self.settings.ollama_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": 0.1, "num_predict": MAX_RESPONSE_TOKENS},
        }
        if json_mode:
            # Ограничиваем вывод схемой: модель физически не сможет ответить прозой.
            payload["format"] = json.loads(response_schema_json())

        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_s) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        message = data.get("message") or {}
        content = message.get("content")
        return content if isinstance(content, str) else None

    async def _complete_openai(self, system: str, user: str, *, json_mode: bool) -> str | None:
        url = f"{self.settings.llm_cloud_base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.settings.llm_cloud_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": MAX_RESPONSE_TOKENS,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {"Authorization": f"Bearer {self.settings.llm_cloud_api_key}"}
        async with httpx.AsyncClient(timeout=self.settings.llm_timeout_s) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        choices = data.get("choices") or []
        if not choices:
            return None
        content = (choices[0].get("message") or {}).get("content")
        return content if isinstance(content, str) else None

    # --- Обогащение карты элементов ----------------------------------------

    async def enrich(
        self,
        *,
        title: str | None,
        lang: str | None,
        url: str,
        repeats: list[dict[str, Any]],
        elements: list[dict[str, Any]],
    ) -> LLMEnrichment:
        """Просит модель описать элементы. Никогда не бросает исключение.

        ``elements`` — список словарей с полями ``index``, ``tag``, ``hint``,
        ``text``. Возвращает описания, которые затем накладываются на карту.
        """
        import time

        if self.settings.llm_provider == "none":
            return LLMEnrichment(detail="ИИ отключён в настройках")

        started = time.monotonic()
        result = LLMEnrichment(provider=self.settings.llm_provider, model=self._model_name())

        if not elements:
            result.detail = "нет элементов для описания"
            return result

        valid_indexes = {item["index"] for item in elements}
        user_prompt = build_user_prompt(
            title=title, lang=lang, url=url, repeats=repeats, elements=elements
        )
        text, error = await self.complete(SYSTEM_PROMPT, user_prompt, json_mode=True)
        result.latency_ms = int((time.monotonic() - started) * 1000)
        result.from_cache = self._last_from_cache

        if error:
            result.detail = error
            log.info("llm.unavailable", detail=error, provider=self.settings.llm_provider)
            return result
        if not text:
            result.detail = "модель вернула пустой ответ"
            return result

        payload = extract_json(text)
        if payload is None:
            result.detail = "ответ модели не является JSON"
            log.warning("llm.bad_json", length=len(text))
            return result

        summary, roles, problems = validate_response(payload, valid_indexes)
        if problems:
            log.info("llm.partial_response", problems=problems[:5], count=len(problems))

        if not roles and not summary:
            result.detail = "в ответе модели нет полезных данных"
            return result

        result.used = True
        result.summary = summary
        result.roles = roles
        if problems:
            result.detail = f"отброшено замечаний: {len(problems)}"
        return result
