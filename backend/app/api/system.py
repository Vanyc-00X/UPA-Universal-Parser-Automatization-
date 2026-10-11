"""Системные эндпоинты: здоровье, сведения о сборке, состояние ИИ, этапы плана."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app import __version__
from app.api import deps
from app.api.schemas import (
    BrowserStatusResponse,
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
        status="done",
        description="Эвристики и локальная модель: роли, устойчивые селекторы, отчёт о странице",
    ),
    FeatureStatus(
        key="visual_editor",
        title="Визуальный редактор элементов",
        stage="3",
        status="done",
        description="Инспектор страницы, проверка селекторов, правка полей и сохранение сценария",
    ),
    FeatureStatus(
        key="extraction",
        title="Движок извлечения",
        stage="4",
        status="done",
        description="DOM list/single, нормализация, пагинация, отчёт о полноте, API запусков",
    ),
    FeatureStatus(
        key="storage_export",
        title="Хранение и экспорт",
        stage="5",
        status="done",
        description="Экспорт CSV/XLSX/JSON, Markdown-ТЗ, diff запусков, артефакты",
    ),
    FeatureStatus(
        key="self_healing",
        title="Надёжность и self-healing",
        stage="6",
        status="done",
        description="Диагностика селекторов, предложение патча, журнал, ретраи, robots.txt",
    ),
    FeatureStatus(
        key="form_fill",
        title="Автоматизация ввода",
        stage="7",
        status="done",
        description="Действия, запись, dry-run, CSV/XLSX, экспорт Playwright-скрипта",
    ),
    FeatureStatus(
        key="packaging",
        title="Упаковка и документация",
        stage="8",
        status="done",
        description="Онбординг, шаблоны, ensure Ollama, лаунчер Windows, документация",
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
        status="done",
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
        status="done",
        items=[
            "лёгкий DOM-парсер",
            "детерминированный предпроход",
            "LLM со структурным выводом",
            "скоринг селекторов",
            "отчёт о странице",
        ],
    ),
    StageInfo(
        key="3",
        title="Визуальный редактор элементов",
        status="done",
        items=[
            "инспектор страницы с рамками",
            "проверка селекторов на живом DOM",
            "черновик сценария и правка полей",
            "сохранение сценария с версиями",
        ],
    ),
    StageInfo(
        key="4",
        title="Движок извлечения",
        status="done",
        items=[
            "извлечение list/single из DOM",
            "нормализация цен, ссылок и дат",
            "пагинация next_link и url_template",
            "запуски, записи и отчёт о полноте",
        ],
    ),
    StageInfo(
        key="5",
        title="Хранение и экспорт",
        status="done",
        items=[
            "экспорт CSV/XLSX/JSON/JSONL/Markdown",
            "генератор ТЗ в Markdown",
            "diff запусков",
            "артефакты экспорта на диске",
        ],
    ),
    StageInfo(
        key="6",
        title="Надёжность и self-healing",
        status="done",
        items=[
            "диагностика сломанных селекторов",
            "предложение патча без автоприменения",
            "журнал шагов запуска",
            "ретраи сети и проверка robots.txt",
        ],
    ),
    StageInfo(
        key="7",
        title="Автоматизация ввода",
        status="done",
        items=[
            "действия включая upload/loop/if",
            "запись событий и очеловечивание шагов",
            "параметризация CSV/XLSX и dry-run",
            "экспорт в Python-скрипт Playwright",
            "подтверждение опасных отправок",
        ],
    ),
    StageInfo(
        key="8",
        title="Упаковка и документация",
        status="done",
        items=[
            "онбординг-визард и пустые состояния",
            "шаблоны сценариев и примеры CSV",
            "проверка/загрузка модели Ollama",
            "лаунчер Windows и Docker Compose",
            "документация: быстрый старт, FAQ, дисклеймер",
        ],
    ),
]

CURRENT_STAGE = "8"


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


@router.get(
    "/system/browser",
    response_model=BrowserStatusResponse,
    summary="Готовность Chromium / Chrome / Edge",
)
async def browser_status(request: Request) -> BrowserStatusResponse:
    from app.crawler.browser_ready import browser_status as probe

    settings = _settings(request)
    return BrowserStatusResponse(**probe(settings))
