"""Доступ к базе данных: асинхронный движок, сессии, инициализация схемы."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _enable_sqlite_pragmas(engine: AsyncEngine) -> None:
    """Включает WAL и внешние ключи для SQLite (иначе их нет по умолчанию)."""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def init_engine(settings: Settings) -> AsyncEngine:
    """Создаёт (один раз) асинхронный движок и фабрику сессий."""
    global _engine, _session_factory
    if _engine is not None:
        return _engine

    settings.ensure_directories()
    # Для SQLite берём абсолютный путь: относительный зависел бы от текущего
    # рабочего каталога процесса, и CLI/Alembic открывали бы другую БД.
    url = settings.absolute_database_url
    if url.startswith("sqlite") and "+aiosqlite" not in url:
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)

    _engine = create_async_engine(
        url,
        echo=False,
        future=True,
        pool_pre_ping=True,
    )
    if url.startswith("sqlite"):
        _enable_sqlite_pragmas(_engine)

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    log.info("db.engine_ready", url=url)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Движок БД не инициализирован: вызовите init_engine()")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Фабрика сессий не инициализирована: вызовите init_engine()")
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Транзакционная область: коммит при успехе, откат при исключении."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncIterator[AsyncSession]:
    """Зависимость FastAPI, отдающая сессию БД."""
    async with session_scope() as session:
        yield session


async def dispose_engine() -> None:
    """Закрывает движок. Вызывается при остановке приложения."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        log.info("db.engine_disposed")
    _engine = None
    _session_factory = None
