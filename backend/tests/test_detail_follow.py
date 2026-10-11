"""Двухуровневый сбор: список → карточка."""

from __future__ import annotations

import pytest

from app.editor.schema import (
    DetailSpec,
    ExtractionPlan,
    FieldSpec,
    SelectStrategy,
    ScenarioDefinition,
)
from app.engine import extractor, service
from app.analyzer.domlite import parse
from app.healing.journal import RunJournal


LIST_HTML = """
<html><body>
<div class="product-list">
  <div class="product-card">
    <a class="product-card__link" href="https://shop.example.com/product/1">
      <h3 class="product-card__title">Товар 1</h3>
    </a>
    <span class="product-card__price">100 ₽</span>
  </div>
  <div class="product-card">
    <a class="product-card__link" href="https://shop.example.com/product/2">
      <h3 class="product-card__title">Товар 2</h3>
    </a>
    <span class="product-card__price">200 ₽</span>
  </div>
</div>
</body></html>
"""

DETAIL_PAGES = {
    "https://shop.example.com/product/1": """
    <html><body>
      <h1 class="title">Товар 1 полный</h1>
      <div class="sku">SKU-1</div>
      <p class="desc">Описание первого</p>
    </body></html>
    """,
    "https://shop.example.com/product/2": """
    <html><body>
      <h1 class="title">Товар 2 полный</h1>
      <div class="sku">SKU-2</div>
      <p class="desc">Описание второго</p>
    </body></html>
    """,
}


def _list_definition(*, detail: bool = True) -> ScenarioDefinition:
    return ScenarioDefinition(
        url="https://shop.example.com/catalog",
        title="Каталог",
        plan=ExtractionPlan(mode="list", container_selector=".product-list"),
        fields=[
            FieldSpec(key="title", title="Название", selector=".product-card__title"),
            FieldSpec(
                key="url",
                title="Ссылка",
                selector=".product-card__link",
                strategy=SelectStrategy.ATTRIBUTE,
                attribute="href",
            ),
            FieldSpec(key="price", title="Цена", selector=".product-card__price"),
        ],
        detail=DetailSpec(
            enabled=detail,
            link_field="url",
            fields=[
                FieldSpec(key="sku", title="Артикул", selector=".sku"),
                FieldSpec(key="description", title="Описание", selector=".desc"),
            ],
            max_follows=10,
            delay_ms=0,
        ),
    )


@pytest.mark.asyncio
async def test_follow_detail_merges_fields() -> None:
    definition = _list_definition()
    document = parse(LIST_HTML)
    result = extractor.extract_page(
        document, definition, base_url="https://shop.example.com/catalog"
    )
    assert len(result.records) == 2

    async def fetch(url: str) -> tuple[str | None, str | None]:
        return DETAIL_PAGES.get(url), None if url in DETAIL_PAGES else "missing"

    class _Settings:
        fetch_max_retries = 1
        fetch_retry_backoff_ms = 1

    await service._follow_detail_pages(
        session=None,  # type: ignore[arg-type]
        settings=_Settings(),  # type: ignore[arg-type]
        records=result.records,
        definition=definition,
        fetch_page=fetch,
        journal=RunJournal(),
    )

    assert result.records[0].values["sku"] == "SKU-1"
    assert result.records[0].values["description"] == "Описание первого"
    assert result.records[1].values["sku"] == "SKU-2"
    assert result.records[0].values["_detail_url"] == "https://shop.example.com/product/1"


def test_detail_overlap_rejected() -> None:
    with pytest.raises(Exception):
        ScenarioDefinition(
            url="https://a.com",
            plan=ExtractionPlan(mode="list"),
            fields=[FieldSpec(key="title", title="T", selector="h1")],
            detail=DetailSpec(
                enabled=True,
                fields=[FieldSpec(key="title", title="T2", selector="h2")],
            ),
        )


def test_definition_for_report_includes_detail_fields() -> None:
    definition = _list_definition()
    report_def = service._definition_for_report(definition)
    keys = {field.key for field in report_def.fields}
    assert "sku" in keys
    assert "description" in keys
    assert report_def.detail.enabled is False
