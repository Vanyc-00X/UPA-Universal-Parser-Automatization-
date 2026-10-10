"""Набор синтетических страниц для проверки анализа.

Каждая страница повторяет характерный тип сайта: каталог с карточками, таблица
прайса, лента новостей, SPA с дорисованным контентом, форма за логином. Набор
нужен, чтобы проверять детерминированный анализ без выхода в интернет — внешние
сайты нестабильны и непригодны для автотестов.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SiteFixture:
    """Тестовая страница и то, что анализатор обязан на ней найти."""

    key: str
    title: str
    html: str
    # Ожидаемые роли, которые обязательно должны быть найдены.
    expected_roles: tuple[str, ...]
    # Ожидаемое число элементов в основном списке (None — не проверяем).
    expected_repeat_count: int | None = None
    # Роли, которых быть не должно (защита от ложных срабатываний).
    forbidden_roles: tuple[str, ...] = ()


STYLE = "<style>.card{border:1px solid #eee}.price{color:red}</style>"


def _cards(count: int, *, tag: str = "div", item_class: str = "product-card") -> str:
    """Список карточек товара."""
    items = "".join(f"""
        <{tag} class="{item_class}" data-id="{index}">
          <a class="product-card__link" href="/product/{index}">
            <img class="product-card__image" src="/img/{index}.jpg" alt="Товар {index}">
            <h3 class="product-card__title">{index}. Товар номер {index}</h3>
          </a>
          <span class="product-card__price" itemprop="price">{index * 250} ₽</span>
          <p class="product-card__description">Описание товара {index} для каталога</p>
        </{tag}>
        """ for index in range(1, count + 1))
    return f'<div class="product-list">{items}</div>'


def _table_rows(count: int) -> str:
    rows = "".join(
        f"""
        <tr class="price-row">
          <td class="price-row__name">{name}</td>
          <td class="price-row__article">ART-{1000 + index}</td>
          <td class="price-row__price">{1000 + index * 137} ₽</td>
        </tr>
        """
        for index, name in enumerate(
            ["Болгарка", "Перфоратор", "Шуруповёрт", "Дрель", "Лобзик", "Рубанок"][:count]
        )
    )
    return f"""
    <table class="price-table">
      <thead><tr><th>Наименование</th><th>Артикул</th><th>Цена</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


def _pagination() -> str:
    return """
    <nav class="pagination" aria-label="Пагинация">
      <a class="pagination__prev" rel="prev" href="/catalog?page=1">Назад</a>
      <a class="pagination__page" href="/catalog?page=2">2</a>
      <a class="pagination__page" href="/catalog?page=3">3</a>
      <a class="pagination__next" rel="next" href="/catalog?page=3">Следующая</a>
    </nav>
    """


def _search_form() -> str:
    return """
    <header class="site-header">
      <form class="search-form" role="search" action="/search" method="get">
        <input type="search" name="q" id="search-input" placeholder="Поиск по каталогу">
        <button type="submit" class="search-form__submit">Найти</button>
      </form>
    </header>
    """


def _footer() -> str:
    return """
    <footer class="site-footer">
      <nav class="footer-nav"><a href="/about">О компании</a><a href="/contacts">Контакты</a></nav>
      <p class="copyright">© 2026 Магазин</p>
    </footer>
    """


# ---------------------------------------------------------------------------
# 1. Каталог интернет-магазина (главный случай)
# ---------------------------------------------------------------------------

