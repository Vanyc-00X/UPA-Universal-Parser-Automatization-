"""Схемы API движка извлечения (Этап 4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.editor.schema import ScenarioDefinition


class RunRequest(BaseModel):
    """Запрос на запуск сценария."""

    scenario_id: str = Field(..., description="Сценарий, который нужно выполнить")
    snapshot_id: str | None = Field(
        None, description="Снапшот страницы; если не указан, берётся последний снапшот сайта"
    )
    min_coverage: float = Field(
        0.95,
        ge=0.0,
        le=1.0,
        description="Минимальная полнота обязательных полей, при которой сбор считается успешным",
    )
    live: bool = Field(
        False,
        description="Догружать страницы живым браузером (нужно для многостраничного обхода)",
    )


class PreviewRequest(BaseModel):
    """Предпросмотр сценария без сохранения запуска."""

    scenario_id: str
    snapshot_id: str | None = None
    limit: int = Field(5, ge=1, le=100)


class PageResultOut(BaseModel):
    """Обработанная страница."""

    number: int
    url: str
    records: int
    is_valid: bool
    note: str | None = None
    problem: str | None = None
    skipped: bool = False


class FieldStatOut(BaseModel):
    """Заполненность одного поля."""

    title: str
    required: bool = False
    filled: int = 0
    total: int = 0
    coverage: float = 0.0
    problems: dict[str, int] = Field(default_factory=dict)


class RecordIssueOut(BaseModel):
    """Замечание к записи."""

    position: int
    key: str
    problem: str
    severity: str = "error"


class RunReportOut(BaseModel):
    """Отчёт о полноте и качестве собранных данных."""

    records: int = 0
    valid_records: int = 0
    invalid_records: int = 0
    required_coverage: float = 0.0
    completeness: float = 0.0
    suspicious: int = 0
    min_coverage: float = 0.95
    passed: bool = False
    issues_total: int = 0
    fields: dict[str, FieldStatOut] = Field(default_factory=dict)
    issues: list[RecordIssueOut] = Field(default_factory=list)
    problems_by_field: dict[str, list[str]] = Field(default_factory=dict)


class RunOut(BaseModel):
    """Запуск сценария."""

    id: str
    scenario_id: str
    scenario_version_id: str | None = None
    status: Literal["pending", "running", "succeeded", "failed", "cancelled"]
    trigger: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    pages_done: int = 0
    items_count: int = 0
    errors_count: int = 0
    error: str | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    # Отчёт строится по сохранённым записям и добавляется при выдаче.
    report: RunReportOut | None = None
    pages: list[PageResultOut] = Field(default_factory=list)
    scenario_name: str | None = None


class RunListResponse(BaseModel):
    items: list[RunOut]
    total: int


class RunItemOut(BaseModel):
    """Одна собранная запись."""

    id: str
    position: int
    data: dict[str, Any] = Field(default_factory=dict)
    source_url: str | None = None
    is_valid: bool = True
    validation_errors: list[str] = Field(default_factory=list)


class RunItemsResponse(BaseModel):
    """Записи запуска с постраничной выдачей."""

    run_id: str
    items: list[RunItemOut]
    total: int
    limit: int
    offset: int


class RunPreviewResponse(BaseModel):
    """Предпросмотр: первые записи и отчёт без сохранения запуска."""

    scenario_id: str
    snapshot_id: str
    mode: str
    records: list[dict[str, Any]] = Field(default_factory=list)
    extraction: dict[str, Any] = Field(default_factory=dict)
    report: RunReportOut
    report_text: str


class PriceParseOut(BaseModel):
    """Разбор цены — вспомогательная проверка для интерфейса."""

    raw: str
    value: float | None = None
    currency: str | None = None
    unit: str | None = None
    problem: str | None = None


class NormalizeCheckRequest(BaseModel):
    """Проверка нормализации значения."""

    value: str
    kind: str = Field("auto", description="Тип значения или auto для определения по содержимому")


class NormalizeCheckResponse(BaseModel):
    """Результат нормализации."""

    kind: str
    value: Any = None
    raw: str | None = None
    problem: str | None = None


class DefinitionPreviewRequest(BaseModel):
    """Проверка произвольного определения сценария на снапшоте."""

    definition: ScenarioDefinition
    snapshot_id: str
    limit: int = Field(5, ge=1, le=100)
