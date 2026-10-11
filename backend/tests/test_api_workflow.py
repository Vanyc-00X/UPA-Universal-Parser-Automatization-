"""Тесты API воркфлоу (Этап 7)."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from tests.fakes import build_form_html, patch_capture

FORM_URL = "https://forms.example.com/order"


@pytest.fixture(autouse=True)
def _fake_browser(settings: Settings, monkeypatch):
    settings.llm_provider = "none"
    return patch_capture(monkeypatch, settings, html=build_form_html())


def _workflow_body() -> dict:
    return {
        "url": FORM_URL,
        "title": "Заявка",
        "steps": [
            {"type": "goto", "url": FORM_URL},
            {"type": "fill", "selector": "#field-name", "value": "{{name}}"},
            {"type": "fill", "selector": "#field-email", "value": "{{email}}"},
            {"type": "select", "selector": "#field-city", "value": "{{city}}"},
            {"type": "check", "selector": "#field-agree"},
            {"type": "assert_text", "value": "Заполните все поля"},
            {"type": "extract", "selector": "h1", "key": "heading"},
            {
                "type": "click",
                "selector": "#btn-submit",
                "confirm_required": True,
                "note": "отправка",
            },
        ],
        "max_rows": 100,
        "require_confirm_submit": True,
    }


async def _prepare(
    client: httpx.AsyncClient,
) -> tuple[str, str]:
    created = await client.post("/api/v1/snapshots", json={"url": FORM_URL})
    assert created.status_code == 200, created.text
    snapshot = created.json()
    site_id = snapshot["site_id"]
    snapshot_id = snapshot["id"]

    saved = await client.post(
        "/api/v1/workflows",
        json={
            "site_id": site_id,
            "name": "Форма заявки",
            "workflow": _workflow_body(),
        },
    )
    assert saved.status_code == 200, saved.text
    return snapshot_id, saved.json()["scenario_id"]


async def test_save_get_and_dry_run(client: httpx.AsyncClient) -> None:
    snapshot_id, scenario_id = await _prepare(client)

    got = await client.get(f"/api/v1/workflows/{scenario_id}")
    assert got.status_code == 200
    body = got.json()
    assert body["kind"] == "form_fill"
    assert body["workflow"]["title"] == "Заявка"
    assert body["summary"]["steps"] == 8

    run = await client.post(
        f"/api/v1/workflows/{scenario_id}/dry-run",
        json={
            "snapshot_id": snapshot_id,
            "rows": [
                {"name": "Иван", "email": "a@b.c", "city": "msk"},
                {"name": "Мария", "email": "m@x.y", "city": "spb"},
            ],
        },
    )
    assert run.status_code == 200, run.text
    payload = run.json()
    assert payload["mode"] == "dry_run"
    assert payload["run_id"]
    assert payload["report"]["total"] == 2
    assert payload["report"]["succeeded"] == 2
    assert payload["report"]["failed"] == 0
    assert payload["report"]["rows"][0]["extracted"]["heading"] == "Форма заявки"
    assert payload["report"]["rows"][0]["skipped"]


async def test_dry_run_from_csv(client: httpx.AsyncClient) -> None:
    snapshot_id, scenario_id = await _prepare(client)
    csv_text = "name,email,city\nПётр,p@e.c,msk\n"
    run = await client.post(
        f"/api/v1/workflows/{scenario_id}/dry-run",
        json={"snapshot_id": snapshot_id, "csv_text": csv_text, "persist": False},
    )
    assert run.status_code == 200, run.text
    assert run.json()["run_id"] is None
    assert run.json()["report"]["succeeded"] == 1


async def test_preview_dry_run_without_save(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/v1/snapshots", json={"url": FORM_URL})
    snapshot_id = created.json()["id"]
    response = await client.post(
        "/api/v1/workflows/preview-dry-run",
        json={
            "snapshot_id": snapshot_id,
            "workflow": _workflow_body(),
            "rows": [{"name": "А", "email": "a@a.a", "city": "msk"}],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["report"]["succeeded"] == 1


async def test_export_script(client: httpx.AsyncClient) -> None:
    _, scenario_id = await _prepare(client)
    response = await client.post(
        f"/api/v1/workflows/{scenario_id}/export-script",
        json={"rows": [{"name": "Иван", "email": "a@b.c", "city": "msk"}]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["filename"].endswith(".py")
    assert "sync_playwright" in payload["script"]
    assert "Иван" in payload["script"]

    plain = await client.get(f"/api/v1/workflows/{scenario_id}/export-script.txt")
    assert plain.status_code == 200
    assert "page.fill" in plain.text


async def test_parse_csv_endpoint(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/workflows/parse-csv",
        json={"csv_text": "a,b\n1,2\n3,4\n"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["columns"] == ["a", "b"]


async def test_live_run_requires_confirm(client: httpx.AsyncClient) -> None:
    _, scenario_id = await _prepare(client)
    response = await client.post(
        f"/api/v1/workflows/{scenario_id}/run",
        json={"rows": [{"name": "Иван", "email": "a@b.c", "city": "msk"}]},
    )
    assert response.status_code == 422
    detail = response.json()["error"]["message"]
    assert "опасн" in detail.lower() or "confirm" in detail.lower()


async def test_preview_steps(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/workflows/preview-steps", json=_workflow_body())
    assert response.status_code == 200
    steps = response.json()
    assert len(steps) == 8
    assert any("page.fill" in step["playwright"] for step in steps)
    assert steps[-1]["dangerous"] is True


async def test_from_recording_and_humanize(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/workflows/from-recording",
        json={
            "url": FORM_URL,
            "title": "Из записи",
            "humanize": True,
            "events": [
                {"type": "goto", "url": FORM_URL},
                {"type": "fill", "selector": "#field-name", "value": "Иван", "name": "name"},
                {"type": "fill", "selector": "#field-email", "value": "a@b.c"},
                {
                    "type": "click",
                    "selector": "#btn-submit",
                    "text": "Отправить",
                    "input_type": "submit",
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    workflow = response.json()["workflow"]
    assert workflow["steps"][1]["value"] == "{{name}}"
    assert workflow["steps"][-1]["confirm_required"] is True

    humanized = await client.post(
        "/api/v1/workflows/humanize",
        json={"workflow": workflow},
    )
    assert humanized.status_code == 200
    assert "summary" in humanized.json()


async def test_parse_xlsx_endpoint(client: httpx.AsyncClient) -> None:
    from io import BytesIO

    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["name", "city"])
    sheet.append(["Иван", "msk"])
    buffer = BytesIO()
    workbook.save(buffer)
    response = await client.post(
        "/api/v1/workflows/parse-xlsx",
        files={
            "file": (
                "params.xlsx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] == 1
    assert payload["rows"][0]["name"] == "Иван"
