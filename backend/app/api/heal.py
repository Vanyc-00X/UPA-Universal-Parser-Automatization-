"""Эндпоинты self-healing и наблюдаемости (Этап 6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.heal_schemas import (
    HealApplyRequest,
    HealApplyResponse,
    HealProposalOut,
    JournalStepOut,
    RobotsCheckOut,
)
from app.core.config import Settings
from app.core.db import get_db
from app.healing import service as healing
from app.healing.robots import check_robots

router = APIRouter(tags=["healing"])


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get(
    "/runs/{run_id}/heal",
    response_model=HealProposalOut,
    summary="Предложение самопочинки селекторов",
    description=(
        "Если заполненность упала, UPA подбирает запасные селекторы и кандидатов "
        "из карты элементов. Патч не применяется без явного подтверждения."
    ),
)
async def get_heal_proposal(
    run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    refresh: bool = Query(False, description="Пересчитать предложение"),
) -> HealProposalOut:
    settings = _settings(request)
    if not refresh:
        cached = await healing.proposal_from_run(db, run_id)
        if cached is not None:
            return HealProposalOut.model_validate(cached.as_dict())
    proposal = await healing.build_heal_proposal(db, settings, run_id)
    return HealProposalOut.model_validate(proposal.as_dict())


@router.post(
    "/runs/{run_id}/heal/apply",
    response_model=HealApplyResponse,
    summary="Применить патч как новую версию сценария",
)
async def apply_heal(
    run_id: str,
    payload: HealApplyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HealApplyResponse:
    settings = _settings(request)
    result = await healing.apply_heal_proposal(
        db,
        settings,
        run_id,
        keys=payload.keys,
        change_note=payload.change_note,
    )
    return HealApplyResponse.model_validate(result)


@router.get(
    "/runs/{run_id}/journal",
    response_model=list[JournalStepOut],
    summary="Журнал шагов запуска",
)
async def get_run_journal(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[JournalStepOut]:
    steps = await healing.journal_of_run(db, run_id)
    return [JournalStepOut.model_validate(step) for step in steps]


@router.get(
    "/robots/check",
    response_model=RobotsCheckOut,
    summary="Проверить robots.txt для URL",
)
async def robots_check(request: Request, url: str = Query(...)) -> RobotsCheckOut:
    settings = _settings(request)
    result = await check_robots(settings, url)
    return RobotsCheckOut.model_validate(result.as_dict())
