"""Ретраи с backoff и классификация сетевых сбоев."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

FailureKind = Literal[
    "selector_broken",
    "site_down",
    "timeout",
    "blocked",
    "captcha",
    "unknown",
]

T = TypeVar("T")


@dataclass
class RetryDecision:
    """Решение: повторять ли попытку и почему."""

    kind: FailureKind
    retryable: bool
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "retryable": self.retryable,
            "message": self.message,
        }


def classify_fetch_error(message: str | None) -> RetryDecision:
    """Отличает «сайт лёг» от «селектор сломался» и прочих причин."""
    text = (message or "").lower()
    if not text:
        return RetryDecision("unknown", True, "неизвестная ошибка сети")

    if any(token in text for token in ("captcha", "hcaptcha", "recaptcha", "cf-challenge")):
        return RetryDecision("captcha", False, "обнаружена капча — нужно ручное вмешательство")
    if any(token in text for token in ("403", "401", "blocked", "access denied", "forbidden")):
        return RetryDecision("blocked", False, "доступ заблокирован сайтом")
    if any(token in text for token in ("timeout", "timed out", "deadline")):
        return RetryDecision("timeout", True, "таймаут загрузки страницы")
    if any(
        token in text
        for token in ("connection", "connect", "dns", "refused", "reset", "502", "503", "504")
    ):
        return RetryDecision("site_down", True, "сайт недоступен или перегружен")
    if any(token in text for token in ("selector", "селектор", "не найден", "not found")):
        return RetryDecision("selector_broken", False, "похоже на сломанный селектор")
    return RetryDecision("unknown", True, message or "ошибка загрузки")


async def with_retries(
    operation: Callable[[], Awaitable[tuple[T | None, str | None]]],
    *,
    max_attempts: int = 3,
    backoff_ms: int = 500,
    on_retry: Callable[[int, RetryDecision], None] | None = None,
) -> tuple[T | None, str | None, list[dict[str, Any]]]:
    """Повторяет операцию с экспоненциальной паузой.

    Возвращает результат, последнюю ошибку и журнал попыток.
    """
    attempts: list[dict[str, Any]] = []
    last_error: str | None = None
    limit = max(1, max_attempts)

    for attempt in range(1, limit + 1):
        value, error = await operation()
        if error is None and value is not None:
            attempts.append({"attempt": attempt, "ok": True})
            return value, None, attempts

        last_error = error or "пустой ответ"
        decision = classify_fetch_error(last_error)
        attempts.append(
            {
                "attempt": attempt,
                "ok": False,
                "error": last_error,
                **decision.as_dict(),
            }
        )
        if not decision.retryable or attempt >= limit:
            break
        if on_retry is not None:
            on_retry(attempt, decision)
        await asyncio.sleep((backoff_ms * (2 ** (attempt - 1))) / 1000)

    return None, last_error, attempts
