"""Тесты детерминированного анализа страниц на наборе из 10 типовых сайтов.

Этот файл реализует критерий готовности Этапа 2 «на 10 тестовых сайтах карта
элементов корректно выделяет поиск, карточки и пагинацию». Набор страниц лежит в
``tests/pages.py`` и повторяет характерные типы: каталог, прайс-таблица, лента новостей,
список объявлений, SPA-каркас, форма входа, карточка товара, каталог без говорящих
классов, личный кабинет и битая вёрстка.
"""

from __future__ import annotations

import pytest

from app.analyzer import detector
from app.analyzer.roles import Role
from tests.pages import CATALOG, FIXTURES, FIXTURES_BY_KEY

CATALOG_HTML = CATALOG.html


@pytest.mark.parametrize("fixture", FIXTURES, ids=[item.key for item in FIXTURES])
def test_fixture_detects_expected_roles(fixture) -> None:
    """На каждой странице должны находиться заявленные роли."""
    analysis = detector.analyze_html(fixture.html)
    found = {element.role.value for element in analysis.elements}

    missing = set(fixture.expected_roles) - found
    assert not missing, f"{fixture.key}: не найдены роли {sorted(missing)}; найдено {sorted(found)}"

    unexpected = set(fixture.forbidden_roles) & found
    assert not unexpected, f"{fixture.key}: найдены запрещённые роли {sorted(unexpected)}"


@pytest.mark.parametrize(
    "fixture",
    [item for item in FIXTURES if item.expected_repeat_count is not None],
    ids=[item.key for item in FIXTURES if item.expected_repeat_count is not None],
)
def test_fixture_detects_repeat_count(fixture) -> None:
    """Число элементов в основном списке должно совпадать с разметкой."""
    analysis = detector.analyze_html(fixture.html)
    best = analysis.best_repeat
    assert best is not None, f"{fixture.key}: список не найден"
    assert best.count == fixture.expected_repeat_count


@pytest.mark.parametrize("fixture", FIXTURES, ids=[item.key for item in FIXTURES])
def test_fixture_always_produces_report_and_title(fixture) -> None:
    """Отчёт формируется всегда, даже если страница пустая или битая."""
    analysis = detector.analyze_html(fixture.html)
    report = detector.build_report(analysis)

    assert analysis.title
    assert report
    assert analysis.title in report


def test_catalog_finds_single_main_list() -> None:
    """В каталоге основной список должен быть один — 12 карточек."""
    analysis = detector.analyze_html(CATALOG_HTML)
    best = analysis.best_repeat
    assert best is not None
    assert best.count == 12
    assert best.container.has_class("product-list")
    assert best.similarity > 0.7


def test_catalog_data_fields_have_stable_selectors() -> None:
    """Поля карточек должны получить осмысленные селекторы, а не пути."""
    analysis = detector.analyze_html(CATALOG_HTML)
    by_role = {element.role: element for element in analysis.elements}

    for role in (Role.ITEM_TITLE, Role.ITEM_PRICE, Role.ITEM_LINK, Role.ITEM_IMAGE):
        assert role in by_role, f"не найдена роль {role}"
        element = by_role[role]
        assert element.count == 12
        # Селектор опирается на говорящий признак: класс внутри карточки,
        # микроразметку itemprop или саму карточку — но не на длинный путь.
        assert (
            "product-card" in element.selector or "itemprop" in element.selector
        ), element.selector
        assert element.candidates[0].kind in {
            "class",
            "class-short",
            "nested",
            "microdata",
        }, element.candidates[0]
        assert element.candidates[0].score > 0.5


def test_catalog_selectors_are_distinct_for_data_roles() -> None:
    """Разные поля карточки не должны получить один и тот же селектор.

    Общая роль «элемент списка» может совпадать с названием — это разные смыслы
    одного элемента, и оба полезны. А вот цена и название обязаны различаться.
    """
    analysis = detector.analyze_html(CATALOG_HTML)
    by_role = {}
    for element in analysis.elements:
        by_role.setdefault(element.role, element)

    title = by_role[Role.ITEM_TITLE].selector
    price = by_role[Role.ITEM_PRICE].selector
    link = by_role[Role.ITEM_LINK].selector
    image = by_role[Role.ITEM_IMAGE].selector
    assert len({title, price, link, image}) == 4


def test_catalog_search_field_detected_with_high_confidence() -> None:
    analysis = detector.analyze_html(CATALOG_HTML)
    search = next(item for item in analysis.elements if item.role is Role.SEARCH_INPUT)

    assert search.confidence >= 0.9
    assert 'input[type="search"]' in search.selector or "search-input" in search.selector
    assert search.sample and "Поиск" in search.sample


def test_pagination_next_uses_rel_attribute() -> None:
    analysis = detector.analyze_html(CATALOG_HTML)
    next_link = next(item for item in analysis.elements if item.role is Role.PAGINATION_NEXT)

    assert next_link.confidence >= 0.8
    assert "next" in next_link.selector


