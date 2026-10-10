"""Эндпоинты Этапа 2: анализ страницы и карта элементов."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer import service as analyze
from app.analyzer.roles import DATA_ROLES, ROLE_LABELS, Role
from app.api.analyze_schemas import (
    AnalyzeRequest,
    ElementMapListResponse,
    ElementMapOut,
    ElementMapSummaryOut,
    ElementUpdateRequest,
    LLMInfoOut,
    RepeatGroupOut,
    ReportResponse,
    RoleInfo,
    RolesResponse,
)
from app.core.config import Settings
from app.core.db import get_db
from app.storage.models import ElementMap, Snapshot

router = APIRouter(tags=["analyze"])


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _outcome_to_out(outcome: analyze.AnalysisOutcome) -> ElementMapOut:
    """Собирает ответ API из результата анализа."""
    record = outcome.element_map
    data = analyze.element_map_to_dict(record, report=outcome.report)
    return ElementMapOut(
        id=data["id"],
        snapshot_id=data["snapshot_id"],
        version=data["version"],
        elements=data["elements"],
        by_role=data["by_role"],
        report=outcome.report,
        warnings=outcome.analysis.warnings,
        repeats=[RepeatGroupOut(**group.as_dict()) for group in outcome.analysis.repeats],
        confidence=data["confidence"],
        llm_provider=data["llm_provider"],
        llm_model=data["llm_model"],
        prompt_version=data["prompt_version"],
        edited_by_user=data["edited_by_user"],
        reused=outcome.reused,
        llm=LLMInfoOut(**outcome.llm.as_dict()),
        page={
            "title": outcome.analysis.title,
            "lang": outcome.analysis.lang,
            "meta": outcome.analysis.meta,
            "counts": outcome.analysis.counts,
        },
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


def _summary_out(record: ElementMap) -> ElementMapSummaryOut:
    return ElementMapSummaryOut(
        id=record.id,
        snapshot_id=record.snapshot_id,
        version=record.version,
        elements_count=len(record.elements or []),
        confidence=record.confidence,
        llm_provider=record.llm_provider,
        edited_by_user=record.edited_by_user,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.post(
    "/snapshots/{snapshot_id}/analyze",
    response_model=ElementMapOut,
    summary="Проанализировать снапшот и построить карту элементов",
    description=(
        "Разбирает обрезанный DOM снапшота: находит повторяющиеся блоки (карточки, "
        "строки), поля, кнопки, пагинацию, определяет роли и устойчивые селекторы. "
        "Если локальная модель доступна, она уточняет роли и формулирует резюме — "
        "при её отсутствии результат остаётся полноценным."
    ),
)
async def analyze_snapshot(
    snapshot_id: str,
    request: Request,
    payload: AnalyzeRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ElementMapOut:
    options = payload or AnalyzeRequest()
    outcome = await analyze.analyze_snapshot(
        db,
        _settings(request),
        snapshot_id,
        use_llm=options.use_llm,
        force=options.force,
    )
    return _outcome_to_out(outcome)


@router.get(
    "/snapshots/{snapshot_id}/element-map",
    response_model=ElementMapOut,
    summary="Карта элементов снапшота",
)
async def get_element_map(
    snapshot_id: str,
    db: AsyncSession = Depends(get_db),
) -> ElementMapOut:
    record = await analyze.require_element_map(db, snapshot_id)
    snapshot = await db.get(Snapshot, snapshot_id)
    return ElementMapOut(
        id=record.id,
        snapshot_id=record.snapshot_id,
        version=record.version,
        elements=list(record.elements or []),
        by_role=_count_by_role(record),
        report=record.summary,
        confidence=record.confidence,
        llm_provider=record.llm_provider,
        llm_model=record.llm_model,
        prompt_version=record.prompt_version,
        edited_by_user=record.edited_by_user,
        page={
            "title": getattr(snapshot, "title", None),
            "lang": getattr(snapshot, "lang", None),
        },
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _count_by_role(record: ElementMap) -> dict[str, int]:
    counts: dict[str, int] = {}
    for element in record.elements or []:
        role = str(element.get("role", "unknown"))
        counts[role] = counts.get(role, 0) + 1
    return counts


@router.get(
    "/element-maps",
    response_model=ElementMapListResponse,
    summary="Список построенных карт элементов",
)
async def list_element_maps(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ElementMapListResponse:
    records = await analyze.list_element_maps(db, limit=limit, offset=offset)
    total = int((await db.execute(select(func.count()).select_from(ElementMap))).scalar_one())
    return ElementMapListResponse(items=[_summary_out(record) for record in records], total=total)


@router.patch(
    "/snapshots/{snapshot_id}/element-map/{element_index}",
    response_model=ElementMapOut,
    summary="Исправить элемент карты",
    description="Ручная правка роли и подписи элемента. Задел визуального редактора (Этап 3).",
)
async def update_element(
    snapshot_id: str,
    element_index: int,
    payload: ElementUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ElementMapOut:
    record = await analyze.update_element(
        db,
        snapshot_id,
        element_index,
        role=payload.role,
        label=payload.label,
        description=payload.description,
    )
    return ElementMapOut(
        id=record.id,
        snapshot_id=record.snapshot_id,
        version=record.version,
        elements=list(record.elements or []),
        by_role=_count_by_role(record),
        report=record.summary,
        confidence=record.confidence,
        llm_provider=record.llm_provider,
        llm_model=record.llm_model,
        prompt_version=record.prompt_version,
        edited_by_user=record.edited_by_user,
        page={},
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get(
    "/snapshots/{snapshot_id}/report",
    response_model=ReportResponse,
    summary="Человекочитаемый отчёт о странице",
)
async def get_report(
    snapshot_id: str,
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    record = await analyze.require_element_map(db, snapshot_id)
    return ReportResponse(
        snapshot_id=snapshot_id,
        element_map_id=record.id,
        report=record.summary or "",
        generated_by="heuristics+llm" if record.llm_provider else "heuristics",
    )


@router.get(
    "/roles",
    response_model=RolesResponse,
    summary="Справочник ролей элементов",
)
async def list_roles() -> RolesResponse:
    return RolesResponse(
        items=[
            RoleInfo(
                role=role.value,
                label=ROLE_LABELS.get(role, role.value),
                is_data=role in DATA_ROLES,
            )
            for role in Role
        ]
    )
