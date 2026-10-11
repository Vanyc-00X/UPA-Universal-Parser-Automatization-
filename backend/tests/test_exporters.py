"""Тесты экспортёров (Этап 5)."""

from __future__ import annotations

from types import SimpleNamespace

from app.editor.schema import (
    ExtractionPlan,
    FieldSpec,
    PaginationKind,
    PaginationSpec,
    ScenarioDefinition,
    SelectStrategy,
)
from app.exporters import csv_export, json_export, markdown, xlsx_export
from app.exporters.diff import compare_runs
from app.exporters.table import table_from_items


def _items() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            data={"title": "Товар 1", "price": 100.0, "url": "https://a.example/1"},
            is_valid=True,
            position=0,
            dedup_key="k1",
        ),
        SimpleNamespace(
            data={"title": "Товар 2", "price": 200.0, "url": "https://a.example/2"},
            is_valid=False,
            position=1,
            dedup_key="k2",
        ),
    ]


def test_table_from_items_preserves_titles_and_filter() -> None:
    table = table_from_items(
        _items(),
        field_titles={"title": "Название", "price": "Цена", "url": "Ссылка"},
        run_id="r1",
    )
    assert table.columns == ["title", "price", "url"]
    assert table.header()[0] == "Название"
    filtered = table.filtered(query="товар 2", only_invalid=True)
    assert filtered.count == 1
    assert filtered.rows[0]["title"] == "Товар 2"


def test_csv_and_json_export() -> None:
    table = table_from_items(_items(), field_titles={"title": "Название", "price": "Цена"})
    csv_bytes = csv_export.render_csv(table, delimiter=";")
    text = csv_bytes.decode("utf-8-sig")
    assert "Название;Цена" in text
    assert "Товар 1;100.0" in text

    payload = json_export.render_json(table).decode("utf-8")
    assert '"title": "Товар 1"' in payload
    jsonl = json_export.render_jsonl(table).decode("utf-8").strip().splitlines()
    assert len(jsonl) == 2


def test_xlsx_export_is_zip_package() -> None:
    table = table_from_items(_items(), field_titles={"title": "Название", "price": "Цена"})
    content = xlsx_export.render_xlsx(table)
    assert content[:2] == b"PK"
    assert len(content) > 1000


def test_markdown_spec_contains_fields_and_acceptance() -> None:
    definition = ScenarioDefinition(
        url="https://shop.example.com/catalog",
        title="Каталог",
        description="Собрать товары",
        plan=ExtractionPlan(mode="list", item_selector="div.card"),
        pagination=PaginationSpec(kind=PaginationKind.NEXT_LINK, selector="a.next", max_pages=3),
        fields=[
            FieldSpec(
                key="title",
                title="Название",
                selector="h3",
                strategy=SelectStrategy.TEXT,
                required=True,
            ),
            FieldSpec(
                key="price",
                title="Цена",
                selector=".price",
                strategy=SelectStrategy.TEXT,
                required=True,
            ),
        ],
    )
    text = markdown.build_spec_markdown(
        definition,
        scenario_name="Каталог тест",
        sample_rows=[{"title": "A", "price": 10}],
    )
    assert "# Техническое задание: Каталог тест" in text
    assert "`title`" in text
    assert "≥ 95%" in text
    assert "Пример собранных записей" in text


def test_compare_runs_detects_added_removed_changed() -> None:
    current = [
        SimpleNamespace(data={"title": "A", "price": 11}, position=0, dedup_key="a"),
        SimpleNamespace(data={"title": "B", "price": 20}, position=1, dedup_key="b"),
    ]
    previous = [
        SimpleNamespace(data={"title": "A", "price": 10}, position=0, dedup_key="a"),
        SimpleNamespace(data={"title": "C", "price": 30}, position=1, dedup_key="c"),
    ]
    diff = compare_runs(
        current_run_id="r2",
        previous_run_id="r1",
        current_items=current,
        previous_items=previous,
    )
    assert diff.summary()["added"] == 1
    assert diff.summary()["removed"] == 1
    assert diff.summary()["changed"] == 1
    assert diff.changed[0]["before"]["price"] == 10
    assert diff.changed[0]["after"]["price"] == 11
