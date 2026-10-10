"""Проверка Этапа 1 настоящим браузером.

Запуск: .venv\\Scripts\\python.exe tools/check_browser.py

Поднимает локальный сайт-стенд, открывает его Chromium'ом через штатный код
UPA (:mod:`app.crawler`) и проверяет, что снапшот получился полноценным:
DOM и обрезка, скриншоты, сетевые запросы с JSON-источником, storage state,
закрытие баннера о cookie и кэш по хэшу DOM.

Стенд специально сделан «неудобным», как настоящие сайты: контент дорисовывается
скриптом после загрузки, есть баннер о cookie, повторяющиеся карточки товара,
данные приходят отдельным JSON-запросом.
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

from app.core.config import Settings  # noqa: E402
from app.core.db import dispose_engine, init_engine, session_scope  # noqa: E402
from app.crawler import service as crawl  # noqa: E402
from app.crawler import store  # noqa: E402
from app.storage import Base  # noqa: E402

PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Стенд UPA — каталог</title>
  <meta name="description" content="Тестовый каталог для проверки снапшота">
  <style>.card { border: 1px solid #eee; } .hidden { display: none; }</style>
</head>
<body>
  <div id="cookie" class="cookie-consent">
    <button class="cookie-accept" onclick="document.getElementById('cookie').remove()">
      Принять все
    </button>
  </div>
  <header class="site-header">
    <form role="search" action="/search" method="get">
      <input type="search" name="q" id="search-input" placeholder="Поиск по каталогу">
      <button type="submit">Найти</button>
    </form>
  </header>
  <main>
    <h1>Каталог</h1>
    <div id="list" class="product-list"></div>
    <nav class="pagination" aria-label="Пагинация">
      <a class="pagination__next" href="/catalog?page=2" rel="next">Следующая</a>
    </nav>
  </main>
  <script>
    // Контент появляется только после выполнения JS — как на настоящих SPA.
    fetch('/api/products?page=1')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var html = '';
        data.items.forEach(function (item) {
          html += '<div class="product-card" data-sku="' + item.sku + '">' +
            '<a class="product-card__link" href="/product/' + item.id + '">' +
            '<h3 class="product-card__title">' + item.name + '</h3></a>' +
            '<span class="product-card__price" itemprop="price">' + item.price + ' ₽</span>' +
            '<button class="product-card__buy" data-action="add-to-cart">В корзину</button>' +
            '</div>';
        });
        document.getElementById('list').innerHTML = html;
      });
  </script>
</body>
</html>
"""

PRODUCTS = {
    "items": [
        {"id": index, "sku": f"SKU-{index}", "name": f"Товар {index}", "price": index * 100}
        for index in range(1, 13)
    ]
}


