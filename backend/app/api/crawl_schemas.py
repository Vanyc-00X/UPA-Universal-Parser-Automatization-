"""Схемы API для сайтов и снапшотов (Этап 1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SiteOut(BaseModel):
    """Сайт в списке."""

    id: str
    url: str
    origin: str
    title: str | None = None
    label: str | None = None
    notes: str | None = None
    last_visited_at: datetime | None = None
    created_at: datetime
    snapshots_count: int = 0


class SiteListResponse(BaseModel):
    items: list[SiteOut]
    total: int


class SnapshotCaptureRequest(BaseModel):
    """Запрос на снятие снапшота."""

    url: str = Field(..., description="Адрес страницы. Схему можно опустить — добавим https")
    use_cache: bool = Field(
        False,
        description="Если DOM не изменился, переиспользовать артефакты прошлого снапшота",
    )
    allow_local: bool = Field(
        False,
        description="Разрешить адреса локальной сети (по умолчанию запрещены)",
    )


class NetworkRequestOut(BaseModel):
    """Сетевой запрос страницы."""

    url: str
    method: str
    resource_type: str
    status: int | None = None
    mime: str | None = None
    size_bytes: int | None = None
    body_truncated: bool = False
    is_data_source: bool = False
    has_body: bool = False
    error: str | None = None


class SnapshotSummaryOut(BaseModel):
    """Краткие сведения о снапшоте для списков."""

    id: str
    site_id: str
    url: str
    final_url: str | None = None
    status: Literal["pending", "running", "ready", "failed"]
    http_status: int | None = None
    title: str | None = None
    lang: str | None = None
    dom_hash: str | None = None
    html_bytes: int | None = None
    trimmed_bytes: int | None = None
    est_tokens: int | None = None
    duration_ms: int | None = None
    error: str | None = None
    created_at: datetime
    data_sources_count: int = 0
    network_count: int = 0
    compression_ratio: float | None = None
    cache_hit: bool = False


class SnapshotListResponse(BaseModel):
    items: list[SnapshotSummaryOut]
    total: int


class SnapshotDetailOut(SnapshotSummaryOut):
    """Полные сведения: статистика обрезки, метаданные, список артефактов."""

    trim: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
    artifact_urls: dict[str, str] = Field(default_factory=dict)
    console_errors: list[str] = Field(default_factory=list)
    failed_requests: list[str] = Field(default_factory=list)
    cookie_banner_closed: bool = False
    viewport: dict[str, int] = Field(default_factory=dict)


class SnapshotNetworkResponse(BaseModel):
    """Сетевые запросы снапшота с возможностью отфильтровать источники данных."""

    snapshot_id: str
    total: int
    items: list[NetworkRequestOut]


class SnapshotDomResponse(BaseModel):
    """HTML снапшота: полный или обрезанный под лимит модели."""

    snapshot_id: str
    variant: Literal["trimmed", "full"]
    bytes: int
    est_tokens: int
    html: str


class SnapshotDeleteResponse(BaseModel):
    snapshot_id: str
    deleted: bool
