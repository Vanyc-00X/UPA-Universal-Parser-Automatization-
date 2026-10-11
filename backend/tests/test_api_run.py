"""Тесты API движка извлечения (Этап 4)."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from tests.fakes import patch_capture


@pytest.fixture(autouse=True)
def _fake_browser(settings: Settings, monkeypatch):
    settings.llm_provider = "none"
    return patch_capture(monkeypatch, settings)


async def _saved_scenario(client: httpx.AsyncClient) -> tuple[str, str]:
    """Снапшот → карта → сценарий. Возвращает (scenario_id, snapshot_id)."""
    created = await client.post(
        "/api/v1/snapshots", json={"url": "https://shop.example.com/catalog"}
    )
    assert created.status_code == 200, created.text
    snapshot_id = created.json()["id"]

    analyzed = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/analyze", json={"use_llm": False}
    )
    assert analyzed.status_code == 200, analyzed.text

    draft = await client.get(f"/api/v1/snapshots/{snapshot_id}/draft")
    assert draft.status_code == 200, draft.text
    assert draft.json()["validation"]["ok"] is True

    saved = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/save-as-scenario",
        json={"name": "Каталог тест", "change_note": "этап 4"},
    )
    assert saved.status_code == 200, saved.text
    return saved.json()["scenario_id"], snapshot_id


async def test_check_value_normalizes_price(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/runs/check-value",
        json={"value": "1 249,00 ₽", "kind": "auto"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["kind"] == "price"
    assert payload["value"] == 1249.0


async def test_preview_definition_returns_records(client: httpx.AsyncClient) -> None:
    _, snapshot_id = await _saved_scenario(client)
    draft = await client.get(f"/api/v1/snapshots/{snapshot_id}/draft")
    definition = draft.json()["draft"]

    response = await client.post(
        "/api/v1/runs/preview-definition",
        json={"definition": definition, "snapshot_id": snapshot_id, "limit": 5},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["records"]
    assert payload["report"]["records"] == len(payload["records"])
    assert payload["report_text"]


async def test_create_run_collects_items(client: httpx.AsyncClient) -> None:
    scenario_id, snapshot_id = await _saved_scenario(client)

    response = await client.post(
        "/api/v1/runs",
        json={"scenario_id": scenario_id, "snapshot_id": snapshot_id, "min_coverage": 0.5},
    )
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] in {"succeeded", "failed"}
    assert run["items_count"] >= 1
    assert run["report"] is not None
    assert run["scenario_name"] == "Каталог тест"

    items = await client.get(f"/api/v1/runs/{run['id']}/items")
    assert items.status_code == 200, items.text
    payload = items.json()
    assert payload["total"] == run["items_count"]
    assert payload["items"]
    first = payload["items"][0]["data"]
    assert any(key in first for key in ("title", "price", "url"))


async def test_list_and_delete_run(client: httpx.AsyncClient) -> None:
    scenario_id, snapshot_id = await _saved_scenario(client)
    created = await client.post(
        "/api/v1/runs",
        json={"scenario_id": scenario_id, "snapshot_id": snapshot_id, "min_coverage": 0.0},
    )
    run_id = created.json()["id"]

    listed = await client.get("/api/v1/runs", params={"scenario_id": scenario_id})
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    assert any(item["id"] == run_id for item in listed.json()["items"])

    deleted = await client.delete(f"/api/v1/runs/{run_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    missing = await client.get(f"/api/v1/runs/{run_id}")
    assert missing.status_code == 404


async def test_preview_scenario_endpoint(client: httpx.AsyncClient) -> None:
    scenario_id, _ = await _saved_scenario(client)
    response = await client.post(
        "/api/v1/runs/preview-scenario",
        json={"scenario_id": scenario_id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["scenario_id"] == scenario_id
    assert response.json()["records"]


async def test_run_unknown_scenario(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/runs", json={"scenario_id": "missing"})
    assert response.status_code == 404
