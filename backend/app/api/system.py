"""Системные эндпоинты: здоровье, сведения о сборке, состояние ИИ, этапы плана."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app import __version__
from app.api import deps
from app.api.schemas import (
    ComponentHealth,
    FeaturesResponse,
    FeatureStatus,
    HealthResponse,
    LLMStatusResponse,
    RoadmapResponse,
    StageInfo,
    SystemInfoResponse,
)
from app.core.config import Settings

router = APIRouter(tags=["system"])

# Соответствие «функция → этап PLAN.md» для дашборда.
FEATURES: list[FeatureStatus] = [
    FeatureStatus(
        key="scaffold",
        title="Каркас приложения",
        stage="0",
        status="done",
        description="FastAPI + React, конфигурация, логирование, БД, единый формат ошибок",
    ),
    FeatureStatus(
        key="browser_snapshot",
        title="Браузер и снапшот страницы",
        stage="1",
        status="done",
        description="Playwright: DOM, скриншоты, сетевые запросы, storage state, кэш снапшотов",
    ),
    FeatureStatus(
        key="element_map",
        title="Анализ и карта элементов",
        stage="2",
        status="planned",
        description="Детерминированные эвристики + локальная модель описывают элементы",
    ),
    FeatureStatus(
        key="visual_editor",
        title="Визуальный редактор элементов",
        stage="3",
        status="planned",
        description="Пользователь исправляет карту без знания CSS",
    ),
    FeatureStatus(
        key="extraction",
        title="Движок извлечения",
        stage="4",
        status="planned",
        description="JSON-API/DOM-стратегии, пагинация, нормализация, валидация",
    ),
    FeatureStatus(
        key="storage_export",
        title="Хранение и экспорт",
        stage="5",
        status="planned",
        description="История запусков, CSV/XLSX/JSON, генератор ТЗ в Markdown",
    ),
    FeatureStatus(
        key="self_healing",
        title="Надёжность и self-healing",
        stage="6",
        status="planned",
        description="Автопочинка селекторов, ретраи, наблюдаемость",
    ),
    FeatureStatus(
        key="form_fill",
        title="Автоматизация ввода",
        stage="7",
        status="planned",
        description="Действия, параметризация, генерация Python-скрипта",
    ),
    FeatureStatus(
        key="packaging",
        title="Упаковка и документация",
        stage="8",
        status="planned",
        description="Лаунчер, онбординг, документация",
    ),
]

STAGES: list[StageInfo] = [
    StageInfo(
        key="0",
        title="Каркас и инфраструктура",
        status="done",
        items=[
            "структура репозитория",
            "FastAPI: health, CORS, конфиг, ошибки",
            "SQLite + Alembic + модели",
            "React-каркас с роутингом",
            "скрипт запуска run.ps1",
            "тесты и линтеры",
        ],
    ),
    StageInfo(
        key="1",
        title="Браузер и снапшот страницы",
        status="in_progress",
        items=[
            "обёртка Playwright",
            "снапшот: DOM, скриншоты, сеть, storage state",
            "обрезка DOM под лимит токенов",
            "кэш снапшотов",
            "прогресс через WebSocket",
        ],
    ),
    StageInfo(
        key="2",
        title="Анализ: карта элементов и ИИ-описания",
        status="planned",
        items=["детерминированный предпроход", "LLM со структурным выводом", "скоринг селекторов"],
    ),
    StageInfo(
        key="3",
        title="Визуальный редактор элементов",
        status="planned",
        items=["overlay-инспектор", "панель ролей", "валидация селектора"],
    ),
    StageInfo(
        key="4",
        title="Движок извлечения",
        status="planned",
        items=["резолвер селекторов", "стратегии json_api/dom_list/llm", "пагинация", "валидация"],
    ),
    StageInfo(
        key="5",
        title="Хранение и экспорт",
        status="planned",
        items=["таблица результатов", "CSV/XLSX/JSON", "генератор ТЗ в Markdown"],
    ),
    StageInfo(
        key="6",
        title="Надёжность и self-healing",
        status="planned",
        items=["автопочинка селекторов", "ретраи", "наблюдаемость"],
    ),
    StageInfo(
        key="7",
        title="Автоматизация ввода",
        status="planned",
        items=["действия", "параметризация из файла", "экспорт в Python-скрипт"],
    ),
    StageInfo(
        key="8",
        title="Упаковка и документация",
        status="planned",
        items=["лаунчер", "онбординг", "документация"],
    ),
]

CURRENT_STAGE = "1"


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Проверка работоспособности",
    description="Возвращает состояние приложения и его подсистем. Всегда 200, если процесс жив.",
)
async def health(request: Request) -> HealthResponse:
    settings = _settings(request)
    components: list[ComponentHealth] = []

    db_status, db_detail = await deps.check_database(settings)
    components.append(ComponentHealth(name="database", status=db_status, detail=db_detail))

    llm = await deps.check_llm(settings)
    components.append(
        ComponentHealth(
            name="llm",
            status="ok" if llm["available"] else "degraded",
            detail=llm.get("detail") or f"провайдер: {llm['provider']}",
        )
    )
    components.append(ComponentHealth(name="browser", status="skipped", detail="Этап 1"))

    overall = "ok" if db_status == "ok" else "degraded"
    return HealthResponse(
        status=overall,
        app=settings.app_name,
        version=__version__,
        env=settings.env,
        uptime_s=deps.uptime_seconds(),
        components=components,
    )


@router.get(
    "/system/info",
    response_model=SystemInfoResponse,
    summary="Сведения о сборке и настройках",
)
async def system_info(request: Request) -> SystemInfoResponse:
    settings = _settings(request)
    db_path = settings.database_path
    return SystemInfoResponse(
        app=settings.app_name,
        version=__version__,
        env=settings.env,
        debug=settings.debug,
        stage=CURRENT_STAGE,
        stage_title=next(s.title for s in STAGES if s.key == CURRENT_STAGE),
        implemented=[f.key for f in FEATURES if f.status == "done"],
        planned=[f.key for f in FEATURES if f.status != "done"],
        python_version=deps.python_version(),
        database_url=settings.database_url,
        database_path=str(db_path) if db_path else None,
        data_dir=str(settings.data_dir),
        browser={
            "headless": settings.browser_headless,
            "timeout_ms": settings.browser_timeout_ms,
            "locale": settings.browser_locale,
            "dom_max_tokens": settings.dom_max_tokens,
        },
        llm={
            "provider": settings.llm_provider,
            "ollama_base_url": settings.ollama_base_url,
            "ollama_model": settings.ollama_model,
            "cloud_fallback": settings.llm_cloud_fallback,
        },
    )


@router.get(
    "/system/features",
    response_model=FeaturesResponse,
    summary="Готовность функций по этапам",
)
async def features() -> FeaturesResponse:
    return FeaturesResponse(current_stage=CURRENT_STAGE, items=FEATURES)


@router.get(
    "/system/roadmap",
    response_model=RoadmapResponse,
    summary="Этапы разработки из PLAN.md",
)
async def roadmap() -> RoadmapResponse:
    from app.storage.models import utcnow

    return RoadmapResponse(stages=STAGES, current_stage=CURRENT_STAGE, updated_at=utcnow())


@router.get(
    "/system/llm",
    response_model=LLMStatusResponse,
    summary="Состояние локальной ИИ-модели",
)
async def llm_status(request: Request) -> LLMStatusResponse:
    settings = _settings(request)
    data = await deps.check_llm(settings)
    return LLMStatusResponse(**data)
