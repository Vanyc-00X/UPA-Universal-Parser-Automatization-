"""Фикстуры-подделки для тестов Этапа 1.

Настоящий Chromium в тестах не запускается: снапшот подменяется на уровне
:func:`app.crawler.browser.capture_page`. Это позволяет проверить весь конвейер
(обрезка DOM, сохранение артефактов, запись в БД, API) без сети и браузера.
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.crawler import browser as browser_module
from app.crawler.browser import NetworkEntry, RawSnapshot, hash_html
from app.crawler.dom import trim_html

DATA_SOURCE_BODY = '{"items":[{"name":"Товар 1","price":1990},{"name":"Товар 2","price":2490}]}'


def build_form_html(*, title: str = "Форма заявки") -> str:
    """Страница с формой — для dry-run воркфлоу (Этап 7)."""
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
</head>
<body>
  <h1>{title}</h1>
  <form id="order-form" action="/submit" method="post">
    <label>Имя <input type="text" name="name" id="field-name" class="form-input" /></label>
    <label>Email <input type="email" name="email" id="field-email" class="form-input" /></label>
    <label>Город
      <select name="city" id="field-city">
        <option value="">—</option>
        <option value="msk">Москва</option>
        <option value="spb">Санкт-Петербург</option>
      </select>
    </label>
    <label><input type="checkbox" name="agree" id="field-agree" /> Согласен</label>
    <p class="form-hint">Заполните все поля</p>
    <button type="submit" id="btn-submit" class="btn-submit">Отправить</button>
  </form>
  <div class="success-message" hidden>Заявка принята</div>
</body>
</html>"""


def build_html(*, cards: int = 12, title: str = "Каталог товаров") -> str:
    """Синтетическая страница: скрипты, стили, cookie-баннер и список карточек."""
    cards_html = "".join(f"""
        <div class="product-card" data-sku="SKU-{index}">
          <a class="product-card__link" href="/product/{index}">
            <h3 class="product-card__title">Товар {index}</h3>
          </a>
          <span class="product-card__price" itemprop="price">{index * 100},00 ₽</span>
          <button class="product-card__buy" data-action="add-to-cart">В корзину</button>
        </div>
        """ for index in range(1, cards + 1))
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <meta name="description" content="Описание каталога" />
  <meta property="og:title" content="{title}" />
  <style>.product-card {{ color: #333; border: 1px solid #eee; }}</style>
  <script src="/static/app.js" defer></script>
</head>
<body>
  <div class="cookie-consent"><button class="cookie-accept">Принять все</button></div>
  <header class="site-header">
    <form role="search" action="/search" method="get">
      <input type="search" name="q" placeholder="Поиск по каталогу" id="search-input" />
      <button type="submit">Найти</button>
    </form>
  </header>
  <main>
    <h1>Каталог</h1>
    <div class="product-list" style="display:grid">
      {cards_html}
    </div>
    <nav class="pagination" aria-label="Пагинация">
      <a class="pagination__next" href="/catalog?page=2" rel="next">Следующая</a>
    </nav>
  </main>
  <img src="data:image/png;base64,{'A' * 200}" alt="tracker" />
  <svg width="24" height="24"><path d="M0 0h24v24H0z"/></svg>
  <!-- служебный комментарий, который не нужен модели -->
  <script src="https://analytics.example.com/tracker.js"></script>
</body>
</html>"""


def build_snapshot(
    settings: Settings,
    *,
    url: str = "https://shop.example.com/catalog",
    html: str | None = None,
    with_screenshot: bool = True,
) -> RawSnapshot:
    """Собирает RawSnapshot так, как это сделал бы браузер."""
    page_html = html if html is not None else build_html()
    final_url = "https://shop.example.com/catalog/"
    trimmed = trim_html(page_html, max_tokens=settings.dom_max_tokens, base_url=final_url)

    network = [
        NetworkEntry(
            url="https://shop.example.com/catalog/",
            method="GET",
            resource_type="document",
            status=200,
            mime="text/html; charset=utf-8",
            size_bytes=len(page_html.encode("utf-8")),
        ),
        NetworkEntry(
            url="https://shop.example.com/api/products?page=1",
            method="GET",
            resource_type="xhr",
            status=200,
            mime="application/json",
            size_bytes=len(DATA_SOURCE_BODY),
            body=DATA_SOURCE_BODY,
        ),
        NetworkEntry(
            url="https://cdn.example.com/logo.png",
            method="GET",
            resource_type="image",
            status=200,
            mime="image/png",
            size_bytes=1024,
        ),
    ]

    png = (
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c6300010000050001"
            "0d0a2db40000000049454e44ae426082"
        )
        if with_screenshot
        else None
    )

    snapshot = RawSnapshot(
        url=url,
        final_url=final_url,
        http_status=200,
        title="Каталог товаров",
        lang="ru",
        html=page_html,
        dom_hash=hash_html(page_html),
        trimmed=trimmed,
        html_bytes=len(page_html.encode("utf-8")),
        screenshot=png,
        screenshot_full=png,
        network=network,
        storage_state={"cookies": [{"name": "session", "value": "abc"}], "origins": []},
        console_errors=["Failed to load resource: 404"],
        blocked_requests=0,
        cookie_banner_closed=True,
        duration_ms=1234,
        viewport={"width": 1440, "height": 900},
    )
    # `extra` — то, что реальный браузер кладёт в Snapshot.meta. Берём его из
    # summary(), чтобы подделка не разъезжалась с настоящим кодом.
    snapshot.extra = dict(snapshot.summary())
    snapshot.extra["trim"] = trimmed.stats.as_dict()
    snapshot.extra["captured_at"] = "2026-01-01T00:00:00+00:00"
    return snapshot


def patch_capture(monkeypatch: Any, settings: Settings, **kwargs: Any) -> dict[str, int]:
    """Подменяет съёмку страницы. Возвращает счётчик вызовов."""
    calls = {"count": 0}

    async def _fake_capture(_settings: Settings, url: str) -> RawSnapshot:
        calls["count"] += 1
        options = dict(kwargs)
        options.setdefault("url", url)
        return build_snapshot(_settings, **options)

    monkeypatch.setattr(browser_module, "capture_page", _fake_capture)
    return calls
