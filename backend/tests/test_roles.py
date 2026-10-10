"""Тесты ролей и построения селекторов."""

from __future__ import annotations

from app.analyzer.domlite import parse
from app.analyzer.roles import (
    Role,
    build_selectors,
    guess_roles,
    label_for,
    looks_generated,
    merge_candidate_lists,
    selector_quality,
)


def node_of(html: str) -> object:
    """Первый элемент разметки — удобно для проверок ролей и селекторов."""
    document = parse(html)
    return next(node for node in document.iter_nodes() if node.tag != "#document")


def roles_of(html: str) -> list[str]:
    return [role.value for role in guess_roles(node_of(html))]  # type: ignore[arg-type]


def test_role_by_tag() -> None:
    assert roles_of("<table></table>")[0] == "table"
    assert roles_of("<tr></tr>")[0] == "table_row"
    assert roles_of("<textarea></textarea>")[0] == "textarea"
    assert roles_of("<h2>Заголовок</h2>")[0] == "heading"
    assert roles_of("<nav></nav>")[0] == "navigation"


def test_role_by_input_type() -> None:
    assert roles_of("<input type='search'>")[0] == "search_input"
    assert roles_of("<input type='email'>")[0] == "email_input"
    assert roles_of("<input type='password'>")[0] == "password_input"
    assert roles_of("<input type='number'>")[0] == "number_input"
    assert roles_of("<input type='checkbox'>")[0] == "checkbox"
    assert roles_of("<input type='file'>")[0] == "file_input"
    assert roles_of("<input type='text'>")[0] == "text_input"


def test_role_by_keywords() -> None:
    assert "item_price" in roles_of("<span class='product-card__price'>100 ₽</span>")
    assert "item_title" in roles_of("<h3 class='product-card__title'>Товар</h3>")
    assert "pagination_next" in roles_of("<a class='pagination__next' rel='next'>Далее</a>")
    assert "load_more" in roles_of("<button class='load-more'>Показать ещё</button>")
    assert "filter" in roles_of("<form class='filter-form'></form>")


def test_role_combines_tag_and_keyword() -> None:
    """Select с именем sort честно совмещает две роли."""
    roles = roles_of("<select name='sort' class='sort__select'></select>")
    assert "select" in roles
    assert "sort" in roles


def test_search_role_prefers_type_over_keywords() -> None:
    roles = roles_of("<input type='search' name='q'>")
    assert roles[0] == "search_input"


def test_unknown_role_for_plain_div() -> None:
    assert roles_of("<div></div>") == ["unknown"]


def test_aria_role_attribute_is_respected() -> None:
    roles = roles_of("<div role='navigation'></div><div role='dialog'></div>")
    assert roles[0] == "navigation"
    assert roles_of("<div role='dialog'></div>")[0] == "modal"


def test_roles_are_deduplicated() -> None:
    roles = roles_of("<input type='search' name='search' class='search-input' placeholder='Поиск'>")
    assert len(roles) == len(set(roles))


# --- Селекторы ---------------------------------------------------------------


def test_selector_prefers_data_testid() -> None:
    selector, candidates = build_selectors(
        node_of("<div data-testid='catalog-item' class='css-1x2y3z' id='x7'></div>")  # type: ignore[arg-type]
    )
    assert selector == '[data-testid="catalog-item"]'
    assert candidates[0].score > 0.9


def test_selector_uses_id_when_stable() -> None:
    selector, _ = build_selectors(node_of("<div id='catalog-list'></div>"))  # type: ignore[arg-type]
    assert selector == "#catalog-list"


def test_generated_id_is_penalized() -> None:
    selector, candidates = build_selectors(node_of("<div id='item-4711'></div>"))  # type: ignore[arg-type]
    assert selector == "#item-4711"
    assert candidates[0].score < 0.6
    assert candidates[0].kind == "id-generated"


def test_selector_uses_aria_and_name() -> None:
    selector, _ = build_selectors(node_of("<input aria-label='Поиск по сайту'>"))  # type: ignore[arg-type]
    assert selector == 'input[aria-label="Поиск по сайту"]'

    selector, _ = build_selectors(node_of("<input name='q'>"))  # type: ignore[arg-type]
    assert selector == 'input[name="q"]'


def test_selector_skips_utility_classes() -> None:
    _, candidates = build_selectors(
        node_of("<div class='mt-4 px-2 flex product-card'></div>")  # type: ignore[arg-type]
    )
    best_class = next(item for item in candidates if item.kind.startswith("class"))
    assert "product-card" in best_class.selector
    assert "mt-4" not in best_class.selector


def test_selector_falls_back_to_path() -> None:
    _, candidates = build_selectors(node_of("<div><span></span></div><span></span>"))  # type: ignore[arg-type]
    assert any(item.kind == "path" for item in candidates)
    assert candidates[-1].kind == "path"


def test_microdata_and_rel_selectors() -> None:
    selector, _ = build_selectors(node_of("<span itemprop='price'>100</span>"))  # type: ignore[arg-type]
    assert selector == 'span[itemprop="price"]'

    selector, _ = build_selectors(node_of("<a rel='next' href='/2'>Далее</a>"))  # type: ignore[arg-type]
    assert selector == 'a[rel="next"]'


def test_selector_quality_reflects_stability() -> None:
    _, stable = build_selectors(node_of("<input data-testid='q'>"))  # type: ignore[arg-type]
    _, weak = build_selectors(node_of("<div class='css-9k8j7h'></div>"))  # type: ignore[arg-type]
    assert selector_quality(stable) > selector_quality(weak)


def test_merge_candidate_lists_prefers_repeated_selectors() -> None:
    _, first = build_selectors(node_of("<div class='card' id='c1'>x</div>"))  # type: ignore[arg-type]
    _, second = build_selectors(node_of("<div class='card' id='c2'>y</div>"))  # type: ignore[arg-type]

    merged = merge_candidate_lists([first, second])
    selectors = [item.selector for item in merged]
    # Селектор по классу встречается у обоих элементов, по id — уникален.
    assert any(item.selector == "div.card" for item in merged)
    assert len(selectors) == len(set(selectors))


def test_looks_generated() -> None:
    assert looks_generated("css-1x2y3z") is True
    assert looks_generated("sc-bdVaJa") is True
    assert looks_generated("item-4711") is True
    assert looks_generated("a1b2c3d4e5") is True
    assert looks_generated("product-card") is False
    assert looks_generated("catalog") is False
    assert looks_generated("") is True


def test_every_role_has_label() -> None:
    for role in Role:
        assert label_for(role)
