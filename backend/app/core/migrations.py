"""Запуск миграций Alembic из кода приложения.

Схема базы создаётся и обновляется только миграциями. Это важно: при старте
приложения нельзя вызывать ``create_all`` — он не добавляет новые колонки в
существующие таблицы, и обновление версии молча ломало бы базу.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config

from alembic import command
from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)

# backend/app/core/migrations.py -> backend
BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
ALEMBIC_DIR = BACKEND_DIR / "alembic"


def alembic_config(settings: Settings) -> Config:
    """Собирает конфигурацию Alembic для текущих настроек."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    # URL передаём абсолютным: alembic можно запускать из любого каталога.
    config.set_main_option(
        "sqlalchemy.url", settings.absolute_database_url.replace("+aiosqlite", "")
    )
    return config


def upgrade_to_head(settings: Settings) -> None:
    """Применяет все миграции. Идемпотентно: повторный вызов ничего не делает."""
    settings.ensure_directories()
    config = alembic_config(settings)
    command.upgrade(config, "head")
    log.info("db.migrations_applied", database=str(settings.database_path))