CATALOG = SiteFixture(
    key="catalog",
    title="Каталог интернет-магазина",
    html=f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Каталог товаров — Магазин</title>
<meta name="description" content="Каталог электроинструмента">{STYLE}</head>
<body>
{_search_form()}
<main class="content">
  <h1>Каталог</h1>
  <aside class="filters">
    <form class="filter-form" action="/catalog">
      <select name="brand" class="filter-form__brand"><option>Bosch</option><option>Makita</option></select>
      <input type="checkbox" name="in_stock" id="in-stock"><label for="in-stock">Только в наличии</label>
      <button type="submit" class="filter-form__apply">Применить фильтр</button>
    </form>
  </aside>
  {_cards(12)}
  {_pagination()}
</main>
{_footer()}
</body></html>""",
    expected_roles=(
        "list_container",
        "item_title",
        "item_price",
        "search_input",
        "pagination_next",
    ),
    expected_repeat_count=12,
)


# ---------------------------------------------------------------------------
# 2. Таблица с прайсом
# ---------------------------------------------------------------------------

PRICE_TABLE = SiteFixture(
    key="price_table",
    title="Таблица прайса",
    html=f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Прайс-лист — Инструмент</title></head>
<body>
<header class="site-header"><a href="/" class="logo">Инструмент</a></header>
<main>
  <h1>Прайс-лист</h1>
  {_table_rows(6)}
  <a class="pagination__next" rel="next" href="/price?page=2">Следующая страница</a>
</main>
</body></html>""",
    expected_roles=("table", "pagination_next", "heading"),
    expected_repeat_count=6,
)


# ---------------------------------------------------------------------------
# 3. Лента новостей
# ---------------------------------------------------------------------------

