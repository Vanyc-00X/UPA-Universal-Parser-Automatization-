"""Диагностика окружения: что уже установлено и доступно ли оно.

Запуск: python tools/probe_env.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULES = [
    "fastapi",
    "starlette",
    "uvicorn",
    "pydantic",
    "pydantic_settings",
    "sqlalchemy",
    "aiosqlite",
    "alembic",
    "httpx",
    "structlog",
    "multipart",
    "playwright",
    "pytest",
    "pytest_asyncio",
    "ruff",
    "black",
]


def main() -> int:
    print(f"Python {sys.version.split()[0]}")
    print(f"Исполняемый файл: {sys.executable}")
    print(f"В виртуальном окружении: {sys.prefix != sys.base_prefix}")
    print()
    print("Модули:")
    available = 0
    for name in MODULES:
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        available += int(found)
        print(f"  {name:20} {'есть' if found else 'нет'}")
    print()
    print(f"Итого доступно: {available} из {len(MODULES)}")

    print()
    print("Каталоги поиска:")
    for entry in sys.path:
        if not entry:
            continue
        print(f"  {entry}  {'<-- существует' if Path(entry).exists() else '<-- НЕТ'}")
    return 0 if available == len(MODULES) else 1


if __name__ == "__main__":
    sys.exit(main())
