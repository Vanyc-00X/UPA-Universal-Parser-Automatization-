"""Тесты API self-healing (Этап 6)."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.core.db import get_session_factory
from app.editor.schema import ScenarioDefinition
from app.storage.models import ScenarioVersion
from tests.fakes import patch_capture


@pytest.fixture(autouse=True)
def _fake_browser(settings: Settings, monkeypatch):
    settings.llm_provider = "none"
    settings.heal_auto_propose = True
    return patch_capture(monkeypatch, settings)


async def _run_with_broken_title(client: httpx.AsyncClient, settings: Settings) -> str:
    created = await client.post(
        "/api/v1/snapshots", json={"url": "https://shop.example.com/catalog"}
    )
    snapshot_id = created.json()["id"]
    await client.post(f"/api/v1/snapshots/{snapshot_id}/analyze", json={"use_llm": False})
    saved = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/save-as-scenario",
        json={"name": "Healing demo"},
    )
    scenario_id = saved.json()["scenario_id"]

    # Ломаем селектор названия в текущей версии — имитация смены вёрстки.
    factory = get_session_factory()
    async with factory() as session:
        from sqlalchemy import select

        from app.storage.models import Scenario

        scenario = await session.get(Scenario, scenario_id)
        assert scenario is not None
        result = await session.execute(
            select(ScenarioVersion).where(
                ScenarioVersion.scenario_id == scenario_id,
                ScenarioVersion.version == scenario.current_version,
            )
        )
        version = result.scalar_one()
        definition = ScenarioDefinition.model_validate(version.definition)
        fields = []
        for field in definition.fields:
            if field.key == "title":
                fields.append(
                    field.model_copy(
                        update={
                            "selector": "h3.broken-title",
                            "fallback_selectors": [
                                "h3.product-card__title",
                                *field.fallback_selectors,
                            ],
                        }
                    )
                )
            else:
                fields.append(field)
        version.definition = definition.model_copy(update={"fields": fields}).model_dump(
            mode="json"
        )
        await session.commit()

    run = await client.post(
        "/api/v1/runs",
        json={
            "scenario_id": scenario_id,
            "snapshot_id": snapshot_id,
            "min_coverage": 0.95,
        },
    )
    assert run.status_code == 200, run.text
    return run.json()["id"]


async def test_journal_after_run(client: httpx.AsyncClient, settings: Settings) -> None:
    run_id = await _run_with_broken_title(client, settings)
    response = await client.get(f"/api/v1/runs/{run_id}/journal")
    assert response.status_code == 200, response.text
    steps = response.json()
    assert steps
    assert any(step["name"] == "run_created" for step in steps)


async def test_heal_proposal_and_apply(client: httpx.AsyncClient, settings: Settings) -> None:
    run_id = await _run_with_broken_title(client, settings)

    proposal = await client.get(f"/api/v1/runs/{run_id}/heal", params={"refresh": True})
    assert proposal.status_code == 200, proposal.text
    payload = proposal.json()
    assert payload["needed"] is True
    assert "title" in payload["broken_fields"]
    assert payload["patches"]
    assert payload["patches"][0]["new_selector"] == "h3.product-card__title"

    applied = await client.post(
        f"/api/v1/runs/{run_id}/heal/apply",
        json={"keys": ["title"], "change_note": "починка title"},
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["version"] >= 2
    assert body["applied"][0]["key"] == "title"

    # Повторный запуск с новой версией должен собрать название.
    rerun = await client.post(
        "/api/v1/runs",
        json={"scenario_id": body["scenario_id"], "min_coverage": 0.5},
    )
    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["items_count"] >= 1


async def test_robots_check_respect_flag(
    client: httpx.AsyncClient, settings: Settings, monkeypatch
) -> None:
    settings.respect_robots_txt = False
    response = await client.get(
        "/api/v1/robots/check",
        params={"url": "https://shop.example.com/catalog"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["allowed"] is True
    assert "отключена" in payload["detail"]