def test_generated_classes_are_avoided_in_selectors() -> None:
    """Там, где есть data-testid, селектор не должен опираться на хэш-классы."""
    fixture = FIXTURES_BY_KEY["unusual_markup"]
    analysis = detector.analyze_html(fixture.html)
    list_container = next(item for item in analysis.elements if item.role is Role.LIST_CONTAINER)
    assert "css-" not in list_container.selector
    assert "data-testid" in list_container.selector


def test_repeat_group_detection_respects_similarity() -> None:
    """Разнородные блоки не должны считаться списком."""
    html = """
    <div class="container">
      <div class="one"><h2>Первый блок</h2><p>Текст</p></div>
      <div class="two"><a href="/x">Ссылка</a><img src="/i.png" alt="Картинка"></div>
      <section class="three"><table><tr><td>Ячейка</td></tr></table></section>
    </div>
    """
    analysis = detector.analyze_html(html)
    assert analysis.best_repeat is None


def test_broken_html_nested_lists_are_found() -> None:
    """При незакрытых тегах парсер обязан закрыть их и всё равно найти списки."""
    fixture = FIXTURES_BY_KEY["broken_html"]
    analysis = detector.analyze_html(fixture.html)

    assert analysis.repeats
    assert analysis.best_repeat is not None
    assert analysis.best_repeat.count == 3
    # Второй список — таблица с незакрытыми строками.
    assert any(item.role is Role.TABLE for item in analysis.elements)


def test_warnings_are_added_for_single_page() -> None:
    analysis = detector.analyze_html(FIXTURES_BY_KEY["product_page"].html)
    assert any("Повторяющихся блоков не найдено" in warning for warning in analysis.warnings)


def test_warnings_are_added_when_no_inputs() -> None:
    analysis = detector.analyze_html(FIXTURES_BY_KEY["news_feed"].html)
    assert any("Полей ввода не найдено" in warning for warning in analysis.warnings)


def test_report_describes_found_list() -> None:
    analysis = detector.analyze_html(CATALOG_HTML)
    report = detector.build_report(analysis)

    assert "Найден список: 12 однотипных элементов" in report
    assert "Поиск" in report or "поиск" in report
    assert "Данные, которые можно собирать" in report


def test_report_for_empty_page() -> None:
    analysis = detector.analyze_html("<html><body></body></html>")
    report = detector.build_report(analysis)

    assert "Списков на странице не найдено" in report
    assert report


def test_analysis_summary_keys() -> None:
    analysis = detector.analyze_html(CATALOG_HTML)
    summary = analysis.summary()

    assert summary["elements"] > 0
    assert summary["repeats"] >= 1
    assert summary["data_elements"] > 0
    assert summary["title"]


def test_table_rows_are_not_treated_as_cards() -> None:
    """Строки таблицы — это список, но не карточки товара."""
    fixture = FIXTURES_BY_KEY["price_table"]
    analysis = detector.analyze_html(fixture.html)

    best = analysis.best_repeat
    assert best is not None
    assert best.container.tag == "tbody"
    assert best.signature.startswith("tr")


def test_elements_are_sorted_with_data_first() -> None:
    analysis = detector.analyze_html(CATALOG_HTML)
    roles = [element.role for element in analysis.elements]

    assert roles[0] is Role.LIST_CONTAINER
    # Служебные элементы (подвал) уходят в конец.
    if Role.FOOTER in roles:
        assert roles.index(Role.FOOTER) > roles.index(Role.ITEM_PRICE)


def test_no_duplicate_role_selector_pairs() -> None:
    for fixture in FIXTURES:
        analysis = detector.analyze_html(fixture.html)
        pairs = [(element.role.value, element.selector) for element in analysis.elements]
        assert len(pairs) == len(set(pairs)), f"{fixture.key}: дубликаты в карте"


def test_microdata_price_is_recognized() -> None:
    html = """
    <div class="product-list">
      <div class="product-card"><span itemprop="price">100 ₽</span><h3>Товар 1</h3></div>
      <div class="product-card"><span itemprop="price">200 ₽</span><h3>Товар 2</h3></div>
      <div class="product-card"><span itemprop="price">300 ₽</span><h3>Товар 3</h3></div>
    </div>
    """
    analysis = detector.analyze_html(html)
    price = next(item for item in analysis.elements if item.role is Role.ITEM_PRICE)
    assert "itemprop" in price.selector or "price" in price.selector


def test_empty_page_analysis() -> None:
    analysis = detector.analyze_html("")

    assert analysis.elements == []
    assert analysis.repeats == []
    assert analysis.warnings


def test_similarity_function_monotonic() -> None:
    document = detector.parse(CATALOG_HTML)
    cards = [node for node in document.iter_nodes() if node.has_class("product-card")]
    assert len(cards) == 12

    same = detector.similarity(cards[0], cards[1])
    assert 0.8 <= same <= 1.0