NEWS_FEED = SiteFixture(
    key="news_feed",
    title="Лента новостей",
    html=f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Новости — Портал</title>
<meta property="og:title" content="Новости">{STYLE}</head>
<body>
<nav class="main-nav"><a href="/">Главная</a><a href="/news">Новости</a></nav>
<main class="news-list">
  <article class="news-item">
    <a class="news-item__link" href="/news/1"><h2 class="news-item__title">Первая новость портала</h2></a>
    <time class="news-item__date" datetime="2026-01-01">1 января</time>
    <p class="news-item__summary">Краткое описание первой новости</p>
  </article>
  <article class="news-item">
    <a class="news-item__link" href="/news/2"><h2 class="news-item__title">Вторая новость портала</h2></a>
    <time class="news-item__date" datetime="2026-01-02">2 января</time>
    <p class="news-item__summary">Краткое описание второй новости</p>
  </article>
  <article class="news-item">
    <a class="news-item__link" href="/news/3"><h2 class="news-item__title">Третья новость портала</h2></a>
    <time class="news-item__date" datetime="2026-01-03">3 января</time>
    <p class="news-item__summary">Краткое описание третьей новости</p>
  </article>
  <article class="news-item">
    <a class="news-item__link" href="/news/4"><h2 class="news-item__title">Четвёртая новость портала</h2></a>
    <time class="news-item__date" datetime="2026-01-04">4 января</time>
    <p class="news-item__summary">Краткое описание четвёртой новости</p>
  </article>
  <button class="load-more" type="button">Показать ещё</button>
</main>
</body></html>""",
    expected_roles=("list_container", "item_title", "load_more", "navigation"),
    expected_repeat_count=4,
)


# ---------------------------------------------------------------------------
# 4. Каталог на списке ul/li с фильтрами
# ---------------------------------------------------------------------------

LIST_CATALOG = SiteFixture(
    key="list_catalog",
    title="Список объявлений",
    html="""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Объявления — Доска</title></head>
<body>
<main>
  <h1>Объявления</h1>
  <form class="search" role="search"><input type="search" name="q" placeholder="Что ищем?"><button type="submit">Искать</button></form>
  <div class="sort"><select name="sort" class="sort__select"><option>По дате</option><option>По цене</option></select></div>
  <ul class="ads-list">
    <li class="ad-item"><a class="ad-item__link" href="/ad/1"><span class="ad-item__title">Продам гараж</span></a><span class="ad-item__price">150 000 ₽</span></li>
    <li class="ad-item"><a class="ad-item__link" href="/ad/2"><span class="ad-item__title">Продам лодку</span></a><span class="ad-item__price">80 000 ₽</span></li>
    <li class="ad-item"><a class="ad-item__link" href="/ad/3"><span class="ad-item__title">Продам участок</span></a><span class="ad-item__price">300 000 ₽</span></li>
    <li class="ad-item"><a class="ad-item__link" href="/ad/4"><span class="ad-item__title">Продам мотоцикл</span></a><span class="ad-item__price">220 000 ₽</span></li>
    <li class="ad-item"><a class="ad-item__link" href="/ad/5"><span class="ad-item__title">Продам прицеп</span></a><span class="ad-item__price">45 000 ₽</span></li>
  </ul>
  <nav class="pagination"><a class="pagination__next" rel="next" href="/ads?page=2">Далее</a></nav>
</main>
</body></html>""",
    expected_roles=(
        "list_container",
        "item_title",
        "item_price",
        "search_input",
        "sort",
        "pagination_next",
    ),
    expected_repeat_count=5,
)


# ---------------------------------------------------------------------------
# 5. SPA с пустым каркасом (контент дорисовывается скриптом)
# ---------------------------------------------------------------------------

SPA_SHELL = SiteFixture(
    key="spa_shell",
    title="SPA-каркас",
    html="""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Приложение</title>
<script>window.__STATE__ = {};</script></head>
<body>
<div id="app">
  <div class="skeleton"><div class="skeleton__row"></div></div>
  <form role="search"><input type="search" name="q" placeholder="Поиск"><button type="submit">Найти</button></form>
</div>
</body></html>""",
    expected_roles=("search_input", "submit"),
)


# ---------------------------------------------------------------------------
# 6. Форма авторизации
# ---------------------------------------------------------------------------

LOGIN_FORM = SiteFixture(
    key="login_form",
    title="Форма входа",
    html="""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Вход в личный кабинет</title></head>
<body>
<main class="auth">
  <h1>Вход</h1>
  <form class="login-form" method="post" action="/login">
    <label for="email">Email</label>
    <input type="email" name="email" id="email" placeholder="you@example.com" required>
    <label for="password">Пароль</label>
    <input type="password" name="password" id="password" required>
    <input type="checkbox" name="remember" id="remember"><label for="remember">Запомнить меня</label>
    <button type="submit" class="login-form__submit">Войти</button>
  </form>
</main>
</body></html>""",
    expected_roles=("email_input", "password_input", "checkbox", "submit"),
)


# ---------------------------------------------------------------------------
# 7. Страница товара (одиночная, без списка)
# ---------------------------------------------------------------------------

PRODUCT_PAGE = SiteFixture(
    key="product_page",
    title="Карточка товара",
    html="""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Перфоратор Bosch — Магазин</title>
<meta property="og:title" content="Перфоратор Bosch"></head>
<body>
<main class="product">
  <h1 class="product__title" itemprop="name">Перфоратор Bosch GBH 2-26</h1>
  <img class="product__image" src="/img/bosch.jpg" alt="Перфоратор Bosch">
  <div class="product__price" itemprop="price">12 990 ₽</div>
  <p class="product__description" itemprop="description">Мощный перфоратор для бетона</p>
  <form class="add-to-cart" method="post" action="/cart">
    <input type="number" name="quantity" value="1" min="1" max="10">
    <button type="submit" class="add-to-cart__button">Добавить в корзину</button>
  </form>
</main>
</body></html>""",
    expected_roles=("heading", "number_input", "submit"),
    # На одиночной странице карточек быть не должно.
    forbidden_roles=("list_container",),
)


# ---------------------------------------------------------------------------
# 8. Каталог с нестандартными классами (проверка устойчивости к разметке)
# ---------------------------------------------------------------------------

UNUSUAL_MARKUP = SiteFixture(
    key="unusual_markup",
    title="Каталог без говорящих классов",
    html="""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Каталог</title></head>
<body>
<div id="root">
  <form role="search"><input type="search" name="q" aria-label="Поиск по каталогу"><button type="submit">Искать</button></form>
  <div data-testid="catalog-grid" class="css-1x2y3z">
    <div data-testid="catalog-item" class="css-9k8j7h"><span class="css-abc123">Позиция 1</span><span data-price="1000">1000</span></div>
    <div data-testid="catalog-item" class="css-9k8j7h"><span class="css-def456">Позиция 2</span><span data-price="2000">2000</span></div>
    <div data-testid="catalog-item" class="css-9k8j7h"><span class="css-ghi789">Позиция 3</span><span data-price="3000">3000</span></div>
    <div data-testid="catalog-item" class="css-9k8j7h"><span class="css-jkl012">Позиция 4</span><span data-price="4000">4000</span></div>
  </div>
  <a data-testid="pagination-next" rel="next" href="/page/2">Вперёд</a>
</div>
</body></html>""",
    expected_roles=("list_container", "search_input", "pagination_next"),
    expected_repeat_count=4,
)


# ---------------------------------------------------------------------------
# 9. Страница за логином с таблицей (личный кабинет)
# ---------------------------------------------------------------------------

DASHBOARD_TABLE = SiteFixture(
    key="dashboard_table",
    title="Личный кабинет с заказами",
    html="""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Мои заказы</title></head>
<body>
<nav class="cabinet-nav"><a href="/orders">Заказы</a><a href="/profile">Профиль</a></nav>
<main>
  <h1>Мои заказы</h1>
  <form class="orders-filter"><input type="date" name="from" aria-label="Дата с"><select name="status"><option>Все</option><option>Оплачен</option></select><button type="submit">Показать</button></form>
  <table class="orders-table">
    <thead><tr><th>Номер</th><th>Дата</th><th>Сумма</th></tr></thead>
    <tbody>
      <tr class="order-row"><td>10001</td><td>01.01.2026</td><td>5 600 ₽</td></tr>
      <tr class="order-row"><td>10002</td><td>02.01.2026</td><td>1 200 ₽</td></tr>
      <tr class="order-row"><td>10003</td><td>03.01.2026</td><td>8 900 ₽</td></tr>
    </tbody>
  </table>
</main>
</body></html>""",
    expected_roles=("table", "date_input", "select", "submit", "navigation"),
    expected_repeat_count=3,
)


# ---------------------------------------------------------------------------
# 10. Битый HTML: незакрытые теги и вложенные повторы
# ---------------------------------------------------------------------------

BROKEN_HTML = SiteFixture(
    key="broken_html",
    title="Битая вёрстка с вложенными повторами",
    # Тег <body> намеренно не закрыт, а строки таблицы — без </tr>.
    # Парсер обязан закрыть их сам и всё равно найти оба списка.
    html="""<html lang="ru"><head><title>Каталог с битой вёрсткой</title>
<body>
<form role="search"><input type="search" name="q" placeholder="Поиск"></form>
<div class="catalog">
  <div class="catalog-section">
    <div class="catalog-item"><span class="catalog-item__name">Позиция раз</span><span class="catalog-item__price">100 ₽</span></div>
    <div class="catalog-item"><span class="catalog-item__name">Позиция два</span><span class="catalog-item__price">200 ₽</span></div>
    <div class="catalog-item"><span class="catalog-item__name">Позиция три</span><span class="catalog-item__price">300 ₽</span></div>
  </div>
  <div class="catalog-section">
    <table class="spec-table">
      <tr><td class="spec-table__name">Позиция четыре</td><td class="spec-table__price">400 ₽</td>
      <tr><td class="spec-table__name">Позиция пять</td><td class="spec-table__price">500 ₽</td>
      <tr><td class="spec-table__name">Позиция шесть</td><td class="spec-table__price">600 ₽</td>
    </table>
  </div>
</div>
<a class="next-page" rel="next" href="/catalog?page=2">Следующая</a>
<br><img src="/img/1.jpg" alt="картинка">
""",
    expected_roles=("list_container", "search_input", "pagination_next", "table"),
    expected_repeat_count=3,
)


FIXTURES: tuple[SiteFixture, ...] = (
    CATALOG,
    PRICE_TABLE,
    NEWS_FEED,
    LIST_CATALOG,
    SPA_SHELL,
    LOGIN_FORM,
    PRODUCT_PAGE,
    UNUSUAL_MARKUP,
    DASHBOARD_TABLE,
    BROKEN_HTML,
)

FIXTURES_BY_KEY: dict[str, SiteFixture] = {item.key: item for item in FIXTURES}
