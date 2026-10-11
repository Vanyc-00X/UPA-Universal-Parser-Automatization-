"""Тесты self-healing (Этап 6)."""

from __future__ import annotations

from app.analyzer.domlite import parse
from app.editor.schema import (
    ExtractionPlan,
    FieldSpec,
    ScenarioDefinition,
    SelectStrategy,
)
from app.healing.journal import RunJournal
from app.healing.propose import (
    apply_patches_to_definition,
    diagnose_broken_fields,
    propose_field_patches,
)
from app.healing.retry import classify_fetch_error
from tests.fakes import build_html


def _definition(*, broken_title: bool = False) -> ScenarioDefinition:
    title_selector = "h3.no-such-title" if broken_title else "h3.product-card__title"
    return ScenarioDefinition(
        url="https://shop.example.com/catalog",
        title="Каталог",
        plan=ExtractionPlan(mode="list", item_selector="div.product-card"),
        fields=[
            FieldSpec(
                key="title",
                title="Название",
                selector=title_selector,
                strategy=SelectStrategy.TEXT,
                required=True,
                role="item_title",
                fallback_selectors=["h3.product-card__title"],
            ),
            FieldSpec(
                key="price",
                title="Цена",
                selector="span.product-card__price",
                strategy=SelectStrategy.TEXT,
                required=True,
                role="item_price",
            ),
        ],
    )


def test_classify_fetch_error_kinds() -> None:
    assert classify_fetch_error("TimeoutError: timed out").kind == "timeout"
    assert classify_fetch_error("HTTP 503").kind == "site_down"
    assert classify_fetch_error("403 Forbidden").kind == "blocked"
    assert classify_fetch_error("recaptcha challenge").kind == "captcha"
    assert classify_fetch_error("селектор не найден").retryable is False


def test_diagnose_and_propose_fallback() -> None:
    definition = _definition(broken_title=True)
    stats = {
        "title": {
            "coverage": 0.0,
            "filled": 0,
            "total": 3,
            "required": True,
            "problems": {"селектор не находит элементов": 3},
        },
        "price": {"coverage": 1.0, "filled": 3, "total": 3, "required": True, "problems": {}},
    }
    broken = diagnose_broken_fields(definition, stats, min_coverage=0.95)
    assert "title" in broken

    document = parse(build_html(cards=3))
    patches = propose_field_patches(document, definition, broken)
    assert len(patches) == 1
    assert patches[0].key == "title"
    assert patches[0].new_selector == "h3.product-card__title"
    assert patches[0].source == "fallback"
    assert patches[0].matches >= 1


def test_propose_from_element_map() -> None:
    definition = ScenarioDefinition(
        url="https://shop.example.com/catalog",
        plan=ExtractionPlan(mode="list", item_selector="div.product-card"),
        fields=[
            FieldSpec(
                key="title",
                title="Название",
                selector="h3.broken",
                strategy=SelectStrategy.TEXT,
                required=True,
                role="item_title",
            )
        ],
    )
    document = parse(build_html(cards=2))
    elements = [
        {
            "role": "item_title",
            "selector": "h3.product-card__title",
            "selectors": [
                {"selector": "h3.product-card__title", "score": 0.9},
                {"selector": ".product-card__title", "score": 0.7},
            ],
        }
    ]
    patches = propose_field_patches(document, definition, ["title"], element_map_elements=elements)
    assert patches
    assert patches[0].source == "element_map"
    assert "product-card__title" in patches[0].new_selector


def test_apply_patches_keeps_old_as_fallback() -> None:
    definition = _definition(broken_title=True)
    document = parse(build_html(cards=2))
    patches = propose_field_patches(document, definition, ["title"])
    patched = apply_patches_to_definition(definition, patches)
    title = next(field for field in patched.fields if field.key == "title")
    assert title.selector == "h3.product-card__title"
    assert "h3.no-such-title" in title.fallback_selectors


def test_journal_records_steps() -> None:
    journal = RunJournal()
    journal.start("page_1")
    journal.info("page_1", "собрано 3 записи", url="/catalog")
    journal.error("fetch_next", "timeout", url="/catalog?page=2")
    steps = journal.as_list()
    assert steps[0]["level"] == "info"
    assert steps[1]["level"] == "error"
    assert steps[0]["details"]["url"] == "/catalog"
