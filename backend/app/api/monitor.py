"""API мониторинга изменений на сайтах."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.monitor_schemas import (
    MonitorCheckRequest,
    MonitorCheckResponse,
    MonitorEventsResponse,
    MonitorListResponse,
    MonitorScenarioOut,
    ScheduleUpdateRequest,
)
from app.core.config import Settings
from app.core.db import get_db
from app.monitor import service as monitor_service
from app.storage.models import Scenario

router = APIRouter(prefix="/monitor", tags=["monitor"])


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get(
    "",
    response_model=MonitorListResponse,
    summary="Сценарии с расписанием мониторинга",
)
async def list_monitors(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MonitorListResponse:
    result = await db.execute(select(Scenario).order_by(Scenario.name))
    scenarios = list(result.scalars().all())
    items = [
        MonitorScenarioOut(
            scenario_id=scenario.id,
            name=scenario.name,
            interval=scenario.schedule_cron,
            interval_seconds=monitor_service.parse_interval_seconds(scenario.schedule_cron),
            last_run_at=scenario.last_run_at,
            is_due=monitor_service.is_due(scenario),
            is_active=scenario.is_active,
        )
        for scenario in scenarios
    ]
    # В списке удобнее сначала те, у кого мониторинг включён.
    items.sort(key=lambda item: (item.interval is None, item.name.lower()))
    return MonitorListResponse(items=items, intervals=dict(monitor_service.INTERVALS))


@router.put(
    "/scenarios/{scenario_id}/schedule",
    response_model=MonitorScenarioOut,
    summary="Задать интервал мониторинга",
)
async def update_schedule(
    scenario_id: str,
    payload: ScheduleUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MonitorScenarioOut:
    scenario = await monitor_service.set_schedule(
        db, scenario_id, interval=payload.interval
    )
    return MonitorScenarioOut(
        scenario_id=scenario.id,
        name=scenario.name,
        interval=scenario.schedule_cron,
        interval_seconds=monitor_service.parse_interval_seconds(scenario.schedule_cron),
        last_run_at=scenario.last_run_at,
        is_due=monitor_service.is_due(scenario),
        is_active=scenario.is_active,
    )


@router.post(
    "/scenarios/{scenario_id}/check",
    response_model=MonitorCheckResponse,
    summary="Проверить изменения сейчас",
)
async def check_now(
    scenario_id: str,
    payload: MonitorCheckRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MonitorCheckResponse:
    settings = _settings(request)
    event = await monitor_service.run_monitor_check(
        db, settings, scenario_id, live=payload.live
    )
    return MonitorCheckResponse(event=event)


@router.get(
    "/events",
    response_model=MonitorEventsResponse,
    summary="Журнал проверок и изменений",
)
async def list_events(
    request: Request,
    limit: int = 50,
) -> MonitorEventsResponse:
    settings = _settings(request)
    items = monitor_service.list_events(settings, limit=min(limit, 200))
    return MonitorEventsResponse(items=items, total=len(items))
