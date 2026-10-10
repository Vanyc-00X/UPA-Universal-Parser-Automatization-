"""Тесты эндпоинтов анализа и карты элементов."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from tests.fakes import patch_capture


@pytest.fixture(autouse=True)
def _fake_browser(settings: Settings, monkeypatch):
    """Анализ в тестах работает по подделанному снапшоту, без браузера."""
    settings.llm_provider = "none"
    return patch_capture(monkeypatch, settings)


async def make_snapshot(
    client: httpx.AsyncClient, url: str = "https://shop.example.com/catalog"
) -> str:
    response = await client.post("/api/v1/snapshots", json={"url": url})
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def test_analyze_endpoint_builds_map(client: httpx.AsyncClient) -> None:
    snapshot_id = await make_snapshot(client)

    response = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/analyze", json={"use_llm": False}
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["snapshot_id"] == snapshot_id
    assert payload["version"] == 1
    assert payload["elements"]
    # Контейнер списка ровно один: карточки товаров. Поле поиска контейнером
    # не считается, хотя в его aria-label есть слово «каталогу».
    assert payload["by_role"]["list_container"] == 1
    assert payload["by_role"]["search_input"] == 1
    assert payload["report"]
    # Обрезка оставляет в DOM три карточки, но полный размер списка известен.
    assert max(group["count"] for group in payload["repeats"]) == 12
    biggest = max(payload["repeats"], key=lambda group: group["count"])
    assert biggest["items_in_dom"] == 3
    assert biggest["collapsed"] == 9
    assert payload["llm"]["used"] is False
    assert payload["page"]["title"] == "Каталог товаров"


async def test_analyze_without_body_uses_defaults(client: httpx.AsyncClient) -> None:
    """POST без тела допустим: настройки берутся по умолчанию."""
    snapshot_id = await make_snapshot(client)

    response = await client.post(f"/api/v1/snapshots/{snapshot_id}/analyze")

    assert response.status_code == 200
    assert response.json()["elements"]


async def test_analyze_missing_snapshot(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/snapshots/nonexistent/analyze", json={})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_get_element_map_requires_analysis(client: httpx.AsyncClient) -> None:
    snapshot_id = await make_snapshot(client)

    response = await client.get(f"/api/v1/snapshots/{snapshot_id}/element-map")

    assert response.status_code == 404
    assert "не построена" in response.json()["error"]["message"]


async def test_get_element_map_after_analysis(client: httpx.AsyncClient) -> None:
    snapshot_id = await make_snapshot(client)
    await client.post(f"/api/v1/snapshots/{snapshot_id}/analyze", json={"use_llm": False})

    response = await client.get(f"/api/v1/snapshots/{snapshot_id}/element-map")

    assert response.status_code == 200
    assert response.json()["snapshot_id"] == snapshot_id
    assert response.json()["elements"]


async def test_analyze_reuse_and_force(client: httpx.AsyncClient) -> None:
    snapshot_id = await make_snapshot(client)

    first = await client.post(f"/api/v1/snapshots/{snapshot_id}/analyze", json={"use_llm": False})
    second = await client.post(f"/api/v1/snapshots/{snapshot_id}/analyze", json={"use_llm": False})
    forced = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/analyze", json={"use_llm": False, "force": True}
    )

    assert first.json()["reused"] is False
    assert second.json()["reused"] is True
    assert second.json()["version"] == 1
    assert forced.json()["reused"] is False
    assert forced.json()["version"] == 2


async def test_report_endpoint(client: httpx.AsyncClient) -> None:
    snapshot_id = await make_snapshot(client)
    await client.post(f"/api/v1/snapshots/{snapshot_id}/analyze", json={"use_llm": False})

    response = await client.get(f"/api/v1/snapshots/{snapshot_id}/report")

    assert response.status_code == 200
    payload = response.json()
    assert payload["generated_by"] == "heuristics"
    assert "Найден список" in payload["report"]
    assert "поиск" in payload["report"].lower() or "Поиск" in payload["report"]


async def test_element_maps_listing(client: httpx.AsyncClient) -> None:
    first = await make_snapshot(client, "https://a.example.com/")
    second = await make_snapshot(client, "https://b.example.com/")
    await client.post(f"/api/v1/snapshots/{first}/analyze", json={"use_llm": False})
    await client.post(f"/api/v1/snapshots/{second}/analyze", json={"use_llm": False})

    response = await client.get("/api/v1/element-maps")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert all(item["elements_count"] > 0 for item in payload["items"])


async def test_update_element_endpoint(client: httpx.AsyncClient) -> None:
    snapshot_id = await make_snapshot(client)
    await client.post(f"/api/v1/snapshots/{snapshot_id}/analyze", json={"use_llm": False})

    response = await client.patch(
        f"/api/v1/snapshots/{snapshot_id}/element-map/1",
        json={"role": "item_title", "label": "Наименование товара", "description": "Название"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["edited_by_user"] is True
    element = payload["elements"][1]
    assert element["role"] == "item_title"
    assert element["label"] == "Наименование товара"
    assert element["source"] == "user"


async def test_update_element_rejects_bad_role(client: httpx.AsyncClient) -> None:
    snapshot_id = await make_snapshot(client)
    await client.post(f"/api/v1/snapshots/{snapshot_id}/analyze", json={"use_llm": False})

    response = await client.patch(
        f"/api/v1/snapshots/{snapshot_id}/element-map/1", json={"role": "нет-такой-роли"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_update_element_out_of_range(client: httpx.AsyncClient) -> None:
    snapshot_id = await make_snapshot(client)
    await client.post(f"/api/v1/snapshots/{snapshot_id}/analyze", json={"use_llm": False})

    response = await client.patch(
        f"/api/v1/snapshots/{snapshot_id}/element-map/777", json={"role": "item_title"}
    )

    assert response.status_code == 404


async def test_roles_catalog(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/roles")

    assert response.status_code == 200
    items = response.json()["items"]
    roles = {item["role"] for item in items}
    assert "search_input" in roles
    assert "item_price" in roles
    assert all(item["label"] for item in items)
    price = next(item for item in items if item["role"] == "item_price")
    assert price["is_data"] is True
    heading = next(item for item in items if item["role"] == "heading")
    assert heading["is_data"] is False


async def test_selectors_have_candidates_and_quality(client: httpx.AsyncClient) -> None:
    """Карта должна отдавать не один селектор, а список кандидатов — задел Этапа 6."""
    snapshot_id = await make_snapshot(client)
    response = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/analyze", json={"use_llm": False}
    )
    elements = response.json()["elements"]

    search = next(item for item in elements if item["role"] == "search_input")
    assert len(search["selectors"]) >= 2
    assert search["selectors"][0]["score"] == max(
        candidate["score"] for candidate in search["selectors"]
    )
    assert search["selector_quality"] >= 0.6


async def test_analyze_endpoint_without_version_prefix(client: httpx.AsyncClient) -> None:
    """Маршруты доступны и без /api/v1 — как и остальные."""
    snapshot_id = await make_snapshot(client)
    response = await client.post(f"/snapshots/{snapshot_id}/analyze", json={"use_llm": False})
    assert response.status_code == 200
    assert response.json()["elements"]
