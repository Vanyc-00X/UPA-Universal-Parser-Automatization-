"""Тесты лёгкого HTML-парсера."""

from __future__ import annotations

from app.analyzer.domlite import (
    Node,
    normalize_space,
    parse,
    parse_attributes,
    strip_dynamic,
)


def test_parse_simple_tree() -> None:
    document = parse("<html><body><div class='a'><p>Текст</p></div></body></html>")

    div = document.root.first("div")
    assert div is not None
    assert div.classes == ["a"]
    assert div.first("p") is not None
    assert div.first("p").all_text() == "Текст"  # type: ignore[union-attr]


def test_parse_closes_unclosed_tags() -> None:
    """Незакрытые теги не должны ломать дерево: вложенность восстанавливается."""
    document = parse(
        "<div class='outer'><div class='inner'>текст</div><div class='inner'>ещё</div>"
    )

    outer = document.root.first("div")
    assert outer is not None
    assert len(outer.children) == 2
    assert all(child.has_class("inner") for child in outer.children)
    assert outer.children[0].all_text() == "текст"


def test_parse_handles_stray_closing_tag() -> None:
    document = parse("<div><span>a</span></div></div></span>")

    spans = document.root.find_all("span")
    assert len(spans) == 1
    assert spans[0].all_text() == "a"


def test_parse_void_elements_do_not_nest() -> None:
    """void-теги (img, br, input) не должны «съедать» последующий контент."""
    document = parse("<div><img src='a.png'><span>после картинки</span></div>")

    div = document.root.first("div")
    assert div is not None
    assert [child.tag for child in div.children] == ["img", "span"]
    assert div.first("span").all_text() == "после картинки"  # type: ignore[union-attr]


def test_parse_ignores_script_and_style_content() -> None:
    """Разметка внутри script/style не должна попадать в дерево и в текст."""
    document = parse(
        '<body><script>var a = "<div>";</script>' "<style>.a{color:red}</style><p>Видно</p></body>"
    )

    assert document.root.find_all("div") == []
    paragraphs = document.root.find_all("p")
    assert len(paragraphs) == 1
    assert paragraphs[0].all_text() == "Видно"
    # Текст скриптов и стилей не попадает в текст документа.
    assert "color:red" not in document.root.all_text()
    assert "var a" not in document.root.all_text()


def test_parse_keeps_text_between_tags() -> None:
    document = parse("<div>начало<span>середина</span>конец</div>")

    div = document.root.first("div")
    assert div is not None
    # own_text — весь непосредственный текст элемента: и до, и после вложенных.
    assert div.own_text == "началоконец"
    assert "середина" in div.all_text()


def test_attributes_parsing() -> None:
    attributes = parse_attributes("class=\"a b\" id=main data-x='1' disabled")
    assert attributes == {"class": "a b", "id": "main", "data-x": "1", "disabled": ""}


def test_hidden_detection() -> None:
    document = parse(
        "<div><p hidden>скрыт</p><p style='display: none'>тоже</p>"
        "<p aria-hidden='true'>и этот</p><p>видно</p></div>"
    )

    visible = [node.all_text() for node in document.find_all("p")]
    assert visible == ["видно"]
    assert len(document.all_nodes("p")) == 4


def test_signature_normalizes_dynamic_parts() -> None:
    first = parse("<div class='card item-1234 active'></div>").root.first("div")
    second = parse("<div class='active card item-5678'></div>").root.first("div")

    assert first is not None and second is not None
    # Порядок классов не важен, счётчики вырезаны — подписи совпадают.
    assert first.signature == second.signature


def test_css_path_and_index() -> None:
    document = parse("<body><div>a</div><div>b</div></body>")

    divs = document.root.find_all("div")
    assert divs[0].index == 0
    assert divs[1].index == 1
    assert divs[1].css_path().endswith("div:nth-child(2)")


def test_document_meta_and_title() -> None:
    document = parse(
        "<html lang='ru'><head><title>Заголовок</title>"
        "<meta name='description' content='Описание'>"
        "<meta property='og:title' content='OG'></head><body></body></html>"
    )

    assert document.title() == "Заголовок"
    assert document.lang() == "ru"
    meta = document.meta()
    assert meta["description"] == "Описание"
    assert meta["og:title"] == "OG"


def test_normalize_space_and_strip_dynamic() -> None:
    assert normalize_space("  a \n b\t c ") == "a b c"
    assert strip_dynamic("item-1234") == "item-*"
    assert strip_dynamic("sc-bdVaJa9") == "sc-*"
    assert strip_dynamic("card") == "card"
    assert strip_dynamic("product-card") == "product-card"


def test_deeply_nested_structure_is_preserved() -> None:
    html = "<ul>" + "".join(f"<li><a href='/{i}'>Пункт {i}</a></li>" for i in range(5)) + "</ul>"
    document = parse(html)

    items = document.root.find_all("li")
    assert len(items) == 5
    assert items[2].first("a").all_text() == "Пункт 2"  # type: ignore[union-attr]


def test_walk_visits_all_nodes() -> None:
    document = parse("<div><span>a</span><span>b</span></div>")

    tags = [node.tag for node in document.iter_nodes()]
    assert tags.count("span") == 2
    assert "div" in tags


def test_node_describe() -> None:
    document = parse("<div class='card' id='c1'><span>Текст</span></div>")
    node = document.root.first("div")
    assert node is not None
    described = node.describe()
    assert described["tag"] == "div"
    assert described["id"] == "c1"
    assert described["classes"] == ["card"]
    assert described["text"] == "Текст"


def test_empty_document_does_not_crash() -> None:
    document = parse("")
    assert document.root.tag == "#document"
    assert document.root.children == []
    assert document.title() is None


def test_counts_tags() -> None:
    document = parse("<div><span></span><span></span></div>")
    counts = document.counts()
    assert counts["span"] == 2
    assert counts["div"] == 1


def test_node_helpers() -> None:
    node = Node(tag="div", attrs={"class": "a b", "id": "x"})
    assert node.has_class("a", "z") is True
    assert node.has_class("c") is False
    assert node.node_id == "x"
    assert node.get("missing", "по умолчанию") == "по умолчанию"
