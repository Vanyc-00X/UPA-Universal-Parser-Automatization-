"""Тесты мониторинга изменений."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core.config import Settings
from app.monitor import service as monitor_service
from app.storage.models import Scenario
from tests.fakes import patch_capture


@pytest.fixture(autouse=True)
def _fake_browser(settings: Settings, monkeypatch):
    settings.llm_provider = "none"
    return patch_capture(monkeypatch, settings)


def test_parse_interval_seconds() -> None:
    assert monitor_service.parse_interval_seconds("every_15m") == 900
    assert monitor_service.parse_interval_seconds("every_1h") == 3600
    assert monitor_service.parse_interval_seconds("off") is None
    assert monitor_service.parse_interval_seconds(None) is None


def test_is_due_without_last_run() -> None:
    scenario = Scenario(id="s1", site_id="x", name="A", schedule_cron="every_1h")
    assert monitor_service.is_due(scenario) is True


def test_is_due_respects_interval() -> None:
    scenario = Scenario(
        id="s1",
        site_id="x",
        name="A",
        schedule_cron="every_1h",
        last_run_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    assert monitor_service.is_due(scenario) is False
    scenario.last_run_at = datetime.now(timezone.utc) - timedelta(hours=2)
    assert monitor_service.is_due(scenario) is True


async def _saved_scenario(client: httpx.AsyncClient) -> str:
    created = await client.post(
        "/api/v1/snapshots", json={"url": "https://shop.example.com/catalog"}
    )
    snapshot_id = created.json()["id"]
    await client.post(f"/api/v1/snapshots/{snapshot_id}/analyze", json={"use_llm": False})
    saved = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/save-as-scenario",
        json={"name": "Монитор тест", "change_note": "monitor"},
    )
    assert saved.status_code == 200, saved.text
    return saved.json()["scenario_id"]


async def test_schedule_and_check_api(client: httpx.AsyncClient) -> None:
    scenario_id = await _saved_scenario(client)

    scheduled = await client.put(
        f"/api/v1/monitor/scenarios/{scenario_id}/schedule",
        json={"interval": "every_15m"},
    )
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["interval"] == "every_15m"

    # Первый запуск — база без diff.
    first = await client.post(
        f"/api/v1/monitor/scenarios/{scenario_id}/check",
        json={"live": False},
    )
    assert first.status_code == 200, first.text
    assert first.json()["event"]["run_id"]

    # Второй — уже с сравнением.
    second = await client.post(
        f"/api/v1/monitor/scenarios/{scenario_id}/check",
        json={"live": False},
    )
    assert second.status_code == 200, second.text
    event = second.json()["event"]
    assert event["diff"] is not None
    assert "added" in event["diff"]

    events = await client.get("/api/v1/monitor/events")
    assert events.status_code == 200
    assert events.json()["total"] >= 1

    listed = await client.get("/api/v1/monitor")
    assert listed.status_code == 200
    assert any(item["scenario_id"] == scenario_id for item in listed.json()["items"])