class Handler(BaseHTTPRequestHandler):
    """Мини-сайт: HTML-страница, JSON-API и статика."""

    def do_GET(self) -> None:  # noqa: N802 — имя задано базовым классом
        path = self.path.split("?")[0]
        if path == "/api/products":
            payload = json.dumps(PRODUCTS, ensure_ascii=False).encode("utf-8")
            self._send(payload, "application/json; charset=utf-8")
            return
        if path == "/":
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        self._send(b"ok", "text/plain; charset=utf-8")

    def _send(self, payload: bytes, mime: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Set-Cookie", "stand_session=abc123; Path=/")
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
    settings.browser_headless = True
    settings.browser_settle_ms = 800
    settings.ensure_directories()

    failures: list[str] = []
    try:
        result = asyncio.run(run_check(settings, base_url, failures))
    finally:
        server.shutdown()
        server.server_close()

    print()
    if not result:
        print("ПРОВАЛЕНО:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("ПРОВЕРКА БРАУЗЕРОМ ПРОЙДЕНА")
    return 0


async def run_check(settings: Settings, base_url: str, failures: list[str]) -> bool:
    engine = init_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    print(f"=== Стенд: {base_url} ===")
    async with session_scope() as db:
        outcome = await crawl.capture(db, settings, base_url, allow_local=True)
    snapshot = outcome.snapshot
    raw = outcome.raw

    def check(name: str, condition: bool, detail: str = "") -> None:
        mark = "OK  " if condition else "НЕТ "
        print(f"  {mark} {name}{(' — ' + detail) if detail else ''}")
        if not condition:
            failures.append(name)

    print()
    print("=== Результат съёмки ===")
    check("страница открылась", raw.http_status == 200, f"HTTP {raw.http_status}")
    check("заголовок получен", raw.title == "Стенд UPA — каталог", repr(raw.title))
    check("язык определён", raw.lang == "ru", repr(raw.lang))
    check("хэш DOM посчитан", bool(raw.dom_hash), raw.dom_hash or "")

    print()
    print("=== Контент, дорисованный JavaScript ===")
    # В исходном HTML тот же атрибут встречается ещё и внутри <script> как часть
    # шаблона, поэтому считаем только элементы, а не подстроки.
    rendered_markers = raw.html.count('<div class="product-card" data-sku=')
    check(
        "карточки товара отрисованы скриптом",
        rendered_markers >= 12,
        f"в DOM найдено элементов-карточек: {rendered_markers} (ожидалось 12, "
        f"плюс строка шаблона в <script>)",
    )
    # В обрезанном DOM остаются только показательные карточки — так и задумано.
    kept_cards = raw.trimmed.html.count('<div class="product-card" data-sku=')
    check(
        "после обрезки остались показательные карточки",
        0 < kept_cards <= 3,
        f"осталось {kept_cards}",
    )
    check(
        "текст карточек сохранён",
        "Товар 1" in raw.trimmed.html and "В корзину" in raw.trimmed.html,
    )
    check("поле поиска найдено", 'id="search-input"' in raw.html)
    check("пагинация найдена", "pagination__next" in raw.html)

    print()
    print("=== Баннер о cookie ===")
    check("баннер закрыт", raw.cookie_banner_closed is True)
    check(
        "элемент баннера исчез из DOM",
        'id="cookie"' not in raw.html,
        "проверяем, что клик по «Принять все» сработал",
    )

    print()
    print("=== Сеть и источники данных ===")
    check("запросы записаны", len(raw.network) >= 2, f"{len(raw.network)} запросов")
    check("JSON-источник найден", len(raw.data_sources) >= 1,
          f"{len(raw.data_sources)} источников: {[e.url for e in raw.data_sources]}")
    if raw.data_sources:
        check("тело JSON прочитано", bool(raw.data_sources[0].body),
              (raw.data_sources[0].body or "")[:60])

    print()
    print("=== Скриншоты и состояние хранилища ===")
    check("скриншот viewport получен", bool(raw.screenshot),
          f"{len(raw.screenshot or b'')} байт")
    check("скриншот страницы целиком получен", bool(raw.screenshot_full),
          f"{len(raw.screenshot_full or b'')} байт")
    check("storage state сохранён", bool(raw.storage_state),
          f"cookies: {len((raw.storage_state or {}).get('cookies', []))}")

    print()
    print("=== Обрезка DOM ===")
    stats = raw.trimmed.stats
    check("скрипты удалены", stats.removed_scripts >= 1, str(stats.removed_scripts))
    # Стили этой страницы лежат в <head>. Обрезка работает с <body>, поэтому
    # проверяем не счётчик, а отсутствие правил CSS в том, что уходит в модель.
    check(
        "CSS не попал в результат",
        "border: 1px solid" not in raw.trimmed.html and "<style" not in raw.trimmed.html,
    )
    check(
        "повторы карточек схлопнуты",
        stats.collapsed_duplicates == 9,
        f"скрыто {stats.collapsed_duplicates} из 12",
    )
    check(
        "уложились в лимит токенов",
        stats.estimated_tokens <= settings.dom_max_tokens,
        f"{stats.estimated_tokens} <= {settings.dom_max_tokens}",
    )
    check("сжатие заметное", stats.compression_ratio > 1.5, f"{stats.compression_ratio}×")
    check("в обрезанном DOM есть текст", "Товар 1" in raw.trimmed.html)

    print()
    print("=== Артефакты на диске ===")
    for name in (
        store.PAGE_HTML,
        store.TRIMMED_HTML,
        store.NETWORK_JSON,
        store.DATA_SOURCES_JSON,
        store.STORAGE_STATE_JSON,
        store.SCREENSHOT_PNG,
        store.SCREENSHOT_FULL_PNG,
        store.SUMMARY_JSON,
    ):
        exists = store.snapshot_dir(settings, snapshot.id).joinpath(name).is_file()
        check(f"файл {name}", exists)
    check("запись в БД готова", snapshot.status.value == "ready", snapshot.status.value)
    check("токены записаны в БД", bool(snapshot.est_tokens), str(snapshot.est_tokens))

    print()
    print("=== Восстановление снапшота с диска ===")
    async with session_scope() as db:
        stored = await crawl.get_snapshot(db, snapshot.id)
        restored = crawl.raw_from_artifacts(settings, stored)
    check("снапшот восстановлен из артефактов", restored is not None)
    if restored:
        check("хэш DOM совпал", restored.dom_hash == raw.dom_hash)
        check("сетевые запросы восстановлены", len(restored.network) == len(raw.network))
        check("скриншот восстановлен", bool(restored.screenshot))

    print()
    print("=== Кэш по хэшу DOM ===")
    async with session_scope() as db:
        second = await crawl.capture(db, settings, base_url, use_cache=True, allow_local=True)
    check("второй снапшот переиспользовал артефакты", second.reused is True)
    check(
        "набор файлов совпадает",
        second.snapshot.artifacts == snapshot.artifacts,
    )
    check("ссылка на исходный снапшот сохранена",
          second.snapshot.meta.get("cached_snapshot_id") == snapshot.id)

    print()
    print(f"Снапшот: {snapshot.id}")
    print(f"  DOM: {snapshot.html_bytes} байт → {snapshot.trimmed_bytes} байт "
          f"({snapshot.est_tokens} токенов, {stats.compression_ratio}×)")

    await dispose_engine()
    return not failures


if __name__ == "__main__":
    sys.exit(main())
