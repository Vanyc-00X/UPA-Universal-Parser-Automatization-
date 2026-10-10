"""Тесты прикладного слоя снапшотов: URL, съёмка, артефакты, кэш."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.db import session_scope
from app.core.errors import NotFoundError, ValidationError
from app.crawler import service as crawl
from app.crawler import store
from app.crawler.browser import RawSnapshot
from tests.fakes import build_html, patch_capture


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("example.com", "https://example.com/"),
        ("https://example.com", "https://example.com/"),
        ("https://Example.COM/catalog?page=2", "https://example.com/catalog?page=2"),
        ("http://example.com/a/b#frag", "http://example.com/a/b"),
        ("  https://example.com/x  ", "https://example.com/x"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert crawl.normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "ftp://example.com", "https://"])
def test_normalize_url_rejects_bad_input(raw: str) -> None:
    with pytest.raises(ValidationError):
        crawl.normalize_url(raw)


def test_local_addresses_are_blocked_by_default() -> None:
    with pytest.raises(ValidationError):
        crawl.check_host_allowed("http://127.0.0.1:8080/admin")
    with pytest.raises(ValidationError):
        crawl.check_host_allowed("http://192.168.1.10/")
    # Явное разрешение снимает запрет.
    crawl.check_host_allowed("http://127.0.0.1:8080/admin", allow_local=True)


def test_origin_of() -> None:
    assert crawl.origin_of("https://shop.example.com/catalog?page=1") == "https://shop.example.com"


async def test_capture_saves_snapshot_and_artifacts(settings: Settings, monkeypatch) -> None:
    patch_capture(monkeypatch, settings)

    async with session_scope() as db:
        outcome = await crawl.capture(db, settings, "shop.example.com/catalog")

    snapshot = outcome.snapshot
    assert outcome.reused is False
    assert snapshot.status.value == "ready"
    assert snapshot.http_status == 200
    assert snapshot.title == "Каталог товаров"
    assert snapshot.lang == "ru"
    assert snapshot.dom_hash
    assert snapshot.est_tokens and snapshot.est_tokens > 0
    assert snapshot.collapsed_blocks == 9

    # Артефакты действительно лежат на диске.
    html = store.load_text(settings, snapshot.id, store.PAGE_HTML)
    trimmed = store.load_text(settings, snapshot.id, store.TRIMMED_HTML)
    network = store.load_json(settings, snapshot.id, store.NETWORK_JSON)
    summary = store.load_json(settings, snapshot.id, store.SUMMARY_JSON)

    assert html is not None and "<!DOCTYPE html>" in html
    assert trimmed is not None and "product-card" in trimmed
    assert network is not None and network["count"] == 3
    assert summary is not None and summary["data_sources"] == 1

    # Исходный HTML больше обрезанного — обрезка работает.
    assert snapshot.html_bytes > (snapshot.trimmed_bytes or 0)


async def test_capture_creates_site_once(settings: Settings, monkeypatch) -> None:
    patch_capture(monkeypatch, settings)

    async with session_scope() as db:
        first = await crawl.capture(db, settings, "https://shop.example.com/catalog")
        second = await crawl.capture(db, settings, "https://shop.example.com/other")
        sites = await crawl.list_sites(db)

    assert first.snapshot.site_id == second.snapshot.site_id
    assert len(sites) == 1
    assert sites[0].origin == "https://shop.example.com"


async def test_capture_with_cache_reuses_artifacts(settings: Settings, monkeypatch) -> None:
    """Одинаковый DOM → второй снапшот переиспользует файлы первого."""
    patch_capture(monkeypatch, settings)

    async with session_scope() as db:
        first = await crawl.capture(db, settings, "https://shop.example.com/catalog")
        second = await crawl.capture(
            db, settings, "https://shop.example.com/catalog", use_cache=True
        )

    assert second.reused is True
    assert second.snapshot.artifacts == first.snapshot.artifacts
    assert second.snapshot.meta["cache_hit"] is True
    assert second.snapshot.meta["cached_snapshot_id"] == first.snapshot.id
    assert second.snapshot.id != first.snapshot.id
    # Артефакты первого снапшота не перезаписываются и остаются на месте.
    assert store.load_text(settings, first.snapshot.id, store.PAGE_HTML) is not None


async def test_failed_capture_is_recorded(settings: Settings, monkeypatch) -> None:
    async def _boom(_settings: Settings, _url: str) -> RawSnapshot:
        raise RuntimeError("сеть недоступна")

    monkeypatch.setattr("app.crawler.browser.capture_page", _boom)

    with pytest.raises(RuntimeError):
        async with session_scope() as db:
            await crawl.capture(db, settings, "https://shop.example.com/catalog")

    # Сбой не должен «зависать» в статусе running.
    async with session_scope() as db:
        snapshots = await crawl.list_snapshots(db)
    assert len(snapshots) == 1
    assert snapshots[0].status.value == "failed"
    assert "сеть недоступна" in (snapshots[0].error or "")


async def test_get_snapshot_not_found(settings: Settings) -> None:
    async with session_scope() as db:
        with pytest.raises(NotFoundError):
            await crawl.get_snapshot(db, "no-such-id")


async def test_delete_snapshot_removes_artifacts(settings: Settings, monkeypatch) -> None:
    patch_capture(monkeypatch, settings)
    async with session_scope() as db:
        outcome = await crawl.capture(db, settings, "https://shop.example.com/catalog")
        snapshot_id = outcome.snapshot.id

    assert store.snapshot_dir(settings, snapshot_id).exists()

    async with session_scope() as db:
        await crawl.delete_snapshot(db, settings, snapshot_id)

    assert not store.snapshot_dir(settings, snapshot_id).exists()


async def test_raw_from_artifacts_round_trip(settings: Settings, monkeypatch) -> None:
    """Снапшот можно поднять с диска в память — основа анализа из кэша."""
    patch_capture(monkeypatch, settings)
    async with session_scope() as db:
        outcome = await crawl.capture(db, settings, "https://shop.example.com/catalog")

    async with session_scope() as db:
        stored = await crawl.get_snapshot(db, outcome.snapshot.id)
        restored = crawl.raw_from_artifacts(settings, stored)

    assert restored is not None
    assert restored.dom_hash == outcome.raw.dom_hash
    assert restored.title == "Каталог товаров"
    assert len(restored.network) == 3
    assert restored.data_sources[0].body is not None
    assert restored.screenshot is not None


async def test_raw_from_artifacts_returns_none_when_files_missing(
    settings: Settings, monkeypatch
) -> None:
    patch_capture(monkeypatch, settings)
    async with session_scope() as db:
        outcome = await crawl.capture(db, settings, "https://shop.example.com/catalog")

    store.delete_snapshot_artifacts(settings, outcome.snapshot.id)

    async with session_scope() as db:
        stored = await crawl.get_snapshot(db, outcome.snapshot.id)
        assert crawl.raw_from_artifacts(settings, stored) is None


async def test_capture_of_large_page_is_trimmed(settings: Settings, monkeypatch) -> None:
    settings.dom_max_tokens = 400
    patch_capture(monkeypatch, settings, html=build_html(cards=150))

    async with session_scope() as db:
        outcome = await crawl.capture(db, settings, "https://shop.example.com/catalog")

    assert outcome.raw.trimmed.stats.truncated is True
    assert (outcome.snapshot.est_tokens or 0) <= 600
