"""Тесты обрезки DOM — критичного шага для работы локальной модели."""

from __future__ import annotations

from app.crawler.dom import estimate_tokens, normalize_url, trim_html
from tests.fakes import build_html


def test_removes_scripts_styles_svg_and_comments() -> None:
    result = trim_html(build_html(), max_tokens=100_000)

    assert "static/app.js" not in result.html
    assert "color: #333" not in result.html
    assert "<svg" not in result.html
    assert "служебный комментарий" not in result.html
    assert "<path" not in result.html
    assert result.stats.removed_scripts >= 1
    assert result.stats.removed_svgs >= 1
    assert result.stats.removed_comments >= 1


def test_removes_styles_from_body() -> None:
    """Стили внутри <body> должны вырезаться: они занимают контекст и бесполезны."""
    html = "<body><style>.a{color:red}</style><p>Текст</p></body>"
    result = trim_html(html, max_tokens=100_000)

    assert result.stats.removed_styles == 1
    assert "color:red" not in result.html
    assert "Текст" in result.html


def test_replaces_base64_payloads() -> None:
    result = trim_html(build_html(), max_tokens=100_000)

    assert "base64,AAAA" not in result.html
    assert "[base64]" in result.html


def test_collapses_repeated_product_cards() -> None:
    """Ради этого шага всё и делается: 12 карточек не должны съесть весь контекст."""
    html = build_html(cards=12)
    result = trim_html(html, max_tokens=100_000)

    assert result.stats.collapsed_duplicates == 9  # 12 карточек минус 3 показанные
    assert "скрыто ещё 9 однотипных" in result.html
    # Три примера карточек остаются — по ним видно структуру.
    assert result.html.count('class="product-card" data-sku=') == 3


def test_keeps_semantic_attributes_and_drops_noise() -> None:
    html = """
    <div class="card" id="main-card" onclick="doEvil()" data-sku="X1"
         style="color:red" aria-label="Карточка" tabindex="0">
      <input type="text" name="q" placeholder="Поиск" value="тест" />
    </div>
    """
    result = trim_html(html, max_tokens=100_000)

    assert 'class="card"' in result.html
    assert 'id="main-card"' in result.html
    assert 'data-sku="X1"' in result.html
    assert 'aria-label="Карточка"' in result.html
    assert 'placeholder="Поиск"' in result.html
    assert "onclick" not in result.html
    assert "doEvil" not in result.html
    assert "style=" not in result.html
    assert "tabindex" not in result.html  # не входит в список значимых


def test_makes_urls_absolute() -> None:
    html = '<a class="next" href="/catalog?page=2">Далее</a><img src="/img/logo.png" alt="l" />'
    result = trim_html(html, max_tokens=100_000, base_url="https://shop.example.com/catalog")

    assert 'href="https://shop.example.com/catalog?page=2"' in result.html
    assert 'src="https://shop.example.com/img/logo.png"' in result.html


def test_respects_token_limit_and_marks_truncation() -> None:
    html = build_html(cards=200)
    result = trim_html(html, max_tokens=200)

    assert result.stats.truncated is True
    assert result.stats.estimated_tokens <= 400  # предел плюс запас на пометку
    assert "середина страницы вырезана" in result.html
    # Начало и конец сохраняются: там поиск и пагинация.
    assert "search-input" in result.html
    assert "pagination" in result.html


def test_small_page_is_not_truncated() -> None:
    result = trim_html("<html><body><p>Привет</p></body></html>", max_tokens=1000)

    assert result.stats.truncated is False
    assert "Привет" in result.html


def test_extracts_title_and_meta() -> None:
    result = trim_html(build_html(), max_tokens=100_000)

    assert result.title == "Каталог товаров"
    assert result.meta.get("description") == "Описание каталога"
    assert result.meta.get("og:title") == "Каталог товаров"


def test_compression_ratio_is_meaningful() -> None:
    result = trim_html(build_html(cards=30), max_tokens=100_000)

    assert result.stats.compression_ratio > 1.5
    assert result.stats.original_bytes > result.stats.trimmed_bytes


def test_estimate_tokens_is_monotonic() -> None:
    assert estimate_tokens("") >= 1
    assert estimate_tokens("a" * 100) > estimate_tokens("a" * 10)


def test_normalize_url_helpers() -> None:
    assert normalize_url("/x", "https://a.com/b") == "https://a.com/x"
    assert normalize_url("https://a.com/x") == "https://a.com/x"
    assert normalize_url("data:image/png;base64,AAA") == "data:image/png;base64,AAA"
    assert normalize_url("#anchor") == "#anchor"
