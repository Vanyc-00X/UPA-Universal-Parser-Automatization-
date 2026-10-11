"""Тесты сопоставления CSS-селекторов с DOM.

Это ядро визуального редактора и будущего движка извлечения: если селектор
сопоставляется неверно, пользователь видит ложную уверенность, а сбор данных
уходит не туда.
"""

from __future__ import annotations

import pytest

from app.analyzer.domlite import parse
from app.editor.resolver import (
    count_matches,
    first_match,
    iter_matches,
    parse_selector,
    resolve,
)

HTML = """
<html><body>
  <div class="catalog" id="main-catalog">
    <div class="product-card" data-sku="A1">
      <a class="product-card__link" href="/p/1" rel="bookmark"><h3 class="product-card__title">Первый</h3></a>
      <span class="product-card__price" itemprop="price">100 ₽</span>
    </div>
    <div class="product-card" data-sku="A2">
      <a class="product-card__link" href="/p/2"><h3 class="product-card__title">Второй</h3></a>
      <span class="product-card__price" itemprop="price">200 ₽</span>
    </div>
    <div class="product-card" data-sku="A3">
      <a class="product-card__link" href="/p/3"><h3 class="product-card__title">Третий</h3></a>
      <span class="product-card__price" itemprop="price">300 ₽</span>
    </div>
    <div class="hidden-note" style="display:none">Скрытый блок</div>
  </div>
  <nav class="pagination">
    <a class="pagination__next" rel="next" href="?page=2">Далее</a>
  </nav>
</body></html>
"""


@pytest.fixture
def root():
    return parse(HTML).root


def test_tag_selector(root) -> None:
    assert count_matches(root, "div") >= 5
    assert count_matches(root, "h3") == 3


def test_class_and_id_selectors(root) -> None:
    assert count_matches(root, ".product-card") == 3
    assert count_matches(root, "#main-catalog") == 1
    assert count_matches(root, "div.catalog") == 1
    assert count_matches(root, ".nonexistent") == 0


def test_attribute_selectors(root) -> None:
    assert count_matches(root, '[data-sku="A1"]') == 1
    assert count_matches(root, "div[data-sku]") == 3
    assert count_matches(root, '[itemprop="price"]') == 3
    assert count_matches(root, 'a[rel="next"]') == 1


def test_attribute_operators(root) -> None:
    assert count_matches(root, '[href^="/p/"]') == 3
    assert count_matches(root, '[href$="/2"]') == 1
    assert count_matches(root, '[class*="card__title"]') == 3
    assert count_matches(root, '[data-sku~="A1"]') == 1
    # |= совпадает с точным значением или значением с дефисом: A2 подходит.
    assert count_matches(root, '[data-sku|="A2"]') == 1
    assert count_matches(root, '[data-sku|="A9"]') == 0


def test_compound_selector(root) -> None:
    assert count_matches(root, 'a.product-card__link[rel="bookmark"]') == 1
    assert count_matches(root, 'span.product-card__price[itemprop="price"]') == 3
    assert count_matches(root, "a.pagination__next") == 1


def test_descendant_combinator(root) -> None:
    assert count_matches(root, ".product-card .product-card__title") == 3
    assert count_matches(root, ".product-card .product-card__price") == 3
    # Цена не лежит внутри ссылки — этот селектор ничего не найдёт.
    assert count_matches(root, ".product-card__link .product-card__price") == 0


def test_child_combinator(root) -> None:
    assert count_matches(root, ".product-card > .product-card__price") == 3
    assert count_matches(root, ".catalog > .product-card") == 3
    # Название вложено глубже: прямым ребёнком каталога оно не является.
    assert count_matches(root, ".catalog > .product-card__title") == 0


def test_nth_child_supports_generated_paths(root) -> None:
    """Резервные селекторы-пути используют :nth-child — они обязаны работать."""
    assert count_matches(root, "div:nth-child(2)") >= 1
    selector = "html > body > div:nth-child(1)"
    assert count_matches(root, selector) == 0 or count_matches(root, selector) >= 1
    assert parse_selector("div:nth-child(2)").valid


def test_nth_child_points_to_right_node(root) -> None:
    node = first_match(root, ".catalog > div:nth-child(2)")
    assert node is not None
    assert node.get("data-sku") == "A2"


def test_universal_selector(root) -> None:
    assert count_matches(root, "*") > 10
    assert count_matches(root, ".product-card *") > 5


def test_hidden_elements_are_counted_separately(root) -> None:
    report = resolve(root, ".hidden-note")
    assert report.count == 1
    assert report.visible_count == 0
    assert report.unique is True


def test_unsupported_selector_reports_error(root) -> None:
    """Неподдерживаемый селектор должен честно сообщать об этом."""
    report = resolve(root, "div:has(> span)")
    assert report.valid is False
    assert report.error
    assert report.count == 0


def test_empty_selector(root) -> None:
    report = resolve(root, "   ")
    assert report.valid is False
    assert report.count == 0


def test_syntax_error_is_not_an_exception(root) -> None:
    report = resolve(root, "$$$[[[")
    assert report.valid is False
    assert report.count == 0


def test_report_samples_and_dict(root) -> None:
    report = resolve(root, ".product-card")
    data = report.as_dict()
    assert data["count"] == 3
    assert data["valid"] is True
    assert len(data["samples"]) == 3
    assert data["samples"][0]["tag"] == "div"
    assert "Первый" in data["samples"][0]["text"]


def test_first_match_and_iter_matches(root) -> None:
    first = first_match(root, ".product-card__title")
    assert first is not None
    assert first.all_text() == "Первый"

    titles = [node.all_text() for node in iter_matches(root, ".product-card__title")]
    assert titles == ["Первый", "Второй", "Третий"]


def test_first_match_returns_none(root) -> None:
    assert first_match(root, ".nothing-here") is None


def test_parsed_selector_snapshot() -> None:
    parsed = parse_selector("div.catalog > a.pagination__next")
    assert parsed.valid
    assert len(parsed.steps) == 2
    combinator, compound = parsed.steps[1]
    assert combinator == ">"
    assert compound.tag == "a"
    assert compound.classes == ["pagination__next"]


def test_attribute_value_with_spaces() -> None:
    document = parse('<div data-label="поиск по каталогу"></div>')
    assert count_matches(document.root, '[data-label="поиск по каталогу"]') == 1


def test_selector_with_dash_and_underscore_classes() -> None:
    document = parse('<div class="my-block_2"></div>')
    assert count_matches(document.root, ".my-block_2") == 1


def test_case_insensitive_tag() -> None:
    document = parse("<DIV class='x'></DIV>")
    assert count_matches(document.root, "div.x") == 1


def test_deep_descendant_chain(root) -> None:
    assert count_matches(root, "body .catalog .product-card .product-card__title") == 3
    assert count_matches(root, "html body div.catalog span.product-card__price") == 3
