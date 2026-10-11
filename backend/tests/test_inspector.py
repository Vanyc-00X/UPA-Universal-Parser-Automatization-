"""Тесты инспектора элементов: узлы, рамки, соседи."""

from __future__ import annotations

from app.analyzer.domlite import parse
from app.editor.inspector import (
    assign_ids,
    build_inspector,
    estimate_boxes,
    node_id_for,
    sibling_context,
)
from tests.pages import CATALOG

HTML = """
<html><body>
  <header class="site-header"><a href="/" class="logo">Магазин</a></header>
  <main>
    <h1>Каталог</h1>
    <div class="product-list">
      <div class="product-card"><h3 class="product-card__title">Товар 1</h3><span class="product-card__price">100 ₽</span></div>
      <div class="product-card"><h3 class="product-card__title">Товар 2</h3><span class="product-card__price">200 ₽</span></div>
      <div class="product-card"><h3 class="product-card__title">Товар 3</h3><span class="product-card__price">300 ₽</span></div>
    </div>
    <img src="/img/1.jpg" alt="Картинка">
  </main>
</body></html>
"""


def test_inspector_returns_interesting_nodes() -> None:
    result = build_inspector(HTML)

    tags = {node.tag for node in result.nodes}
    assert "main" in tags
    assert "div" in tags
    assert "h3" in tags
    assert "img" in tags
    assert result.total == len(result.nodes) > 0


def test_inspector_skips_scripts_and_styles() -> None:
    html = "<body><script>var a=1;</script><style>.a{}</style><p>Текст</p></body>"
    result = build_inspector(html)

    tags = {node.tag for node in result.nodes}
    assert "script" not in tags
    assert "style" not in tags
    assert "p" in tags


def test_nodes_have_ids_paths_and_parents() -> None:
    result = build_inspector(HTML)
    by_id = {node.node_id: node for node in result.nodes}

    main = next(node for node in result.nodes if node.tag == "main")
    assert main.node_id in by_id
    # Ближайший показанный предок — header или сам body не показывается,
    # поэтому у первого блока страницы родитель может отсутствовать.
    if main.parent_id is not None:
        assert by_id[main.parent_id].tag == "header"

    # Связи детей и родителей согласованы.
    for node in result.nodes:
        for child_id in node.children_ids:
            assert by_id[child_id].parent_id == node.node_id


def test_boxes_are_inside_page() -> None:
    result = build_inspector(HTML)
    width = result.page["width"]
    height = result.page["height"]

    for node in result.nodes:
        assert node.box
        assert node.box["x"] >= 0
        assert node.box["width"] > 0
        assert node.box["height"] > 0
        assert node.box["x"] + node.box["width"] <= width + 1
        assert node.box["y"] + node.box["height"] <= height + 1


def test_boxes_increase_down_the_page() -> None:
    """Позже идущие элементы должны быть ниже — иначе подсветка бессмысленна."""
    result = build_inspector(HTML)
    cards = [node for node in result.nodes if "product-card" in node.classes and node.tag == "div"]
    assert len(cards) == 3
    assert cards[0].box["y"] < cards[1].box["y"] < cards[2].box["y"]


def test_matched_by_links_nodes_to_map_selectors() -> None:
    result = build_inspector(HTML, selectors=[".product-card", ".product-card__price"])

    with_selector = [node for node in result.nodes if node.matched_by]
    assert with_selector
    card = next(
        node for node in result.nodes if "product-card" in node.classes and node.tag == "div"
    )
    assert ".product-card" in card.matched_by
    price = next(node for node in result.nodes if "product-card__price" in node.classes)
    assert ".product-card__price" in price.matched_by


def test_matched_by_ignores_broken_selectors() -> None:
    result = build_inspector(HTML, selectors=["div:has(> span)", ".product-card"])
    assert all(
        all(selector == ".product-card" for selector in node.matched_by) for node in result.nodes
    )


def test_max_nodes_is_respected() -> None:
    result = build_inspector(CATALOG.html, max_nodes=10)
    assert len(result.nodes) <= 10


def test_node_ids_are_stable_between_calls() -> None:
    first = build_inspector(HTML)
    second = build_inspector(HTML)
    assert [node.node_id for node in first.nodes] == [node.node_id for node in second.nodes]


def test_assign_ids_maps_every_node() -> None:
    document = parse(HTML)
    mapping = assign_ids(document.root)
    assert len(mapping) > 5
    for node in document.root.walk():
        if node.tag == "#document":
            continue
        assert node_id_for(node) in mapping


def test_estimate_boxes_skips_hidden_elements() -> None:
    html = "<body><div style='display:none'>скрыт</div><div>видно</div></body>"
    document = parse(html)
    boxes = estimate_boxes(document.root)

    assert len(boxes) == 1


def test_sibling_context_detects_list_item() -> None:
    document = parse(HTML)
    card = next(
        node
        for node in document.root.walk()
        if "product-card" in node.classes and node.tag == "div"
    )
    context = sibling_context(HTML, node_id_for(card))

    assert context["found"] is True
    assert context["similar_siblings"] == 2
    assert context["looks_like_list_item"] is True
    assert len(context["neighbours"]) == 2


def test_sibling_context_for_unknown_node() -> None:
    context = sibling_context(HTML, "nope")
    assert context == {"found": False}


def test_inspector_reports_page_size() -> None:
    result = build_inspector(HTML)
    assert result.page["width"] == 1440
    assert result.page["height"] >= 100


def test_inspector_is_serializable() -> None:
    import json

    result = build_inspector(HTML)
    payload = json.dumps(result.as_dict(), ensure_ascii=False)
    assert "product-card" in payload
