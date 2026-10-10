"""Сборка FastAPI-приложения UPA."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import api_router
from app.api.errors import register_error_handlers
from app.core.config import Settings, get_settings
from app.core.db import dispose_engine, init_engine
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)

DESCRIPTION = """
**UPA (Universal Parser Automatization)** — локальное приложение, которое изучает сайт,
описывает его элементы, собирает данные по сценарию пользователя и умеет готовить
ТЗ в Markdown для внешнего ИИ-агента.

Текущий этап разработки — **Этап 1: браузер и снапшот страницы**.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Инициализация и освобождение ресурсов приложения."""
    settings: Settings = app.state.settings
    settings.ensure_directories()
    init_engine(settings)
    log.info(
        "app.startup",
        app=settings.app_name,
        version=__version__,
        env=settings.env,
        data_dir=str(settings.data_dir),
    )
    try:
        yield
    finally:
        await dispose_engine()
        log.info("app.shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Создаёт приложение. Принимает настройки — это упрощает тесты."""
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=f"{settings.app_name} API",
        description=DESCRIPTION,
        version=__version__,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app, settings)

    # Две точки монтирования одного набора маршрутов:
    #   /health, /system/*            — без версии: скрипт запуска и быстрые проверки;
    #   /api/v1/...                   — версионированный API для фронтенда.
    # Перед вторым монтированием добавляем префикс к operation_id, иначе в схеме
    # OpenAPI останется только одна из двух операций с одинаковым именем.
    app.include_router(api_router)
    for route in api_router.routes:
        operation_id = getattr(route, "operation_id", None) or getattr(route, "name", None)
        if operation_id:
            route.operation_id = f"v1_{operation_id}"  # type: ignore[attr-defined]
    app.include_router(api_router, prefix=settings.api_prefix)

    return app


app = create_app()
