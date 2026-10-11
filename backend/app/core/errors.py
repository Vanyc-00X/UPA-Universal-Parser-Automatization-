"""Доменные ошибки и единый формат ответа об ошибке.

Любая ожидаемая проблема приложения выражается наследником :class:`UPAError`.
Обработчик в :mod:`app.api.errors` превращает её в предсказуемый JSON:

.. code-block:: json

    {
      "error": {
        "code": "site_unreachable",
        "message": "Не удалось открыть сайт",
        "details": {"url": "https://example.com"}
      }
    }
"""

from __future__ import annotations

from typing import Any


class UPAError(Exception):
    """Базовая ошибка приложения."""

    code: str = "internal_error"
    http_status: int = 500
    message: str = "Внутренняя ошибка приложения"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        http_status: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or {}
        if http_status is not None:
            self.http_status = http_status
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class ValidationError(UPAError):
    code = "validation_error"
    http_status = 422
    message = "Некорректные данные запроса"


class ModelValidationError(UPAError):
    """Ошибка проверки модели Pydantic — с понятным первым замечанием.

    Используется там, где тело запроса разбирается вложенной моделью: FastAPI
    поднимает ``pydantic.ValidationError``, и без явного обработчика ответ был бы
    невнятным или превращался в 500.
    """

    code = "validation_error"
    http_status = 422
    message = "Данные не прошли проверку"

    @classmethod
    def from_pydantic(cls, exc: Exception, message: str | None = None) -> ModelValidationError:
        details: dict[str, Any] = {}
        errors = getattr(exc, "errors", None)
        if callable(errors):
            try:
                items = errors()
            except Exception:  # noqa: BLE001 — чужая ошибка не должна ломать обработку
                items = []
            if items:
                first = items[0]
                location = ".".join(str(part) for part in first.get("loc", ()))
                details["reason"] = f"{location}: {first.get('msg', 'неверное значение')}"
                details["problems"] = [
                    ".".join(str(part) for part in item.get("loc", ())) + f": {item.get('msg', '')}"
                    for item in items[:10]
                ]
        if "reason" not in details:
            details["reason"] = str(exc)[:300]
        return cls(message, details=details)


class NotFoundError(UPAError):
    code = "not_found"
    http_status = 404
    message = "Объект не найден"


class ConflictError(UPAError):
    code = "conflict"
    http_status = 409
    message = "Конфликт состояния"


class SiteUnreachableError(UPAError):
    """Сайт не открылся: DNS, таймаут, TLS, отказ соединения."""

    code = "site_unreachable"
    http_status = 502
    message = "Не удалось открыть сайт"


class BrowserError(UPAError):
    """Сбой браузерного движка."""

    code = "browser_error"
    http_status = 500
    message = "Ошибка браузерного движка"


class LLMUnavailableError(UPAError):
    """Локальная модель недоступна, облачный фолбэк не разрешён."""

    code = "llm_unavailable"
    http_status = 503
    message = "ИИ-модель недоступна"


class FeatureNotImplementedError(UPAError):
    """Функциональность ещё не реализована на текущем этапе разработки."""

    code = "not_implemented"
    http_status = 501
    message = "Функциональность ещё не реализована"
