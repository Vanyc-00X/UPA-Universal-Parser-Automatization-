"""Тесты шаблонов и ensure LLM (Этап 8)."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.packaging import llm_ensure


async def test_templates_list_and_detail(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/templates")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) >= 3
    assert {item["kind"] for item in items} >= {"collection", "form_fill"}

    detail = await client.get(f"/api/v1/templates/{items[0]['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["sample_csv"]
    assert body["definition"] or body["workflow"]


async def test_templates_filter_by_kind(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/templates", params={"kind": "form_fill"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    assert all(item["kind"] == "form_fill" for item in items)


async def test_template_not_found(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/templates/no-such-template")
    assert response.status_code == 404


async def test_ensure_llm_disabled_provider(client: httpx.AsyncClient, settings: Settings) -> None:
    settings.llm_provider = "none"
    response = await client.post("/api/v1/system/llm/ensure", json={"pull": False})
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["action"] == "disabled"


async def test_ensure_ollama_needs_pull(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    settings.llm_provider = "ollama"
    settings.ollama_model = "qwen2.5:7b"

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"models": [{"name": "other:latest"}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str):
            return FakeResponse()

    monkeypatch.setattr(llm_ensure.httpx, "AsyncClient", FakeClient)
    result = await llm_ensure.ensure_ollama_model(settings, pull=False)
    assert result["available"] is True
    assert result["action"] == "needs_pull"


async def test_packaging_feature_marked_done(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/system/features")
    assert response.status_code == 200
    packaging = next(item for item in response.json()["items"] if item["key"] == "packaging")
    assert packaging["status"] == "done"
    form_fill = next(item for item in response.json()["items"] if item["key"] == "form_fill")
    assert form_fill["status"] == "done"
