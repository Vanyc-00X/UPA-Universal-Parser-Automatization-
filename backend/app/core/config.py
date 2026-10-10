"""Конфигурация приложения.

Все настройки читаются из переменных окружения с префиксом ``UPA_`` и/или из
файла ``.env`` в корне репозитория. Секреты в коде не хранятся.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# backend/app/core/config.py -> backend/app/core -> backend/app -> backend -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[3]

# Поля-списки, которые задаются строкой через запятую. Для них отключается
# встроенный JSON-разбор pydantic-settings: иначе значение «a,b» ломает разбор.
COMMA_SEPARATED_FIELDS = {"cors_origins"}


class UpaEnvSettingsSource(EnvSettingsSource):
    """Источник настроек из переменных окружения с терпимым разбором списков.

    По умолчанию pydantic-settings пытается прочитать любое сложное поле (список)
    как JSON. Из-за этого привычное ``UPA_CORS_ORIGINS=http://a,http://b`` падает с
    ошибкой разбора. Здесь такие поля передаются в валидатор как обычная строка.
    """

    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        if field_name in COMMA_SEPARATED_FIELDS and isinstance(value, str):
            return value
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class Settings(BaseSettings):
    """Настройки UPA."""

    model_config = SettingsConfigDict(
        env_prefix="UPA_",
        env_file=(REPO_ROOT / ".env", REPO_ROOT / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Подменяет источник окружения на версию с терпимым разбором списков."""
        return (
            init_settings,
            UpaEnvSettingsSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )

    # --- Приложение ---------------------------------------------------------
    app_name: str = "UPA"
    env: Literal["dev", "test", "prod"] = "dev"
    debug: bool = True
    log_level: str = "INFO"
    log_json: bool = False

    # --- HTTP API -----------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8000
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )

    # --- Хранилище ----------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./data/upa.db"

    # --- Браузер (Этап 1) ---------------------------------------------------
    browser_headless: bool = True
    browser_timeout_ms: int = 30_000
    browser_locale: str = "ru-RU"
    browser_user_agent: str | None = None
    dom_max_tokens: int = 24_000
    # Размер окна: влияет на то, какие элементы вообще попадут в DOM (lazy-load).
    browser_viewport_width: int = 1440
    browser_viewport_height: int = 900
    # Сколько ждать «тишины» в сети после загрузки, мс.
    browser_settle_ms: int = 1_500
    # Ограничение объёма сохраняемых тел сетевых ответов (защита от гигантских JSON).
    network_body_limit_kb: int = 2048
    # Автоматически принимать диалоги (alert/confirm) при снятии снапшота.
    browser_auto_dismiss_dialogs: bool = True
    # Закрывать типовые баннеры о cookie, чтобы они не перекрывали контент.
    browser_dismiss_cookie_banners: bool = True

    # --- LLM ----------------------------------------------------------------
    llm_provider: Literal["ollama", "openai_compatible", "none"] = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    llm_cloud_fallback: bool = False
    llm_cloud_base_url: str = ""
    llm_cloud_api_key: str = ""
    llm_cloud_model: str = ""
    llm_timeout_s: int = 180

    # --- Артефакты ----------------------------------------------------------
    artifacts_retention_days: int = 30

    # --- Пути (вычисляются, не задаются извне) ------------------------------
    repo_root: Path = REPO_ROOT
    data_dir: Path = REPO_ROOT / "data"
    artifacts_dir: Path = REPO_ROOT / "data" / "artifacts"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Разрешает задавать список источников одной строкой через запятую."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    # --- Производные значения ----------------------------------------------
    @property
    def sync_database_url(self) -> str:
        """URL для синхронного драйвера (Alembic, миграции)."""
        return self.database_url.replace("+aiosqlite", "")

    @property
    def absolute_database_url(self) -> str:
        """URL с абсолютным путём к файлу БД.

        Это важно: относительный путь в SQLite резолвится от текущего рабочего
        каталога процесса, а не от корня репозитория. При запуске из ``backend/``
        (так делают CLI и Alembic) файл ``./data/upa.db`` указывал бы в
        ``backend/data/``, которого нет. Приложение обязано открывать одну и ту же
        БД независимо от того, откуда его запустили.
        """
        path = self.database_path
        if path is None:
            return self.database_url
        return f"sqlite+aiosqlite:///{path.as_posix()}"

    @property
    def database_path(self) -> Path | None:
        """Путь к файлу БД, если используется SQLite."""
        url = self.sync_database_url
        prefix = "sqlite:///"
        if not url.startswith(prefix):
            return None
        raw = url[len(prefix) :]
        path = Path(raw)
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        return path

    def ensure_directories(self) -> None:
        """Создаёт каталоги данных, если их ещё нет."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.database_path
        if db_path is not None:
            db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает единственный экземпляр настроек (кэшируется)."""
    return Settings()


def reset_settings_cache() -> None:
    """Сбрасывает кэш настроек. Нужно тестам."""
    get_settings.cache_clear()


settings = get_settings()
