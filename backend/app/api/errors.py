"""Обработчики ошибок: приводят любые сбои к единому JSON-формату."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import Settings
from app.core.errors import UPAError
from app.core.logging import get_logger

log = get_logger(__name__)


def _payload(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def register_error_handlers(app: FastAPI, settings: Settings) -> None:
    """Регистрирует обработчики на приложении."""

    @app.exception_handler(UPAError)
    async def _handle_upa_error(_request: Request, exc: UPAError) -> JSONResponse:
        log.warning("api.error", code=exc.code, message=exc.message, details=exc.details)
        return JSONResponse(status_code=exc.http_status, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_payload(
                "validation_error",
                "Некорректные данные запроса",
                {"errors": exc.errors()},
            ),
        )

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
