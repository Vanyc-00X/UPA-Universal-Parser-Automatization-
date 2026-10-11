"""Тесты системных эндпоинтов: здоровье, сведения, этапы, состояние ИИ."""

from __future__ import annotations

import httpx

from app import __version__


async def test_health_ok_when_database_available(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == __version__
    assert payload["env"] == "test"
    assert payload["uptime_s"] >= 0

    components = {component["name"]: component for component in payload["components"]}
    assert components["database"]["status"] == "ok"
    assert components["browser"]["status"] == "skipped"
    # ИИ в тестах отключён — это штатное состояние, а не ошибка.
    assert components["llm"]["status"] == "degraded"


async def test_health_available_with_version_prefix(client: httpx.AsyncClient) -> None:
    """/health продублирован под /api/v1 — им пользуются и скрипт запуска, и UI."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["app"] == "UPA"


async def test_system_info_reports_current_stage(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/system/info")

    assert response.status_code == 200
    payload = response.json()
    assert payload["app"] == "UPA"
    assert payload["stage"] == "7"
    assert "scaffold" in payload["implemented"]
    assert payload["database_path"] is not None
    assert payload["browser"]["dom_max_tokens"] > 0
    assert payload["llm"]["provider"] == "none"


async def test_features_cover_all_planned_stages(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/system/features")

    assert response.status_code == 200
    payload = response.json()
    stages = {item["stage"] for item in payload["items"]}
    assert stages == {str(number) for number in range(9)}
    scaffold = next(item for item in payload["items"] if item["key"] == "scaffold")
    assert scaffold["status"] == "done"


async def test_roadmap_has_nine_stages(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/system/roadmap")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["stages"]) == 9
    assert payload["stages"][0]["key"] == "0"
    assert payload["current_stage"] == "7"


async def test_llm_status_reports_disabled_provider(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/system/llm")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "none"
    assert payload["available"] is False
    assert payload["detail"]


async def test_unknown_route_uses_unified_error_shape(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "not_found"
    assert payload["error"]["message"]


async def test_validation_error_shape(client: httpx.AsyncClient) -> None:
    """Несуществующий маршрут с неверным методом отдаёт тот же формат ошибки."""
    response = await client.post("/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
