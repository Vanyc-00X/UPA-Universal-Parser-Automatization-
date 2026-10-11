"""Тесты извлечения из XHR/JSON."""

from __future__ import annotations

from app.editor.schema import ExtractionPlan, FieldSpec, ScenarioDefinition
from app.engine import json_extract


def test_walk_path_nested_and_array() -> None:
    data = {"data": {"items": [{"name": "A"}, {"name": "B"}]}}
    items = json_extract.walk_path(data, "data.items")
    assert isinstance(items, list) and len(items) == 2
    assert json_extract.walk_path(items[0], "name") == "A"


def test_extract_from_json_records() -> None:
    payload = {
        "results": [
            {"title": "Товар 1", "price": {"value": 100}},
            {"title": "Товар 2", "price": {"value": 200}},
        ]
    }
    definition = ScenarioDefinition(
        url="https://shop.example.com",
        title="API",
        plan=ExtractionPlan(mode="api", records_path="results"),
        fields=[
            FieldSpec(key="title", title="Название", selector="title", required=True),
            FieldSpec(key="price", title="Цена", selector="price.value"),
        ],
    )
    result = json_extract.extract_from_json(payload, definition)
    assert not result.errors
    assert len(result.records) == 2
    assert result.records[0].values["title"] == "Товар 1"
    assert result.records[0].values["price"] == 100


def test_pick_network_payload_prefers_api_url(settings) -> None:
    import json

    from app.crawler import store

    snapshot_id = "snapjson01"
    directory = store.snapshot_dir(settings, snapshot_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / store.NETWORK_JSON).write_text(
        json.dumps(
            {
                "count": 2,
                "requests": [
                    {
                        "url": "https://shop.example.com/api/other",
                        "method": "GET",
                        "resource_type": "xhr",
                        "status": 200,
                        "mime": "application/json",
                        "body": '{"items": [{"n": 1}]}',
                    },
                    {
                        "url": "https://shop.example.com/api/products",
                        "method": "GET",
                        "resource_type": "fetch",
                        "status": 200,
                        "mime": "application/json",
                        "body": '{"items": [{"n": 2}, {"n": 3}]}',
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    payload, url = json_extract.pick_network_payload(
        settings, snapshot_id, api_url="/api/products"
    )
    assert payload is not None
    assert url and "products" in url
    assert len(payload["items"]) == 2
