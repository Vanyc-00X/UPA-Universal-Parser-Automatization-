"""Фоновый цикл мониторинга (asyncio)."""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.monitor import service as monitor_service

log = get_logger(__name__)

_task: asyncio.Task[Any] | None = None
_stop: asyncio.Event | None = None


async def _loop(settings: Settings, *, poll_seconds: int = 60) -> None:
    assert _stop is not None
    log.info("monitor.scheduler_started", poll_seconds=poll_seconds)
    while not _stop.is_set():
        if settings.env != "test":
            try:
                results = await monitor_service.tick(settings)
                if results:
                    log.info("monitor.tick", checks=len(results))
            except Exception as exc:  # noqa: BLE001
                log.error("monitor.scheduler_error", error=str(exc))
        try:
            await asyncio.wait_for(_stop.wait(), timeout=poll_seconds)
        except TimeoutError:
            continue
    log.info("monitor.scheduler_stopped")


def start(settings: Settings, *, poll_seconds: int = 60) -> None:
    """Запускает фоновый планировщик (идемпотентно)."""
    global _task, _stop
    if _task is not None and not _task.done():
        return
    _stop = asyncio.Event()
    _task = asyncio.create_task(_loop(settings, poll_seconds=poll_seconds))


async def stop() -> None:
    global _task, _stop
    if _stop is not None:
        _stop.set()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=5)
        except (TimeoutError, asyncio.CancelledError):
            _task.cancel()
    _task = None
    _stop = None
