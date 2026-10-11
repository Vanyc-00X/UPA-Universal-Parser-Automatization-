"""Сквозная проверка Этапа 3: редактор через живой HTTP API.

Запуск: .venv\\Scripts\\python.exe tools/check_editor.py

Что происходит:

1. поднимается локальный сайт-стенд и живой API UPA на свободном порту;
2. снимается снапшот настоящим браузером и строится карта элементов;
3. через HTTP проверяется работа редактора: инспектор, проверка селекторов,
   правка черновика, добавление поля по элементу, предпросмотр;
4. черновик сохраняется как сценарий, проверяется версионирование;
5. отдельно проверяется, что сценарий с неработающим селектором не сохраняется.

Здесь намеренно используется именно HTTP, а не вызовы функций: так проверяется
весь путь, которым пользуется интерфейс.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from tools.check_analyzer import Handler  # noqa: E402

PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
BACKEND = ROOT / "backend"
API_PORT = 8031
BASE = f"http://127.0.0.1:{API_PORT}"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(method: str, path: str, payload: dict | None = None, timeout: float = 120.0):
    """Запрос к живому API. Возвращает (код, разобранный JSON)."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method=method,
    )
    try:
        with OPENER.open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            return error.code, json.loads(body)
        except json.JSONDecodeError:
            return error.code, {"raw": body}


