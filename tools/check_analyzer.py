"""Сквозная проверка Этапа 2: браузер → снапшот → карта элементов.

Запуск: .venv\\Scripts\\python.exe tools/check_analyzer.py

Что происходит:

1. поднимается локальный сайт-стенд (каталог с карточками, поиском, пагинацией,
   баннером о cookie и JSON-источником данных);
2. Chromium через штатный код UPA снимает снапшот страницы;
3. анализатор строит карту элементов: роли, селекторы, группы повторов, отчёт;
4. проверяется, что ключевые роли и устойчивые селекторы найдены, а карта
   сохранена в базе.

Так проверяется весь путь целиком — от живой страницы до карты, которой будет
пользоваться движок извлечения (Этап 4).
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.analyzer import service as analyze  # noqa: E402
from app.analyzer.roles import Role  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.db import dispose_engine, init_engine, session_scope  # noqa: E402
from app.crawler import service as crawl  # noqa: E402
from app.storage import Base  # noqa: E402

PRODUCTS = {
    "items": [
        {
            "id": index,
            "sku": f"SKU-{index:03d}",
            "name": f"Перфоратор модель {index}",
            "price": 1000 + index * 137,
        }
        for index in range(1, 25)
    ]
}

PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Каталог электроинструмента — Стенд UPA</title>
  <meta name="description" content="Каталог инструмента: 24 позиции">
  <style>.card{border:1px solid #eee}</style>
</head>
<body>
  <div id="cookie" class="cookie-consent"><button class="cookie-accept">Принять все</button></div>
  <header class="site-header">
    <form class="search-form" role="search" action="/search" method="get">
      <input type="search" name="q" id="search-input" placeholder="Поиск по каталогу">
      <button type="submit" class="search-form__submit">Найти</button>
    </form>
    <nav class="main-nav"><a href="/">Главная</a><a href="/catalog">Каталог</a></nav>
  </header>
  <main>
    <h1>Каталог</h1>
    <aside class="filters">
      <select name="brand" class="filter-form__brand"><option>Bosch</option><option>Makita</option></select>
      <select name="sort" class="sort__select"><option>По цене</option><option>По названию</option></select>
    </aside>
    <div id="grid" class="product-grid"></div>
    <nav class="pagination" aria-label="Пагинация">
      <a class="pagination__prev" rel="prev" href="/catalog?page=1">Назад</a>
      <a class="pagination__next" rel="next" href="/catalog?page=3">Следующая</a>
    </nav>
  </main>
  <script>
    fetch('/api/products').then(function (r) { return r.json(); }).then(function (data) {
      var html = '';
      data.items.forEach(function (item) {
        html += '<article class="product-card" data-sku="' + item.sku + '">' +
          '<a class="product-card__link" href="/product/' + item.id + '">' +
          '<img class="product-card__image" src="/img/' + item.id + '.jpg" alt="' + item.name + '">' +
          '<h3 class="product-card__title">' + item.name + '</h3></a>' +
          '<span class="product-card__price" itemprop="price">' + item.price + ' ₽</span>' +
          '<p class="product-card__description">Инструмент для профессионалов</p>' +
          '<button class="product-card__buy" data-action="add-to-cart">В корзину</button>' +
          '</article>';
      });
      document.getElementById('grid').innerHTML = html;
    });
  </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    """Мини-сайт: страница каталога и JSON-API."""

    def do_GET(self) -> None:  # noqa: N802 — имя задано базовым классом
        path = self.path.split("?")[0]
        if path == "/api/products":
            self._send(json.dumps(PRODUCTS, ensure_ascii=False).encode("utf-8"), "application/json")
            return
        if path == "/":
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        self._send(b"ok", "text/plain; charset=utf-8")

    def _send(self, payload: bytes, mime: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Set-Cookie", "stand=1; Path=/")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args: object) -> None:
        return


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{port}/"

    settings = Settings()
    settings.data_dir = ROOT / "data"
    settings.artifacts_dir = settings.data_dir / "artifacts"
    settings.llm_provider = "none"
    settings.browser_settle_ms = 800
    settings.ensure_directories()

    failures: list[str] = []
    try:
        asyncio.run(run_check(settings, base_url, failures))
    finally:
        server.shutdown()
        server.server_close()

    print()
    if failures:
        print("ПРОВАЛЕНО:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("СКВОЗНАЯ ПРОВЕРКА АНАЛИЗА ПРОЙДЕНА")
    return 0


async def run_check(settings: Settings, base_url: str, failures: list[str]) -> None:
    engine = init_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    def check(name: str, condition: bool, detail: str = "") -> None:
        mark = "OK  " if condition else "НЕТ "
        print(f"  {mark} {name}{(' — ' + detail) if detail else ''}")
        if not condition:
            failures.append(name)

    print(f"=== Стенд: {base_url} ===")
    print()
    print("=== 1. Съёмка снапшота настоящим браузером ===")
    async with session_scope() as db:
        captured = await crawl.capture(db, settings, base_url, allow_local=True)
    snapshot = captured.snapshot
    check("страница открыта", captured.raw.http_status == 200, f"HTTP {captured.raw.http_status}")
    check(
        "контент дорисован скриптом",
        "product-card" in captured.raw.html,
        f"{captured.raw.html.count('product-card')} упоминаний в DOM",
    )
    check("баннер cookie закрыт", captured.raw.cookie_banner_closed is True)
    check(
        "JSON-источник перехвачен",
        len(captured.raw.data_sources) >= 1,
        f"{len(captured.raw.data_sources)} источников",
    )
    check("скрыто повторов при обрезке", captured.raw.trimmed.stats.collapsed_duplicates == 21,
          f"{captured.raw.trimmed.stats.collapsed_duplicates} из 24")

    print()
    print("=== 2. Построение карты элементов ===")
    async with session_scope() as db:
        outcome = await analyze.analyze_snapshot(db, settings, snapshot.id, use_llm=False)
    record = outcome.element_map
    elements = record.elements or []
    by_role: dict[str, dict] = {}
    for element in elements:
        by_role.setdefault(str(element["role"]), element)

    check("карта сохранена", bool(record.id))
    check("элементы размечены", len(elements) > 0, f"{len(elements)} элементов")
    check("отчёт сформирован", bool(record.summary))
    check("селекторы-кандидаты сохранены",
          all(len(element.get("selectors", [])) >= 1 for element in elements))

    print()
    print("=== 3. Ключевые роли найдены ===")
    for role in (
        Role.LIST_CONTAINER,
        Role.SEARCH_INPUT,
        Role.PAGINATION_NEXT,
        Role.ITEM_TITLE,
        Role.ITEM_PRICE,
        Role.ITEM_LINK,
        Role.ITEM_IMAGE,
        Role.SORT,
    ):
        found = by_role.get(role.value)
        check(
            f"роль «{role.value}»",
            found is not None,
            (found or {}).get("selector", "") if found else "не найдена",
        )

    print()
    print("=== 4. Список распознан с полным размером ===")
    best = outcome.analysis.best_repeat
    check("группа повторов найдена", best is not None)
    if best is not None:
        check("полный размер списка", best.real_count == 24, f"{best.real_count}")
        check(
            "обрезка учтена",
            best.count == 3 and best.collapsed == 21,
            f"в DOM {best.count}, скрыто {best.collapsed}",
        )
        check(
            "похожесть элементов высокая",
            best.similarity > 0.8,
            f"{best.similarity:.0%}",
        )

    print()
    print("=== 5. Селекторы пригодны для работы ===")
    price = by_role.get(Role.ITEM_PRICE.value)
    if price:
        check(
            "у цены есть микроразметка или говорящий класс",
            "itemprop" in price["selector"] or "product-card" in price["selector"],
            price["selector"],
        )
        check("цена помечена как повторяющаяся", price["count"] == 24, f"×{price['count']}")
    search = by_role.get(Role.SEARCH_INPUT.value)
    if search:
        check(
            "поле поиска имеет устойчивый селектор",
            search["selector_quality"] >= 0.6,
            f"{search['selector']} ({search['selector_quality']:.0%})",
        )
        check("поле поиска одиночное", search["count"] == 1)
    next_link = by_role.get(Role.PAGINATION_NEXT.value)
    if next_link:
        check("пагинация опознана по rel", "rel" in next_link["selector"], next_link["selector"])

    print()
    print("=== 6. Запись читается из базы ===")
    async with session_scope() as db:
        stored = await analyze.require_element_map(db, snapshot.id)
    check("карта доступна по снапшоту", stored.id == record.id)
    check("версия карты", stored.version >= 1, f"v{stored.version}")
    check("средняя уверенность посчитана", stored.confidence is not None,
          f"{stored.confidence}")

    print()
    print("=== 7. Фрагмент отчёта ===")
    for line in (record.summary or "").splitlines():
        if line.strip():
            print(f"    {line}")
        if line.startswith("Что можно делать"):
            break

    await dispose_engine()


if __name__ == "__main__":
    sys.exit(main())
