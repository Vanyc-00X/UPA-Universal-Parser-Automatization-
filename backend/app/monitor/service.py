"""Сервис мониторинга: расписание, проверка, сохранение отчётов об изменениях."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.engine import service as engine
from app.exporters import service as export_service
from app.storage.models import RunTrigger, Scenario

log = get_logger(__name__)

# Человекочитаемые интервалы → секунды. Хранятся в Scenario.schedule_cron.
INTERVALS: dict[str, int] = {
    "every_15m": 15 * 60,
    "every_1h": 60 * 60,
    "every_6h": 6 * 60 * 60,
    "every_24h": 24 * 60 * 60,
}


def parse_interval_seconds(value: str | None) -> int | None:
    """Возвращает интервал в секундах или None, если мониторинг выключен."""
    if not value:
        return None
    cleaned = value.strip().lower()
    if cleaned in {"off", "none", "disabled", ""}:
        return None
    if cleaned in INTERVALS:
        return INTERVALS[cleaned]
    if cleaned.startswith("every_") and cleaned.endswith("m"):
        try:
            minutes = int(cleaned.removeprefix("every_").removesuffix("m"))
            if 1 <= minutes <= 24 * 60:
                return minutes * 60
        except ValueError:
            return None
    return None


def events_dir(settings: Settings) -> Path:
    path = settings.data_dir / "monitor_events"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def set_schedule(
    session: AsyncSession,
    scenario_id: str,
    *,
    interval: str | None,
) -> Scenario:
    """Включает или выключает мониторинг сценария."""
    scenario = await session.get(Scenario, scenario_id)
    if scenario is None:
        raise NotFoundError("Сценарий не найден", details={"scenario_id": scenario_id})
    if interval in (None, "", "off", "none"):
        scenario.schedule_cron = None
    else:
        if parse_interval_seconds(interval) is None:
            raise ValidationError(
                "Неизвестный интервал",
                details={"interval": interval, "allowed": list(INTERVALS)},
            )
        scenario.schedule_cron = interval
    await session.flush()
    return scenario


async def list_monitored(session: AsyncSession) -> list[Scenario]:
    result = await session.execute(
        select(Scenario)
        .where(Scenario.schedule_cron.is_not(None), Scenario.is_active.is_(True))
        .order_by(Scenario.name)
    )
    return list(result.scalars().all())


def is_due(scenario: Scenario, *, now: datetime | None = None) -> bool:
    seconds = parse_interval_seconds(scenario.schedule_cron)
    if seconds is None:
        return False
    now = now or datetime.now(timezone.utc)
    last = scenario.last_run_at
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return now >= last + timedelta(seconds=seconds)


async def run_monitor_check(
    session: AsyncSession,
    settings: Settings,
    scenario_id: str,
    *,
    live: bool = False,
) -> dict[str, Any]:
    """Запускает сценарий и сравнивает с предыдущим запуском."""
    scenario = await session.get(Scenario, scenario_id)
    if scenario is None:
        raise NotFoundError("Сценарий не найден", details={"scenario_id": scenario_id})

    fetch_page = None
    if live:
        from app.crawler import browser as browser_module

        async def fetch_page(url: str) -> tuple[str | None, str | None]:
            try:
                snapshot = await browser_module.capture_page(settings, url)
            except Exception as exc:  # noqa: BLE001
                return None, f"{type(exc).__name__}: {exc}"
            return snapshot.html, None

    outcome = await engine.run_scenario(
        session,
        settings,
        scenario_id,
        fetch_page=fetch_page,
        trigger=RunTrigger.SCHEDULED,
        min_coverage=0.0,
    )
    scenario.last_run_at = datetime.now(timezone.utc)
    await session.flush()

    run = outcome.run
    diff_summary: dict[str, Any] | None = None
    has_changes = False
    try:
        diff = await export_service.diff_runs(session, run.id)
        diff_summary = diff.summary()
        has_changes = bool(diff.added or diff.removed or diff.changed)
        event = {
            "scenario_id": scenario_id,
            "scenario_name": scenario.name,
            "run_id": run.id,
            "previous_run_id": diff.previous_run_id,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "has_changes": has_changes,
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
            "items_count": run.items_count,
            "diff": diff.as_dict(),
        }
    except Exception as exc:  # noqa: BLE001 — первый запуск без предыдущего
        event = {
            "scenario_id": scenario_id,
            "scenario_name": scenario.name,
            "run_id": run.id,
            "previous_run_id": None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "has_changes": False,
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
            "items_count": run.items_count,
            "diff": None,
            "note": str(exc),
        }

    path = events_dir(settings) / f"{scenario_id}_{run.id}.json"
    path.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(
        "monitor.check",
        scenario_id=scenario_id,
        run_id=run.id,
        has_changes=has_changes,
        path=str(path),
    )
    return event


def list_events(settings: Settings, *, limit: int = 50) -> list[dict[str, Any]]:
    directory = events_dir(settings)
    files = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    events: list[dict[str, Any]] = []
    for path in files[:limit]:
        try:
            events.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return events


async def tick(settings: Settings) -> list[dict[str, Any]]:
    """Один проход планировщика: все просроченные сценарии."""
    from app.core.db import session_scope

    results: list[dict[str, Any]] = []
    async with session_scope() as session:
        monitored = await list_monitored(session)
        due = [item for item in monitored if is_due(item)]
        for scenario in due:
            try:
                event = await run_monitor_check(session, settings, scenario.id, live=False)
                results.append(event)
            except Exception as exc:  # noqa: BLE001 — один сбой не останавливает остальных
                log.error("monitor.tick_failed", scenario_id=scenario.id, error=str(exc))
                results.append(
                    {
                        "scenario_id": scenario.id,
                        "error": str(exc),
                        "has_changes": False,
                    }
                )
    return results
