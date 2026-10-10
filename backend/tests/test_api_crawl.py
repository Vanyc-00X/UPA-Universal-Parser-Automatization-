"""Тесты эндпоинтов Этапа 1: сайты, снапшоты, DOM, сеть, артефакты."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from tests.fakes import patch_capture


@pytest.fixture(autouse=True)
def _fake_browser(settings: Settings, monkeypatch):
    """Ни один тест API не должен открывать настоящий браузер."""
    return patch_capture(monkeypatch, settings)


async def test_capture_snapshot_endpoint(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/snapshots", json={"url": "shop.example.com/catalog"})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["http_status"] == 200
    assert payload["title"] == "Каталог товаров"
    assert payload["network_count"] == 3
    assert payload["data_sources_count"] == 1
    assert payload["trim"]["collapsed_duplicates"] == 9
    assert payload["compression_ratio"] > 1
    assert payload["artifact_urls"]["dom-trimmed.html"].startswith("/api/v1/snapshots/")
    assert "screenshot.png" in payload["artifacts"]
    assert payload["cookie_banner_closed"] is True


async def test_capture_rejects_local_address(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/snapshots", json={"url": "http://127.0.0.1:9090/"})

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"]["host"] == "127.0.0.1"


async def test_capture_rejects_unsupported_scheme(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/snapshots", json={"url": "ftp://files.example.com"})

    assert response.status_code == 422
    assert response.json()["error"]["details"]["scheme"] == "ftp"


async def test_capture_rejects_empty_url(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/snapshots", json={"url": "   "})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_snapshot_list_and_sites(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/snapshots", json={"url": "https://shop.example.com/catalog"})
    await client.post("/api/v1/snapshots", json={"url": "https://shop.example.com/other"})

    listing = await client.get("/api/v1/snapshots")
    assert listing.status_code == 200
    assert listing.json()["total"] == 2

    sites = await client.get("/api/v1/sites")
    assert sites.status_code == 200
    site_items = sites.json()["items"]
    assert len(site_items) == 1
    assert site_items[0]["origin"] == "https://shop.example.com"
    assert site_items[0]["snapshots_count"] == 2

    filtered = await client.get("/api/v1/snapshots", params={"site_id": site_items[0]["id"]})
    assert filtered.json()["total"] == 2


async def test_snapshot_detail_dom_and_network(client: httpx.AsyncClient) -> None:
    created = (
        await client.post("/api/v1/snapshots", json={"url": "https://shop.example.com/"})
    ).json()
    snapshot_id = created["id"]

    detail = await client.get(f"/api/v1/snapshots/{snapshot_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == snapshot_id

    trimmed = await client.get(f"/api/v1/snapshots/{snapshot_id}/dom")
    assert trimmed.status_code == 200
    trimmed_payload = trimmed.json()
    assert trimmed_payload["variant"] == "trimmed"
    assert "product-card" in trimmed_payload["html"]
    assert trimmed_payload["est_tokens"] > 0

    full = await client.get(f"/api/v1/snapshots/{snapshot_id}/dom", params={"variant": "full"})
    assert full.status_code == 200
    assert full.json()["bytes"] >= trimmed_payload["bytes"]

    network = await client.get(f"/api/v1/snapshots/{snapshot_id}/network")
    assert network.status_code == 200
    assert network.json()["total"] == 3

    sources = await client.get(
        f"/api/v1/snapshots/{snapshot_id}/network", params={"data_sources_only": True}
    )
    sources_payload = sources.json()
    assert sources_payload["total"] == 1
    assert sources_payload["items"][0]["is_data_source"] is True
    assert "/api/products" in sources_payload["items"][0]["url"]


async def test_artifact_download(client: httpx.AsyncClient) -> None:
    created = (
        await client.post("/api/v1/snapshots", json={"url": "https://shop.example.com/"})
    ).json()
    snapshot_id = created["id"]

    html = await client.get(f"/api/v1/snapshots/{snapshot_id}/artifacts/dom-trimmed.html")
    assert html.status_code == 200
    assert "text/html" in html.headers["content-type"]
    assert "product-card" in html.text

    shot = await client.get(f"/api/v1/snapshots/{snapshot_id}/artifacts/screenshot.png")
    assert shot.status_code == 200
    assert shot.headers["content-type"] == "image/png"
    assert shot.content.startswith(b"\x89PNG")

    summary = await client.get(f"/api/v1/snapshots/{snapshot_id}/artifacts/summary.json")
    assert summary.status_code == 200
    assert summary.json()["data_sources"] == 1


async def test_artifact_path_traversal_is_rejected(client: httpx.AsyncClient) -> None:
    created = (
        await client.post("/api/v1/snapshots", json={"url": "https://shop.example.com/"})
    ).json()
    snapshot_id = created["id"]

    response = await client.get(f"/api/v1/snapshots/{snapshot_id}/artifacts/..%2F..%2Fetc%2Fpasswd")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_missing_snapshot_returns_unified_404(client: httpx.AsyncClient) -> None:
    for path in (
        "/api/v1/snapshots/deadbeef",
        "/api/v1/snapshots/deadbeef/dom",
        "/api/v1/snapshots/deadbeef/network",
    ):
        response = await client.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


async def test_cache_reuse_through_api(client: httpx.AsyncClient) -> None:
    first = (
        await client.post("/api/v1/snapshots", json={"url": "https://shop.example.com/catalog"})
    ).json()
    second = (
        await client.post(
            "/api/v1/snapshots",
            json={"url": "https://shop.example.com/catalog", "use_cache": True},
        )
    ).json()

    assert second["cache_hit"] is True
    assert second["id"] != first["id"]
    assert second["artifacts"] == first["artifacts"]


async def test_delete_snapshot(client: httpx.AsyncClient) -> None:
    created = (
        await client.post("/api/v1/snapshots", json={"url": "https://shop.example.com/"})
    ).json()
    snapshot_id = created["id"]

    deleted = await client.delete(f"/api/v1/snapshots/{snapshot_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    assert (await client.get(f"/api/v1/snapshots/{snapshot_id}")).status_code == 404
    assert (await client.get("/api/v1/snapshots")).json()["total"] == 0
