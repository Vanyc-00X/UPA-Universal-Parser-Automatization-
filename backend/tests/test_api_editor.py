"""Тесты эндпоинтов визуального редактора (Этап 3)."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from tests.fakes import patch_capture


@pytest.fixture(autouse=True)
def _fake_browser(settings: Settings, monkeypatch):
    """Редактор в тестах работает по подделанному снапшоту, без браузера."""
    settings.llm_provider = "none"
    return patch_capture(monkeypatch, settings)


async def prepared_snapshot(
    client: httpx.AsyncClient, url: str = "https://shop.example.com/catalog"
) -> str:
    """Снапшот с готовой картой элементов."""
    created = await client.post("/api/v1/snapshots", json={"url": url})
    assert created.status_code == 200, created.text
    snapshot_id = created.json()["id"]
    analyzed = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/analyze", json={"use_llm": False}
    )
    assert analyzed.status_code == 200, analyzed.text
    return snapshot_id


# --- Инспектор ---------------------------------------------------------------


async def test_inspector_returns_nodes_and_page(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)

    response = await client.get(f"/api/v1/snapshots/{snapshot_id}/inspector")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["snapshot_id"] == snapshot_id
    assert payload["nodes"]
    assert payload["total"] == len(payload["nodes"])
    assert payload["page"]["width"] > 0
    assert payload["selectors"]

    node = payload["nodes"][0]
    assert node["node_id"]
    assert node["tag"]
    assert node["box"]["height"] > 0
    # Хотя бы один узел отмечен как совпавший с селектором карты.
    assert any(item["matched_by"] for item in payload["nodes"])


async def test_inspector_respects_max_nodes(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)

    response = await client.get(
        f"/api/v1/snapshots/{snapshot_id}/inspector", params={"max_nodes": 20}
    )
    assert response.status_code == 200
    assert len(response.json()["nodes"]) <= 20


async def test_inspector_requires_element_map(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/v1/snapshots", json={"url": "https://a.example.com/"})
    snapshot_id = created.json()["id"]

    response = await client.get(f"/api/v1/snapshots/{snapshot_id}/inspector")
    assert response.status_code == 404
    assert "не построена" in response.json()["error"]["message"]


# --- Проверка селекторов -----------------------------------------------------


async def test_selector_test_reports_matches(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)

    response = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/element-selector",
        json={"selector": "div.product-card"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valid"] is True
    # Обрезка оставила в DOM три карточки.
    assert payload["count"] == 3
    assert payload["samples"]
    assert payload["samples"][0]["tag"] == "div"


async def test_selector_test_reports_empty_and_invalid(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)

    empty = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/element-selector",
        json={"selector": ".no-such-class"},
    )
    assert empty.status_code == 200
    assert empty.json()["count"] == 0
    assert empty.json()["valid"] is True

    invalid = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/element-selector",
        json={"selector": "div:has(> span)"},
    )
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is False
    assert invalid.json()["error"]


# --- Черновик ----------------------------------------------------------------


async def test_draft_state_from_element_map(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)

    response = await client.get(f"/api/v1/snapshots/{snapshot_id}/draft")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["changed"] is False
    assert payload["baseline"]["fields"]
    assert payload["draft"]["fields"]
    assert payload["validation"]["fields"]
    assert payload["items_expected"] >= 3
    # Обрезка оставила в DOM несколько показательных карточек.
    assert payload["items_in_dom"] == 3
    assert payload["collapsed"] >= 1
    keys = {field["key"] for field in payload["draft"]["fields"]}
    assert "title" in keys
    assert "price" in keys


async def test_draft_put_and_reset(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)
    state = (await client.get(f"/api/v1/snapshots/{snapshot_id}/draft")).json()

    definition = state["draft"]
    definition["title"] = "Мой сценарий"
    definition["fields"] = definition["fields"][:2]

    saved = await client.put(
        f"/api/v1/snapshots/{snapshot_id}/draft", json={"definition": definition}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["draft"]["title"] == "Мой сценарий"
    assert saved.json()["changed"] is True
    assert len(saved.json()["draft"]["fields"]) == 2

    reset = await client.post(f"/api/v1/snapshots/{snapshot_id}/draft/reset")
    assert reset.status_code == 200
    assert reset.json()["changed"] is False
    assert len(reset.json()["draft"]["fields"]) > 2


async def test_draft_put_rejects_invalid_definition(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)
    state = (await client.get(f"/api/v1/snapshots/{snapshot_id}/draft")).json()

    definition = state["draft"]
    definition["fields"] = [
        {"key": "t", "title": "Первое", "selector": "h1"},
        {"key": "t", "title": "Дубликат", "selector": "h2"},
    ]
    response = await client.put(
        f"/api/v1/snapshots/{snapshot_id}/draft", json={"definition": definition}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_suggest_key_endpoint(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)

    response = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/suggest-key",
        params={"title": "Артикул товара"},
    )

    assert response.status_code == 200
    assert response.json()["key"] == "artikul_tovara"


async def test_suggest_key_avoids_collisions(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)
    first = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/suggest-key", params={"title": "Название"}
    )
    added = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/fields",
        json={
            "key": first.json()["key"],
            "title": "Название",
            "selector": "h3.product-card__title",
        },
    )
    assert added.status_code == 200

    second = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/suggest-key", params={"title": "Название"}
    )
    assert second.json()["key"] != first.json()["key"]


# --- Поля --------------------------------------------------------------------


async def test_field_lifecycle(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)

    added = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/fields",
        json={
            "title": "Артикул",
            "selector": "div.product-card",
            "strategy": "attribute",
            "attribute": "data-sku",
            "required": True,
        },
    )
    assert added.status_code == 200, added.text
    assert any(field["key"] == "artikul" for field in added.json()["draft"]["fields"])
    assert any(field["required"] for field in added.json()["draft"]["fields"])

    updated = await client.patch(
        f"/api/v1/snapshots/{snapshot_id}/draft/fields",
        json={"key": "artikul", "title": "Артикул поставщика", "required": False},
    )
    assert updated.status_code == 200
    field = next(item for item in updated.json()["draft"]["fields"] if item["key"] == "artikul")
    assert field["title"] == "Артикул поставщика"
    assert field["required"] is False

    removed = await client.delete(f"/api/v1/snapshots/{snapshot_id}/draft/fields/artikul")
    assert removed.status_code == 200
    assert all(item["key"] != "artikul" for item in removed.json()["draft"]["fields"])


async def test_field_validation_errors(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)

    # Атрибутная стратегия без имени атрибута — ошибка.
    bad = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/fields",
        json={"title": "Плохое", "selector": "div", "strategy": "attribute"},
    )
    assert bad.status_code == 422

    # Обновление несуществующего поля.
    missing = await client.patch(
        f"/api/v1/snapshots/{snapshot_id}/draft/fields",
        json={"key": "no-such", "title": "Нет"},
    )
    assert missing.status_code == 422

    # Удаление несуществующего поля.
    gone = await client.delete(f"/api/v1/snapshots/{snapshot_id}/draft/fields/no-such")
    assert gone.status_code == 404


async def test_field_order(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)
    state = (await client.get(f"/api/v1/snapshots/{snapshot_id}/draft")).json()
    order = [field["key"] for field in reversed(state["draft"]["fields"])]

    response = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/order", json={"order": order}
    )

    assert response.status_code == 200
    assert [field["key"] for field in response.json()["draft"]["fields"]] == order


async def test_field_order_with_unknown_key(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)
    response = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/order", json={"order": ["no-such"]}
    )
    assert response.status_code == 404


async def test_add_field_from_element(client: httpx.AsyncClient) -> None:
    """Основной способ ручного добавления: выбрали элемент — получили поле."""
    snapshot_id = await prepared_snapshot(client)
    inspector = (await client.get(f"/api/v1/snapshots/{snapshot_id}/inspector")).json()
    price_node = next(
        node for node in inspector["nodes"] if "product-card__price" in node["classes"]
    )

    response = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/fields/from-element",
        json={"node_id": price_node["node_id"], "title": "Цена со скидкой"},
    )

    assert response.status_code == 200, response.text
    field = next(
        item for item in response.json()["draft"]["fields"] if item["title"] == "Цена со скидкой"
    )
    assert field["selector"]
    assert field["key"]


async def test_add_field_from_element_with_selector(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)

    response = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/fields/from-element",
        json={"selector": "a.product-card__link", "title": "Ссылка"},
    )

    assert response.status_code == 200
    field = next(item for item in response.json()["draft"]["fields"] if item["title"] == "Ссылка")
    # Ссылка — берём href, а не текст.
    assert field["strategy"] == "attribute"
    assert field["attribute"] == "href"


async def test_add_field_from_unknown_element(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)
    response = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/fields/from-element",
        json={"node_id": "nope"},
    )
    assert response.status_code == 422


# --- План, предпросмотр, сохранение ------------------------------------------


async def test_update_plan_mode(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)

    response = await client.patch(
        f"/api/v1/snapshots/{snapshot_id}/draft/plan", json={"plan_mode": "single"}
    )

    assert response.status_code == 200, response.text
    plan = response.json()["draft"]["plan"]
    assert plan["mode"] == "single"
    # В одиночном режиме контейнер списка не нужен.
    assert plan["container_selector"] is None


async def test_update_pagination(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)

    response = await client.patch(
        f"/api/v1/snapshots/{snapshot_id}/draft/plan",
        json={
            "pagination": {
                "kind": "url_template",
                "url_template": "https://shop.example.com/catalog?page={page}",
                "max_pages": 3,
                "delay_ms": 200,
            }
        },
    )

    assert response.status_code == 200, response.text
    pagination = response.json()["draft"]["pagination"]
    assert pagination["kind"] == "url_template"
    assert pagination["max_pages"] == 3


async def test_pagination_template_requires_placeholder(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)
    response = await client.patch(
        f"/api/v1/snapshots/{snapshot_id}/draft/plan",
        json={"pagination": {"kind": "url_template", "url_template": "https://a.com/catalog"}},
    )
    assert response.status_code == 422


async def test_preview_shows_values(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)

    response = await client.get(f"/api/v1/snapshots/{snapshot_id}/draft/preview")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mode"] == "list"
    assert payload["items_in_dom"] == 3
    assert payload["fields"]
    price = next(field for field in payload["fields"] if field["key"] == "price")
    assert price["matches"] == 3
    assert price["values"]
    assert "₽" in price["values"][0] or price["values"][0]


async def test_save_as_scenario(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)

    response = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/save-as-scenario",
        json={"name": "Каталог магазина", "change_note": "первая версия"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["scenario_name"] == "Каталог магазина"
    assert payload["version"] == 1
    assert payload["fields"] > 0
    assert payload["definition"]["title"] == "Каталог магазина"

    # Второе сохранение добавляет версию.
    second = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/save-as-scenario",
        json={
            "name": "Каталог магазина",
            "scenario_id": payload["scenario_id"],
            "change_note": "правка",
        },
    )
    assert second.status_code == 200
    assert second.json()["version"] == 2
    assert second.json()["scenario_id"] == payload["scenario_id"]


async def test_save_scenario_rejected_when_not_ready(client: httpx.AsyncClient) -> None:
    """Сценарий с неработающим селектором сохранять нельзя."""
    snapshot_id = await prepared_snapshot(client)
    state = (await client.get(f"/api/v1/snapshots/{snapshot_id}/draft")).json()

    definition = state["draft"]
    definition["fields"] = definition["fields"] + [
        {"key": "broken", "title": "Сломанное поле", "selector": ".no-such-element"}
    ]
    await client.put(f"/api/v1/snapshots/{snapshot_id}/draft", json={"definition": definition})

    response = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/save-as-scenario",
        json={"name": "Плохой сценарий"},
    )

    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert any("Сломанное поле" in problem for problem in details["problems"])


async def test_scenarios_listing_and_versions(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)
    saved = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/save-as-scenario",
        json={"name": "Сценарий А"},
    )
    scenario_id = saved.json()["scenario_id"]

    listing = await client.get("/api/v1/scenarios")
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["total"] == 1
    assert payload["items"][0]["name"] == "Сценарий А"
    assert payload["items"][0]["current_version"] == 1
    assert payload["items"][0]["definition"]["fields"]

    versions = await client.get(f"/api/v1/scenarios/{scenario_id}/versions")
    assert versions.status_code == 200
    assert [item["version"] for item in versions.json()] == [1]


async def test_delete_scenario(client: httpx.AsyncClient) -> None:
    snapshot_id = await prepared_snapshot(client)
    saved = await client.post(
        f"/api/v1/snapshots/{snapshot_id}/draft/save-as-scenario", json={"name": "Удаляемый"}
    )
    scenario_id = saved.json()["scenario_id"]

    deleted = await client.delete(f"/api/v1/scenarios/{scenario_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    assert (await client.get("/api/v1/scenarios")).json()["total"] == 0
    assert (await client.get(f"/api/v1/scenarios/{scenario_id}/versions")).status_code == 404


async def test_editor_endpoints_without_version_prefix(client: httpx.AsyncClient) -> None:
    """Маршруты редактора доступны и без /api/v1 — как и остальные."""
    snapshot_id = await prepared_snapshot(client)

    inspector = await client.get(f"/snapshots/{snapshot_id}/inspector")
    assert inspector.status_code == 200

    draft = await client.get(f"/snapshots/{snapshot_id}/draft")
    assert draft.status_code == 200


async def test_editor_missing_snapshot(client: httpx.AsyncClient) -> None:
    for path in (
        "/api/v1/snapshots/nope/inspector",
        "/api/v1/snapshots/nope/draft",
        "/api/v1/snapshots/nope/draft/preview",
    ):
        response = await client.get(path)
        assert response.status_code == 404, path
