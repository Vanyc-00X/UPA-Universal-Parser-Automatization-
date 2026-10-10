"""ORM-модели UPA.

Сущности образуют цепочку «сайт → снапшот → карта элементов → сценарий → запуск»,
описанную в PLAN.md. Все идентификаторы — строковые UUID, чтобы их можно было
безопасно использовать в путях артефактов и в API.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    """Новый строковый идентификатор."""
    return uuid.uuid4().hex


def utcnow() -> datetime:
    """Текущее время в UTC (timezone-aware)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Базовый класс моделей."""


class TimestampMixin:
    """Метки создания и обновления записи."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Перечисления
# ---------------------------------------------------------------------------


class SnapshotStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class RunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunTrigger(str, enum.Enum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    RETRY = "retry"


# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------


class Site(TimestampMixin, Base):
    """Сайт, с которым работает пользователь."""

    __tablename__ = "sites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    origin: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    favicon_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Пользовательский ярлык в UI.
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    robots_txt: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_visited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    snapshots: Mapped[list[Snapshot]] = relationship(
        back_populates="site", cascade="all, delete-orphan", passive_deletes=True
    )
    scenarios: Mapped[list[Scenario]] = relationship(
        back_populates="site", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (Index("ix_sites_origin", "origin"),)


class Snapshot(TimestampMixin, Base):
    """Слепок страницы: DOM, скриншоты, сетевые запросы, storage state.

    Артефакты лежат в ``data/artifacts/<snapshot_id>/``, в БД хранятся только
    метаданные и относительные пути.
    """

    __tablename__ = "snapshots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    site_id: Mapped[str] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    final_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[SnapshotStatus] = mapped_column(
        SAEnum(SnapshotStatus, native_enum=False, length=16),
        default=SnapshotStatus.PENDING,
        nullable=False,
    )
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    lang: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Хэш финального DOM — ключ кэша и признак изменения вёрстки.
    dom_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Размеры: полный HTML и обрезанный (тот, что уходит в модель).
    html_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trimmed_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    est_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Сколько блоков-повторов схлопнула обрезка: видно, насколько страница «списочная».
    collapsed_blocks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    site: Mapped[Site] = relationship(back_populates="snapshots")
    element_map: Mapped[ElementMap | None] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )


class ElementMap(TimestampMixin, Base):
    """Карта элементов страницы: роли, описания, селекторы-кандидаты (Этап 2)."""

    __tablename__ = "element_maps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # Список элементов: см. app.api.schemas.ElementOut
    elements: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    # Полный человекочитаемый отчёт о странице: что найдено и за что отвечает.
    # В API отдаётся как поле report.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Какие ИИ-модель и промпт использовались (для воспроизводимости).
    llm_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    snapshot: Mapped[Snapshot] = relationship(back_populates="element_map")


class Scenario(TimestampMixin, Base):
    """Сценарий: переиспользуемый рецепт «что и откуда собирать»."""

    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    site_id: Mapped[str] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Тип сценария: collection (сбор данных) | form_fill (ввод данных, Этап 7).
    kind: Mapped[str] = mapped_column(String(32), default="collection", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    schedule_cron: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    site: Mapped[Site] = relationship(back_populates="scenarios")
    versions: Mapped[list[ScenarioVersion]] = relationship(
        back_populates="scenario",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ScenarioVersion.version",
    )
    runs: Mapped[list[Run]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (UniqueConstraint("site_id", "name", name="uq_scenarios_site_name"),)


class ScenarioVersion(TimestampMixin, Base):
    """Версия сценария. Изменения вёрстки порождают новую версию, а не потерю работы."""

    __tablename__ = "scenario_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    scenario_id: Mapped[str] = mapped_column(
        ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Полное описание сценария: шаги, поля, пагинация, лимиты.
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(32), default="user", nullable=False)

    scenario: Mapped[Scenario] = relationship(back_populates="versions")
    runs: Mapped[list[Run]] = relationship(back_populates="scenario_version")

    __table_args__ = (
        UniqueConstraint("scenario_id", "version", name="uq_scenario_versions_scenario_version"),
    )


class Run(TimestampMixin, Base):
    """Запуск сценария."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    scenario_id: Mapped[str] = mapped_column(
        ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scenario_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("scenario_versions.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus, native_enum=False, length=16),
        default=RunStatus.PENDING,
        nullable=False,
        index=True,
    )
    trigger: Mapped[RunTrigger] = mapped_column(
        SAEnum(RunTrigger, native_enum=False, length=16),
        default=RunTrigger.MANUAL,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Прогресс и итоги.
    pages_done: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    scenario: Mapped[Scenario] = relationship(back_populates="runs")
    scenario_version: Mapped[ScenarioVersion | None] = relationship(back_populates="runs")
    items: Mapped[list[RunItem]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )


class RunItem(TimestampMixin, Base):
    """Одна собранная запись (строка результата)."""

    __tablename__ = "run_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Порядковый номер записи в выдаче.
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # Ключ дедупликации для инкрементального сбора (Этап 4/6).
    dedup_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    validation_errors: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)

    run: Mapped[Run] = relationship(back_populates="items")


class Artifact(TimestampMixin, Base):
    """Файл-артефакт: скриншот, HTML, JSON-ответ, выгрузка."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # Путь относительно data/artifacts.
    rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    run: Mapped[Run | None] = relationship(back_populates="artifacts")
