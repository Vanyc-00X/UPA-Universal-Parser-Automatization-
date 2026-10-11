"""Тесты доставки результатов во внешние приёмники."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, text

from app.exporters import destinations
from app.exporters.destinations import DestinationKind, deliver
from app.exporters.table import ExportTable


def _table() -> ExportTable:
    return ExportTable(
        columns=["title", "price"],
        titles={"title": "Название", "price": "Цена"},
        rows=[{"title": "A", "price": 10}, {"title": "B", "price": 20}],
        meta={"run_id": "run123", "scenario_name": "demo"},
    )


@pytest.mark.asyncio
async def test_deliver_webhook_posts_json(monkeypatch) -> None:
    captured: dict = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"ok": True}

        @property
        def text(self):
            return '{"ok": true}'

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    result = await deliver(
        _table(),
        kind=DestinationKind.WEBHOOK,
        target="https://hooks.example.com/upa",
        options={"headers": {"X-Token": "secret"}},
    )
    assert result.ok
    assert captured["url"] == "https://hooks.example.com/upa"
    assert captured["json"]["count"] == 2
    assert captured["headers"]["X-Token"] == "secret"


@pytest.mark.asyncio
async def test_deliver_sheets_appends(monkeypatch) -> None:
    captured: dict = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"updates": {"updatedRows": 3}}

        @property
        def text(self):
            return "{}"

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, params=None, headers=None, json=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    result = await deliver(
        _table(),
        kind="sheets",
        target="spreadsheet123",
        options={"access_token": "tok", "range": "Sheet1!A1"},
    )
    assert result.ok
    assert "spreadsheet123" in captured["url"]
    assert captured["json"]["values"][0] == ["Название", "Цена"]
    assert len(captured["json"]["values"]) == 3


def test_deliver_postgres_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "export.db"
    dsn = f"sqlite:///{db_path.as_posix()}"
    result = destinations._deliver_postgres(_table(), dsn, {"table": "upa_items"})
    assert result.ok
    assert result.records == 2

    engine = create_engine(dsn)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT title, price FROM upa_items ORDER BY title")).fetchall()
    assert rows == [("A", "10"), ("B", "20")]
