"""Тесты API экспорта (Этап 5)."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from tests.fakes import patch_capture


@pytest.fixture(autouse=True)
def _fake_browser(settings: Settings, monkeypatch):
    settings.llm_provider = "none"
    return patch_capture(monkeypatch, settings)


async def _run_ready(client: httpx.AsyncClient) -> tuple[str, str]:
    created = await client.post(
        "/api/v1/snapshots", json={"url": "https://shop.example.com/catalog"}
    )
    snapshot_id = created.json()["id"]
    await client.post(f"/api/v1/snapshots/{snapshot_id}/analyze", json={"use_llm": False})
    saved = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/save-as-scenario",
        json={"name": "Экспорт каталога"},
    )
    scenario_id = saved.json()["scenario_id"]
    run = await client.post(
        "/api/v1/runs",
        json={"scenario_id": scenario_id, "snapshot_id": snapshot_id, "min_coverage": 0.0},
    )
    assert run.status_code == 200, run.text
    return run.json()["id"], scenario_id


async def test_export_csv_and_xlsx(client: httpx.AsyncClient) -> None:
    run_id, _ = await _run_ready(client)

    csv_response = await client.get(f"/api/v1/runs/{run_id}/export", params={"format": "csv"})
    assert csv_response.status_code == 200, csv_response.text
    assert "text/csv" in csv_response.headers["content-type"]
    assert "attachment" in csv_response.headers["content-disposition"]
    assert len(csv_response.content) > 10

    xlsx = await client.get(f"/api/v1/runs/{run_id}/export", params={"format": "xlsx"})
    assert xlsx.status_code == 200, xlsx.text
    assert xlsx.content[:2] == b"PK"


async def test_export_meta_and_artifact_download(client: httpx.AsyncClient) -> None:
    run_id, _ = await _run_ready(client)
    meta = await client.get(f"/api/v1/runs/{run_id}/export/meta", params={"format": "json"})
    assert meta.status_code == 200, meta.text
    payload = meta.json()
    assert payload["records"] >= 1
    assert payload["artifact_id"]

    listed = await client.get(f"/api/v1/runs/{run_id}/artifacts")
    assert listed.status_code == 200
    assert any(item["id"] == payload["artifact_id"] for item in listed.json())

    downloaded = await client.get(payload["download_url"])
    assert downloaded.status_code == 200
    assert b"records" in downloaded.content or b"{" in downloaded.content


async def test_spec_markdown_for_run_and_scenario(client: httpx.AsyncClient) -> None:
    run_id, scenario_id = await _run_ready(client)

    run_spec = await client.get(f"/api/v1/runs/{run_id}/spec")
    assert run_spec.status_code == 200, run_spec.text
    assert "Техническое задание" in run_spec.json()["markdown"]

    scenario_spec = await client.get(f"/api/v1/scenarios/{scenario_id}/spec")
    assert scenario_spec.status_code == 200, scenario_spec.text
    assert scenario_spec.json()["scenario_id"] == scenario_id

    file_spec = await client.get(f"/api/v1/runs/{run_id}/spec.md")
    assert file_spec.status_code == 200
    assert "text/markdown" in file_spec.headers["content-type"]


async def test_run_diff_with_previous(client: httpx.AsyncClient) -> None:
    first_id, scenario_id = await _run_ready(client)
    second = await client.post(
        "/api/v1/runs",
        json={"scenario_id": scenario_id, "min_coverage": 0.0},
    )
    assert second.status_code == 200, second.text
    second_id = second.json()["id"]

    diff = await client.get(f"/api/v1/runs/{second_id}/diff")
    assert diff.status_code == 200, diff.text
    payload = diff.json()
    assert payload["previous_run_id"] == first_id
    assert payload["current_run_id"] == second_id
