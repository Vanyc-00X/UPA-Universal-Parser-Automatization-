"""Тесты извлечения записей из DOM (Этап 4)."""

from __future__ import annotations

from app.analyzer.domlite import parse
from app.editor.schema import (
    ExtractionPlan,
    FieldSpec,
    PaginationSpec,
    ScenarioDefinition,
    SelectStrategy,
)
from app.engine import extractor
from tests.fakes import build_html


def _catalog_definition() -> ScenarioDefinition:
    return ScenarioDefinition(
        url="https://shop.example.com/catalog",
        title="Каталог",
        plan=ExtractionPlan(mode="list", item_selector="div.product-card"),
        pagination=PaginationSpec(),
        fields=[
            FieldSpec(
                key="title",
                title="Название",
                selector="h3.product-card__title",
                strategy=SelectStrategy.TEXT,
                required=True,
            ),
            FieldSpec(
                key="price",
                title="Цена",
                selector="span.product-card__price",
                strategy=SelectStrategy.TEXT,
                required=True,
            ),
            FieldSpec(
                key="url",
                title="Ссылка",
                selector="a.product-card__link",
                strategy=SelectStrategy.ATTRIBUTE,
                attribute="href",
                required=True,
            ),
        ],
    )


def test_extract_list_fills_fields() -> None:
    document = parse(build_html(cards=5))
    result = extractor.extract_page(
        document, _catalog_definition(), base_url="https://shop.example.com/catalog"
    )

    assert not result.errors
    assert result.count == 5
    assert result.records[0].values["title"] == "Товар 1"
    assert result.records[0].values["price"] == 100.0
    assert result.records[0].values["url"] == "https://shop.example.com/product/1"
    assert all(record.filled == 3 for record in result.records)


def test_extract_respects_limit() -> None:
    document = parse(build_html(cards=8))
    result = extractor.extract_page(document, _catalog_definition(), limit=2)
    assert result.count == 2
    assert any("ограничена" in warning for warning in result.warnings)


def test_extract_single_mode() -> None:
    definition = ScenarioDefinition(
        url="https://shop.example.com/catalog",
        plan=ExtractionPlan(mode="single"),
        fields=[
            FieldSpec(
                key="title",
                title="Заголовок",
                selector="h1",
                strategy=SelectStrategy.TEXT,
            )
        ],
    )
    result = extractor.extract_page(parse(build_html()), definition)
    assert result.count == 1
    assert result.records[0].values["title"] == "Каталог"


def test_extract_reports_missing_items() -> None:
    definition = _catalog_definition()
    definition.plan.item_selector = "div.no-such-cards"
    result = extractor.extract_page(parse(build_html()), definition)
    assert result.errors
    assert result.count == 0


def test_extract_api_and_llm_modes_are_explicit_stubs() -> None:
    for mode in ("api", "llm"):
        definition = ScenarioDefinition(
            url="https://shop.example.com/",
            plan=ExtractionPlan(mode=mode),  # type: ignore[arg-type]
            fields=[FieldSpec(key="title", title="T", selector="h1", strategy=SelectStrategy.TEXT)],
        )
        result = extractor.extract_page(parse(build_html()), definition)
        assert result.errors
