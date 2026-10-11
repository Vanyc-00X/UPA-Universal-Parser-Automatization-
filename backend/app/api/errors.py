"""Обработчики ошибок: приводят любые сбои к единому JSON-формату."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import Settings
from app.core.errors import ModelValidationError, UPAError
from app.core.logging import get_logger

log = get_logger(__name__)


def _payload(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _readable_problems(errors: list[dict]) -> list[str]:
    """Превращает ошибки pydantic в список понятных строк.

    В ``ctx`` pydantic кладёт исходные объекты исключений: отдавать их в JSON
    нельзя, ответ просто не соберётся. Поэтому оставляем только путь и текст.
    """
    problems: list[str] = []
    for item in errors[:10]:
        location = ".".join(str(part) for part in item.get("loc", ()))
        problems.append(f"{location}: {item.get('msg', 'неверное значение')}")
    return problems


def register_error_handlers(app: FastAPI, settings: Settings) -> None:
    """Регистрирует обработчики на приложении."""

    @app.exception_handler(UPAError)
    async def _handle_upa_error(_request: Request, exc: UPAError) -> JSONResponse:
        log.warning("api.error", code=exc.code, message=exc.message, details=exc.details)
        return JSONResponse(status_code=exc.http_status, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # Приводим детали к сериализуемому виду: pydantic складывает в ctx живые
        # объекты исключений, из-за которых ответ иначе не собрать.
        return JSONResponse(
            status_code=422,
            content=_payload(
                "validation_error",
                "Некорректные данные запроса",
                {"problems": _readable_problems(exc.errors())},
            ),
        )

    @app.exception_handler(PydanticValidationError)
    async def _handle_model_validation(
        _request: Request, exc: PydanticValidationError
    ) -> JSONResponse:
        """Ошибки вложенных моделей: например, определения сценария.

        FastAPI разбирает тело запроса до вызова обработчика, поэтому без этого
        перехвата ответ был бы невнятным или превращался в 500.
        """
        converted = ModelValidationError.from_pydantic(
            exc, "Определение сценария заполнено неверно"
        )
        log.warning("api.model_validation", details=converted.details)
        return JSONResponse(status_code=converted.http_status, content=converted.to_payload())

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(code, str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        log.exception("api.unhandled", error=str(exc))
        details = {"type": type(exc).__name__} if settings.debug else {}
        return JSONResponse(
            status_code=500,
            content=_payload("internal_error", "Внутренняя ошибка приложения", details),
        )
