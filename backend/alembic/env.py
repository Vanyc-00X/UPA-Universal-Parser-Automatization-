"""Окружение Alembic для UPA.

URL базы берётся из настроек приложения (``UPA_DATABASE_URL``), а не из
``alembic.ini`` — так миграции всегда идут в ту же БД, что и приложение.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Делаем пакет `app` импортируемым при запуске alembic из каталога backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.storage import Base  # noqa: E402  (регистрирует все модели)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
settings.ensure_directories()
# Абсолютный путь: alembic можно запускать из любого каталога.
config.set_main_option("sqlalchemy.url", settings.absolute_database_url.replace("+aiosqlite", ""))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Генерирует SQL без подключения к БД (``alembic upgrade head --sql``)."""
    context.configure(
        url=settings.absolute_database_url.replace("+aiosqlite", ""),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=settings.sync_database_url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Применяет миграции к реальной БД."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite не умеет ALTER COLUMN — batch-режим обязателен.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
