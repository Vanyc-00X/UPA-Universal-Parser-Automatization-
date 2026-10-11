"""Эндпоинты движка извлечения (Этап 4): запуски, записи, отчёты.

Здесь сценарий превращается в данные. Каждый эндпоинт возвращает отчёт о полноте
вместе с данными: без него непонятно, собрано всё или с дырами.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.run_schemas import (
    DefinitionPreviewRequest,
    NormalizeCheckRequest,
    NormalizeCheckResponse,
    PageResultOut,
    RunItemOut,
    RunItemsResponse,
    RunListResponse,
    RunOut,
    RunPreviewResponse,
    RunReportOut,
    RunRequest,
)
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import ValidationError
from app.editor import scenario as scenario_service
from app.editor.schema import ScenarioDefinition
from app.engine import normalize as normalize_mod
from app.engine import service as engine
from app.engine import validate as engine_validate
from app.storage.models import Run, Scenario, ScenarioVersion

router = APIRouter(tags=["runs"])


def _settings(request: Request) -> Settings:
    return request.app.state.settings


# ---------------------------------------------------------------------------
# Предпросмотр и вспомогательные проверки (статические пути — до /runs/{id})
# ---------------------------------------------------------------------------


@router.post(
    "/runs/preview-definition",
    response_model=RunPreviewResponse,
    summary="Проверить определение сценария на снапшоте",
    description="Работает с черновиком редактора: позволяет проверить сценарий до сохранения.",
)
async def preview_definition(
    payload: DefinitionPreviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RunPreviewResponse:
    settings = _settings(request)
    definition = _validate_definition(payload.definition)
    data = await engine.preview_definition(
        db, settings, definition, snapshot_id=payload.snapshot_id, limit=payload.limit
    )
    return RunPreviewResponse(
        scenario_id="draft",
        snapshot_id=payload.snapshot_id,
        mode=data["extraction"]["mode"],
        records=data["records"],
        extraction=data["extraction"],
        report=_report_out(data["report"]),
        report_text=data["report_text"],
    )


@router.post(
    "/runs/preview-scenario",
    response_model=RunPreviewResponse,
    summary="Предпросмотр сохранённого сценария",
)
async def preview_scenario(
    payload: RunRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RunPreviewResponse:
    settings = _settings(request)
    scenario = await scenario_service.get_scenario(db, payload.scenario_id)
    version = await scenario_service.get_current_version(db, scenario)
    if version is None:
        raise ValidationError("У сценария нет версий", details={"scenario_id": scenario.id})
    definition = scenario_service.definition_from_version(version)

    snapshot_id = payload.snapshot_id or definition.snapshot_id
    if snapshot_id is None:
        snapshot_id = await engine._latest_snapshot_id(db, scenario.site_id)  # noqa: SLF001
    if snapshot_id is None:
        raise ValidationError("Не найден снапшот для предпросмотра")

    data = await engine.preview_definition(db, settings, definition, snapshot_id=snapshot_id)
    return RunPreviewResponse(
        scenario_id=scenario.id,
        snapshot_id=snapshot_id,
        mode=data["extraction"]["mode"],
        records=data["records"],
        extraction=data["extraction"],
        report=_report_out(data["report"]),
        report_text=data["report_text"],
    )


@router.post(
    "/runs/check-value",
    response_model=NormalizeCheckResponse,
    summary="Проверить нормализацию значения",
    description="Показывает, как UPA поймёт значение: «1 249,00 ₽» → 1249.0.",
)
async def check_value(payload: NormalizeCheckRequest) -> NormalizeCheckResponse:
    kind = payload.kind
    if kind == "auto":
        kind = normalize_mod.detect_kind(payload.value)
    result = normalize_mod.normalize(payload.value, kind=kind)
    return NormalizeCheckResponse(
        kind=kind, value=result.value, raw=result.raw, problem=result.problem
    )


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------


@router.post(
    "/runs",
    response_model=RunOut,
    summary="Запустить сценарий и собрать данные",
    description=(
        "Разбирает страницы по сценарию, нормализует значения, проверяет записи и "
        "возвращает отчёт о полноте. Разбор идёт по снапшоту; обход нескольких "
        "страниц требует заранее снятых снапшотов или живой догрузки."
    ),
)
async def create_run(
    payload: RunRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RunOut:
    settings = _settings(request)
    fetcher = _live_fetcher(settings) if payload.live else None

    outcome = await engine.run_scenario(
        db,
        settings,
        payload.scenario_id,
        snapshot_id=payload.snapshot_id,
        fetch_page=fetcher,
        min_coverage=payload.min_coverage,
    )
    return await _run_out(db, outcome.run, outcome=outcome)


@router.get(
    "/runs",
    response_model=RunListResponse,
    summary="Список запусков",
)
async def list_runs(
    db: AsyncSession = Depends(get_db),
    scenario_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> RunListResponse:
    runs = await engine.list_runs(db, scenario_id=scenario_id, limit=limit, offset=offset)
    total = await engine.count_runs(db, scenario_id)
    items = [await _run_out(db, run, with_items_report=True) for run in runs]
    return RunListResponse(items=items, total=total)


@router.get(
    "/runs/{run_id}",
    response_model=RunOut,
    summary="Сведения о запуске с отчётом",
)
async def get_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> RunOut:
    run = await engine.get_run(db, run_id)
    return await _run_out(db, run, with_items_report=True)


@router.get(
    "/runs/{run_id}/items",
    response_model=RunItemsResponse,
    summary="Собранные записи",
)
async def get_run_items(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    only_invalid: bool = Query(False, description="Только записи с пропусками"),
) -> RunItemsResponse:
    await engine.get_run(db, run_id)
    items = await engine.list_run_items(
        db, run_id, limit=limit, offset=offset, only_invalid=only_invalid
    )
    total = await engine.count_run_items(db, run_id, only_invalid=only_invalid)
    return RunItemsResponse(
        run_id=run_id,
        items=[
            RunItemOut(
                id=item.id,
                position=item.position,
                data=item.data or {},
                source_url=item.source_url,
                is_valid=item.is_valid,
                validation_errors=list(item.validation_errors or []),
            )
            for item in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/runs/{run_id}",
    summary="Удалить запуск вместе с записями",
)
async def delete_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await engine.delete_run(db, run_id)
    return {"run_id": run_id, "deleted": True}


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _validate_definition(definition: ScenarioDefinition) -> ScenarioDefinition:
    """Проверяет определение из тела запроса."""
    try:
        return ScenarioDefinition.model_validate(definition)
    except Exception as exc:  # noqa: BLE001 — ошибки валидации pydantic
        raise ValidationError(
            "Определение сценария заполнено неверно", details={"reason": str(exc)[:300]}
        ) from exc


def _report_out(payload: dict[str, Any]) -> RunReportOut:
    """Приводит отчёт движка к схеме API."""
    return RunReportOut.model_validate(payload)


async def _run_out(
    session: AsyncSession,
    run: Run,
    *,
    outcome: engine.RunOutcome | None = None,
    with_items_report: bool = False,
) -> RunOut:
    """Собирает представление запуска, добавляя отчёт при необходимости."""
    report: RunReportOut | None = None
    pages: list[dict[str, Any]] = []
    if outcome is not None:
        report = _report_out(outcome.report.as_dict())
        pages = [page.as_dict() for page in outcome.pages]
    elif with_items_report:
        report = await _report_from_items(session, run)

    scenario_name: str | None = None
    if run.scenario_id:
        scenario = await session.get(Scenario, run.scenario_id)
        if scenario is not None:
            scenario_name = scenario.name

    return RunOut(
        id=run.id,
        scenario_id=run.scenario_id,
        scenario_version_id=run.scenario_version_id,
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        trigger=run.trigger.value if hasattr(run.trigger, "value") else str(run.trigger),
        started_at=run.started_at,
        finished_at=run.finished_at,
        pages_done=run.pages_done,
        items_count=run.items_count,
        errors_count=run.errors_count,
        error=run.error,
        stats=run.stats or {},
        created_at=run.created_at,
        report=report,
        pages=[PageResultOut.model_validate(page) for page in pages],
        scenario_name=scenario_name,
    )


async def _report_from_items(session: AsyncSession, run: Run) -> RunReportOut | None:
    """Строит отчёт по уже сохранённым записям.

    Нужно для истории запусков: отчёт должен восстанавливаться, а не храниться
    отдельно и расходиться с данными.
    """
    items = await engine.list_run_items(session, run.id, limit=10_000)
    if not items:
        return None

    definition = await _definition_of_run(session, run)
    if definition is None:
        return RunReportOut(records=len(items))

    fields: dict[str, dict[str, Any]] = {}
    for spec in definition.fields:
        filled = sum(1 for item in items if (item.data or {}).get(spec.key) not in (None, ""))
        fields[spec.key] = {
            "title": spec.title,
            "required": spec.required,
            "filled": filled,
            "total": len(items),
            "coverage": round(filled / len(items), 3) if items else 0.0,
            "problems": {},
        }

    required = [key for key, item in fields.items() if item["required"]]
    coverage = (
        round(sum(fields[key]["coverage"] for key in required) / len(required), 3)
        if required
        else (
            round(sum(item["coverage"] for item in fields.values()) / len(fields), 3)
            if fields
            else 0.0
        )
    )
    invalid = sum(1 for item in items if not item.is_valid)
    completeness = (
        round(sum(item["coverage"] for item in fields.values()) / len(fields), 3) if fields else 0.0
    )

    return RunReportOut(
        records=len(items),
        valid_records=len(items) - invalid,
        invalid_records=invalid,
        required_coverage=coverage,
        completeness=completeness,
        min_coverage=engine_validate.DEFAULT_MIN_COVERAGE,
        passed=bool(items) and invalid == 0 and coverage >= engine_validate.DEFAULT_MIN_COVERAGE,
        issues_total=sum(len(item.validation_errors or []) for item in items),
        fields=fields,
    )


async def _definition_of_run(session: AsyncSession, run: Run) -> ScenarioDefinition | None:
    """Определение сценария, по которому выполнялся запуск."""
    if not run.scenario_version_id:
        return None
    version = await session.get(ScenarioVersion, run.scenario_version_id)
    if version is None:
        return None
    try:
        return scenario_service.definition_from_version(version)
    except ValidationError:
        return None


def _live_fetcher(settings: Settings) -> engine.PageFetcher:
    """Загрузчик страниц живым браузером.

    Используется только при явном запросе: обычный запуск разбирает уже снятые
    снапшоты и не ходит в сеть.
    """
    from app.crawler import browser as browser_module

    async def fetch(url: str) -> tuple[str | None, str | None]:
        try:
            snapshot = await browser_module.capture_page(settings, url)
        except Exception as exc:  # noqa: BLE001 — внешний сайт
            return None, f"{type(exc).__name__}: {exc}"
        return snapshot.html, None

    return fetch
