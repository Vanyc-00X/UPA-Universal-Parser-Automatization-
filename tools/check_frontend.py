"""Проверка веб-интерфейса: Vite отдаёт страницу, а прокси ведёт к API.

Запуск: .venv\\Scripts\\python.exe tools/check_frontend.py

Проверяет три вещи:

1. dev-сервер Vite отдаёт HTML с корневым элементом и заголовком;
2. прокси Vite перенаправляет ``/health`` на API (то есть фронтенд действительно
   подключён к бэкенду, а не работает в вакууме);
3. сборка ``frontend/dist`` существует, если её выполняли.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
NODE = Path(
    r"C:\Users\Admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"
)
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"
WEB_PORT = 5175
API_PORT = 8027
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch(url: str, timeout: float = 15.0) -> tuple[int, str]:
    with OPENER.open(url, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def wait_for(url: str, attempts: int = 15) -> bool:
    last = ""
    for _ in range(attempts):
        try:
            status, _body = fetch(url, timeout=10.0)
            if status == 200:
                return True
            last = f"код {status}"
        except Exception as exc:  # noqa: BLE001 — сервер ещё поднимается
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(1.0)
    print(f"  не дождались {url}: {last}")
    return False


def main() -> int:
    if not NODE.exists():
        print(f"Node не найден: {NODE}")
        return 1

    failures: list[str] = []

    api_log = (ROOT / "data" / "_front-api.log").open("w", encoding="utf-8")
    web_log = (ROOT / "data" / "_front-web.log").open("w", encoding="utf-8")

    api = subprocess.Popen(
        [str(PYTHON), "-u", "-m", "app", "serve", "--port", str(API_PORT)],
        cwd=str(BACKEND),
        env={**os.environ, "PYTHONPATH": str(BACKEND), "PYTHONIOENCODING": "utf-8"},
        stdout=api_log,
        stderr=subprocess.STDOUT,
    )
    web = subprocess.Popen(
        [
            str(NODE),
            str(FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"),
            "--port",
            str(WEB_PORT),
            "--strictPort",
        ],
        cwd=str(FRONTEND),
        env={
            **os.environ,
            "UPA_API_TARGET": f"http://127.0.0.1:{API_PORT}",
            "PATH": f"{NODE.parent}{os.pathsep}{os.environ.get('PATH', '')}",
        },
        stdout=web_log,
        stderr=subprocess.STDOUT,
    )

    try:
        print("=== 1. API ===")
        if wait_for(f"http://127.0.0.1:{API_PORT}/health"):
            status, body = fetch(f"http://127.0.0.1:{API_PORT}/health")
            print(f"  HTTP {status}: {body[:120]}")
        else:
            failures.append("API не поднялся")

        print()
        print("=== 2. Vite: отдача страницы ===")
        web_url = f"http://127.0.0.1:{WEB_PORT}/"
        if wait_for(web_url):
            status, body = fetch(web_url)
            print(f"  HTTP {status}, размер {len(body)} байт")
            checks = {
                "корневой элемент #root": 'id="root"' in body,
                "заголовок UPA": "UPA" in body,
                "подключён main.tsx": "main.tsx" in body,
                "язык ru": 'lang="ru"' in body,
            }
            for name, ok in checks.items():
                print(f"  {'OK  ' if ok else 'НЕТ '} {name}")
                if not ok:
                    failures.append(f"HTML интерфейса: {name}")
        else:
            failures.append("Vite не поднялся")

        print()
        print("=== 3. Прокси Vite → API ===")
        try:
            status, body = fetch(f"http://127.0.0.1:{WEB_PORT}/health")
            print(f"  /health через прокси: HTTP {status}")
            print(f"  тело: {body[:140]}")
            if status != 200 or '"status"' not in body:
                failures.append("прокси Vite не донёс запрос до API")
        except Exception as exc:  # noqa: BLE001
            print(f"  СБОЙ: {type(exc).__name__}: {exc}")
            failures.append("прокси Vite недоступен")

        print()
        print("=== 4. Сборка frontend/dist ===")
        dist = FRONTEND / "dist" / "index.html"
        if dist.is_file():
            size = dist.stat().st_size
            assets = list((FRONTEND / "dist" / "assets").glob("*")) if (FRONTEND / "dist" / "assets").is_dir() else []
            print(f"  dist/index.html есть ({size} байт), файлов в assets: {len(assets)}")
        else:
            print("  сборка не выполнялась (dist отсутствует) — это не ошибка")

    finally:
        for process, log in ((web, web_log), (api, api_log)):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            log.close()

    if failures:
        print()
        print("=== ЛОГ VITE (последние строки) ===")
        print((ROOT / "data" / "_front-web.log").read_text(encoding="utf-8", errors="replace")[-1500:])
        print()
        print(f"ПРОВАЛЕНО: {len(failures)}")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print()
    print("ИНТЕРФЕЙС ПРОВЕРЕН: страница отдаётся, прокси ведёт к API")
    return 0


if __name__ == "__main__":
    sys.exit(main())
