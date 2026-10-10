"""Проверка живого API UPA: поднимает сервер и опрашивает эндпоинты.

Запуск: .venv\\Scripts\\python.exe tools/smoke_api.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
BACKEND = ROOT / "backend"
PORT = 8023
BASE = f"http://127.0.0.1:{PORT}"
LOG_PATH = ROOT / "data" / "_smoke-api.log"

# Запросы идут напрямую: никакие прокси из окружения не должны вмешиваться.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(path: str, timeout: float = 10.0) -> tuple[int, str]:
    """Возвращает (код ответа, тело)."""
    request = urllib.request.Request(f"{BASE}{path}", headers={"Accept": "application/json"})
    try:
        with OPENER.open(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def wait_for_server(attempts: int = 15) -> bool:
    """Ждёт готовности сервера.

    Таймаут запроса намеренно большой: в ограниченном окружении первый контакт с
    чужим сокетом может занимать несколько секунд.
    """
    last_error: str | None = None
    for _ in range(attempts):
        try:
            status, _ = get("/health", timeout=10.0)
            if status == 200:
                return True
            last_error = f"код {status}"
        except Exception as exc:  # noqa: BLE001 — сервер ещё поднимается
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.5)
    print(f"последняя ошибка соединения: {last_error}")
    return False


def main() -> int:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = LOG_PATH.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [str(PYTHON), "-u", "-m", "app", "serve", "--port", str(PORT)],
        cwd=str(BACKEND),
        env={
            **__import__("os").environ,
            "PYTHONPATH": str(BACKEND),
            "PYTHONIOENCODING": "utf-8",
        },
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    failures: list[str] = []
    try:
        if not wait_for_server():
            print(f"СЕРВЕР НЕ ОТВЕТИЛ на {BASE} за 30 секунд")
            print(f"процесс жив: {process.poll() is None}")
            log_file.flush()
            print("--- лог сервера ---")
            print(LOG_PATH.read_text(encoding="utf-8", errors="replace").strip() or "(лог пуст)")
            return 1

        print("=== /health ===")
        status, body = get("/health")
        payload = json.loads(body)
        print(f"HTTP {status}, status={payload['status']}, версия={payload['version']}")
        for component in payload["components"]:
            print(f"  {component['name']:9} {component['status']:8} {component.get('detail') or ''}")
        if status != 200:
            failures.append("/health вернул не 200")

        print()
        print("=== /api/v1/system/info ===")
        status, body = get("/api/v1/system/info")
        info = json.loads(body)
        print(f"HTTP {status}, этап={info['stage']} — {info['stage_title']}")
        print(f"  data_dir={info['data_dir']}")
        print(f"  реализовано: {info['implemented']}")
        if status != 200:
            failures.append("/api/v1/system/info вернул не 200")

        print()
        print("=== /api/v1/sites и /api/v1/snapshots ===")
        for path in ("/api/v1/sites", "/api/v1/snapshots", "/api/v1/system/features", "/api/v1/system/roadmap", "/api/v1/system/llm"):
            status, body = get(path)
            data = json.loads(body)
            summary = f"total={data.get('total')}" if "total" in data else f"ключей={len(data)}"
            print(f"  HTTP {status} {path:32} {summary}")
            if status != 200:
                failures.append(f"{path} вернул {status}")

        print()
        print("=== Проверка валидации (локальный адрес запрещён) ===")
        request = urllib.request.Request(
            f"{BASE}/api/v1/snapshots",
            data=json.dumps({"url": "http://127.0.0.1:9999/"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with OPENER.open(request, timeout=10) as response:
                status, body = response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read().decode()
        print(f"  HTTP {status}: {body[:160]}")
        if status != 422:
            failures.append("локальный адрес не был отклонён с кодом 422")

        print()
        print("=== /openapi.json ===")
        status, body = get("/openapi.json")
        spec = json.loads(body)
        paths = sorted(spec["paths"])
        print(f"HTTP {status}, маршрутов: {len(paths)}")
        for path in paths:
            print(f"  {path}")
        if status != 200:
            failures.append("/openapi.json вернул не 200")

    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        log_file.close()

    print()
    if failures:
        print(f"ПРОВАЛЕНО: {len(failures)}")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