def wait_for_api(attempts: int = 20) -> bool:
    for _ in range(attempts):
        try:
            status, _payload = call("GET", "/health", timeout=10.0)
            if status == 200:
                return True
        except Exception:  # noqa: BLE001 — сервер ещё поднимается
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    site = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    site_port = site.server_address[1]
    threading.Thread(target=site.serve_forever, daemon=True).start()
    site_url = f"http://127.0.0.1:{site_port}/"

    # Своя база и свои артефакты: проверка не должна трогать рабочие данные
    # разработчика и не должна зависеть от того, что там уже накопилось.
    work_dir = ROOT / "data" / "_editor-check"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    (work_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    database = work_dir / "check.db"

    log_path = work_dir / "_api.log"

    env = {
        **os.environ,
        "PYTHONPATH": str(BACKEND),
        "PYTHONIOENCODING": "utf-8",
        "TEMP": str(work_dir),
        "TMP": str(work_dir),
        "UPA_DATABASE_URL": f"sqlite+aiosqlite:///{database.as_posix()}",
        "UPA_LOG_LEVEL": "WARNING",
    }
    browsers = ROOT / "data" / "_pw-browsers"
    if browsers.is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)

    log_file = log_path.open("w", encoding="utf-8")
    api = subprocess.Popen(
        [str(PYTHON), "-u", "-m", "app", "serve", "--port", str(API_PORT)],
        cwd=str(BACKEND),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        mark = "OK  " if condition else "НЕТ "
        print(f"  {mark} {name}{(' — ' + detail) if detail else ''}")
        if not condition:
            failures.append(name)

    try:
        if not wait_for_api():
            print("API НЕ ОТВЕЧАЕТ")
            log_file.flush()
            print(log_path.read_text(encoding="utf-8", errors="replace")[-1500:])
            return 1

        print(f"=== Стенд: {site_url} ===")
        print()
        print("=== 1. Снапшот и карта элементов ===")
        status, snapshot = call("POST", "/api/v1/snapshots", {"url": site_url, "allow_local": True})
        check("снапшот снят", status == 200, f"HTTP {status}")
        snapshot_id = (snapshot or {}).get("id", "")
        check("снапшот пригоден для анализа", bool(snapshot_id))

        status, _map = call(
            "POST", f"/api/v1/snapshots/{snapshot_id}/analyze", {"use_llm": False}
        )
        check("карта элементов построена", status == 200, f"HTTP {status}")

        print()
        print("=== 2. Инспектор страницы ===")
        status, inspector = call("GET", f"/api/v1/snapshots/{snapshot_id}/inspector")
        check("инспектор отдаёт узлы", status == 200 and bool(inspector.get("nodes")))
        nodes = inspector.get("nodes", [])
        check("узлов больше десяти", len(nodes) > 10, str(len(nodes)))
        check(
            "у узлов есть рамки на странице",
            all(node["box"].get("height", 0) > 0 for node in nodes[:20]),
        )
        check(
            "узлы карты отмечены в инспекторе",
            any(node["matched_by"] for node in nodes),
        )
        linked = [node for node in nodes if node["parent_id"]]
        check("связи родителей заполнены", len(linked) > 5, f"{len(linked)} узлов с родителем")

        print()
        print("=== 3. Проверка селекторов ===")
        status, report = call(
            "POST",
            f"/api/v1/snapshots/{snapshot_id}/element-selector",
            {"selector": "article.product-card"},
        )
        check("селектор карточек проверен", status == 200 and report["valid"])
        cards_in_dom = report.get("count", 0)
        check("обрезка оставила несколько карточек", cards_in_dom == 3, str(cards_in_dom))

        status, empty = call(
            "POST",
            f"/api/v1/snapshots/{snapshot_id}/element-selector",
            {"selector": ".no-such-element"},
        )
        check("неработающий селектор честно сообщает 0", empty.get("count") == 0)

        status, invalid = call(
            "POST",
            f"/api/v1/snapshots/{snapshot_id}/element-selector",
            {"selector": "div:has(> span)"},
        )
        check(
            "неподдерживаемый селектор помечен как неподдерживаемый",
            invalid.get("valid") is False and bool(invalid.get("error")),
        )

        print()
        print("=== 4. Черновик сценария ===")
        status, state = call("GET", f"/api/v1/snapshots/{snapshot_id}/draft")
        check("черновик получен", status == 200)
        check("базовый сценарий содержит поля", bool(state["baseline"]["fields"]))
        check(
            "полный размер списка известен",
            state["items_expected"] == 24,
            str(state["items_expected"]),
        )
        check(
            "число записей в обрезанном DOM известно",
            state["items_in_dom"] == 3,
            str(state["items_in_dom"]),
        )
        check("проверка полей выполнена", bool(state["validation"]["fields"]))
        broken = [
            field
            for field in state["validation"]["fields"]
            if field["status"] not in {"ok", "partial"}
        ]
        check(
            "поля базового сценария находят данные",
            not broken,
            f"проблемных: {len(broken)}",
        )
        check("селектор ссылки берёт href", any(
            field["strategy"] == "attribute" and field["attribute"] == "href"
            for field in state["draft"]["fields"]
        ))
        check("переход по страницам распознан", state["draft"]["pagination"]["kind"] != "none",
              state["draft"]["pagination"]["kind"])

        print()
        print("=== 5. Правки в редакторе ===")
        card_node = next(
            (node for node in nodes if "product-card" in node["classes"] and node["tag"] == "article"),
            None,
        )
        check("карточка найдена в инспекторе", card_node is not None)

        status, added = call(
            "POST",
            f"/api/v1/snapshots/{snapshot_id}/draft/fields/from-element",
            {"node_id": card_node["node_id"], "title": "Артикул"} if card_node else {},
        )
        check("поле добавлено по элементу", status == 200, f"HTTP {status}")
        field = next(
            (item for item in added.get("draft", {}).get("fields", []) if item["title"] == "Артикул"),
            None,
        )
        check("новое поле получило селектор и стратегию", field is not None and bool(field["selector"]))
        check(
            "новое поле проверено на живом DOM",
            any(item["key"] == (field or {}).get("key") for item in added["validation"]["fields"]),
        )

        status, renamed = call(
            "PATCH",
            f"/api/v1/snapshots/{snapshot_id}/draft/fields",
            {"key": (field or {}).get("key"), "title": "Артикул поставщика"},
        )
        check("поле переименовано", status == 200 and any(
            item["title"] == "Артикул поставщика" for item in renamed["draft"]["fields"]
        ))

        status, removed = call(
            "DELETE",
            f"/api/v1/snapshots/{snapshot_id}/draft/fields/{(field or {}).get('key')}",
        )
        check("поле удалено", status == 200 and all(
            item["title"] != "Артикул поставщика" for item in removed["draft"]["fields"]
        ))

        status, replay = call("POST", f"/api/v1/snapshots/{snapshot_id}/draft/reset")
        check("правки сброшены", status == 200 and replay["changed"] is False)

        print()
        print("=== 6. Предпросмотр собранных данных ===")
        status, preview = call("GET", f"/api/v1/snapshots/{snapshot_id}/draft/preview")
        check("предпросмотр получен", status == 200)
        price = next(
            (item for item in preview.get("fields", []) if item["key"] == "price"), None
        )
        check("значения цены видны", price is not None and bool(price["values"]))
        if price:
            print(f"       примеры цены: {', '.join(price['values'][:3])}")

        print()
        print("=== 7. Сохранение сценария и версии ===")
        status, saved = call(
            "POST",
            f"/api/v1/snapshots/{snapshot_id}/draft/save-as-scenario",
            {"name": "Каталог стенда", "change_note": "первая версия из редактора"},
        )
        check("сценарий сохранён", status == 200, f"HTTP {status}")
        check("это версия 1", saved.get("version") == 1, str(saved.get("version")))
        check("поля попали в сценарий", saved.get("fields", 0) > 0, str(saved.get("fields")))
        scenario_id = saved.get("scenario_id", "")

        status, second = call(
            "POST",
            f"/api/v1/snapshots/{snapshot_id}/draft/save-as-scenario",
            {"name": "Каталог стенда", "scenario_id": scenario_id, "change_note": "вторая версия"},
        )
        check("повторное сохранение добавило версию", second.get("version") == 2)
        check("сценарий остался тем же", second.get("scenario_id") == scenario_id)

        status, versions = call("GET", f"/api/v1/scenarios/{scenario_id}/versions")
        check(
            "история версий сохранена",
            status == 200 and [item["version"] for item in versions] == [2, 1],
            str([item["version"] for item in versions] if isinstance(versions, list) else versions),
        )
        first_version = next((item for item in versions if item["version"] == 1), None)
        check(
            "первая версия читается целиком",
            bool(first_version and first_version["definition"]["fields"]),
        )

        status, listing = call("GET", "/api/v1/scenarios")
        check("сценарий виден в списке", listing.get("total") == 1)

        print()
        print("=== 8. Защита от нерабочего сценария ===")
        status, broken = call(
            "PUT",
            f"/api/v1/snapshots/{snapshot_id}/draft",
            {
                "definition": {
                    **state["draft"],
                    "fields": state["draft"]["fields"]
                    + [
                        {
                            "key": "broken",
                            "title": "Сломанное поле",
                            "selector": ".no-such-element",
                            "strategy": "text",
                            "attribute": None,
                            "required": False,
                            "role": None,
                            "note": None,
                            "fallback_selectors": [],
                        }
                    ],
                }
            },
        )
        check("черновик со сломанным полем сохранён", status == 200)

        status, rejected = call(
            "POST",
            f"/api/v1/snapshots/{snapshot_id}/draft/save-as-scenario",
            {"name": "Плохой сценарий"},
        )
        check("сценарий с неработающим селектором не сохранён", status == 422, f"HTTP {status}")
        problems = (rejected or {}).get("error", {}).get("details", {}).get("problems", [])
        check(
            "причина отказа понятна",
            any("Сломанное поле" in problem for problem in problems),
            str(problems[:1]),
        )

        status, duplicate = call(
            "PUT",
            f"/api/v1/snapshots/{snapshot_id}/draft",
            {
                "definition": {
                    **state["draft"],
                    "fields": [
                        {"key": "same", "title": "Первое", "selector": "h1"},
                        {"key": "same", "title": "Дубликат", "selector": "h2"},
                    ],
                }
            },
        )
        check(
            "дубликаты имён полей отклонены с понятной ошибкой",
            duplicate == 422 or status == 422,
            f"HTTP {duplicate}",
        )
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api.kill()
        log_file.close()
        site.shutdown()
        site.server_close()

    print()
    if failures:
        print(f"ПРОВАЛЕНО: {len(failures)}")
        for failure in failures:
            print(f"  - {failure}")
        print()
        print("--- лог API (последние строки) ---")
        print(log_path.read_text(encoding="utf-8", errors="replace")[-1200:])
        return 1
    print("СКВОЗНАЯ ПРОВЕРКА РЕДАКТОРА ПРОЙДЕНА")
    return 0


if __name__ == "__main__":
    sys.exit(main())
