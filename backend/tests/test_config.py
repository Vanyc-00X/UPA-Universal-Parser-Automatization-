"""Тесты конфигурации и ORM-схемы."""

from __future__ import annotations

from app.core.config import Settings
from app.storage import Base


def test_settings_derive_paths(settings: Settings) -> None:
    assert settings.env == "test"
    assert settings.sync_database_url.startswith("sqlite:///")
    assert "+aiosqlite" not in settings.sync_database_url
    assert settings.database_path is not None
    assert settings.data_dir.exists()


def test_settings_split_cors_origins_from_string(monkeypatch) -> None:
    monkeypatch.setenv("UPA_CORS_ORIGINS", "http://a.local, http://b.local")
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    current = Settings()
    assert current.cors_origins == ["http://a.local", "http://b.local"]
    reset_settings_cache()


def test_expected_tables_registered() -> None:
    """Схема должна содержать все сущности конвейера из PLAN.md."""
    expected = {
        "sites",
        "snapshots",
        "element_maps",
        "scenarios",
        "scenario_versions",
        "runs",
        "run_items",
        "artifacts",
    }
    assert expected <= set(Base.metadata.tables)
