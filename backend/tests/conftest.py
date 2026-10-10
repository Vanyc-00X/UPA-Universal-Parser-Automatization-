"""Общие фикстуры тестов.

Тесты работают с изолированной БД в tmp_path: приложение создаётся штатной
фабрикой :func:`app.main.create_app`, движок инициализируется один раз на тест.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import pytest_asyncio

from app.core.config import Settings, reset_settings_cache
from app.core.db import dispose_engine, init_engine
from app.main import create_app


@pytest.fixture
def settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Настройки для теста: своя БД, ИИ выключен, каталог данных во временной папке."""
    database_path = tmp_path / "upa-test.db"
    monkeypatch.setenv("UPA_ENV", "test")
    monkeypatch.setenv("UPA_DATABASE_URL", f"sqlite+aiosqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("UPA_LLM_PROVIDER", "none")
    monkeypatch.setenv("UPA_LOG_LEVEL", "WARNING")
    reset_settings_cache()

    current = Settings()
    # Каталоги данных уводим во временную папку, чтобы тесты не писали в репозиторий.
    current.data_dir = tmp_path / "data"
    current.artifacts_dir = current.data_dir / "artifacts"
    current.ensure_directories()

    yield current
    reset_settings_cache()


@pytest_asyncio.fixture(autouse=True)
async def db(settings: Settings):
    """Готовит изолированную схему БД. Нужна и API-тестам, и тестам сервисов."""
    engine = init_engine(settings)
    from app.storage import Base

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    yield engine

    await dispose_engine()


@pytest_asyncio.fixture
async def app(settings: Settings, db):
    """Приложение FastAPI поверх подготовленной БД."""
    return create_app(settings)


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP-клиент, работающий с приложением в одном процессе."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://upa.test") as http_client:
        yield http_client
