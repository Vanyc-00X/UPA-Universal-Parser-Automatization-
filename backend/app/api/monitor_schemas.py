"""Схемы API мониторинга изменений."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ScheduleUpdateRequest(BaseModel):
    interval: str | None = Field(
        None,
        description="every_15m | every_1h | every_6h | every_24h | off",
    )


class MonitorScenarioOut(BaseModel):
    scenario_id: str
    name: str
    interval: str | None
    interval_seconds: int | None
    last_run_at: datetime | None
    is_due: bool
    is_active: bool


class MonitorListResponse(BaseModel):
    items: list[MonitorScenarioOut]
    intervals: dict[str, int]


class MonitorCheckRequest(BaseModel):
    live: bool = False


class MonitorCheckResponse(BaseModel):
    event: dict[str, Any]


class MonitorEventsResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
