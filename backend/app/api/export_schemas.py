"""Схемы API экспорта (Этап 5)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ExportMetaOut(BaseModel):
    """Сведения о готовом файле экспорта."""

    run_id: str
    format: Literal["csv", "xlsx", "json", "jsonl", "md"]
    filename: str
    records: int
    artifact_id: str | None = None
    download_url: str


class SpecOut(BaseModel):
    """Markdown-ТЗ."""

    filename: str
    markdown: str
    scenario_id: str | None = None
    run_id: str | None = None


class RunDiffSummaryOut(BaseModel):
    current_run_id: str
    previous_run_id: str
    added: int
    removed: int
    changed: int
    unchanged: int


class RunDiffOut(BaseModel):
    current_run_id: str
    previous_run_id: str
    added: int
    removed: int
    changed: int
    unchanged: int
    added_items: list[dict[str, Any]] = Field(default_factory=list)
    removed_items: list[dict[str, Any]] = Field(default_factory=list)
    changed_items: list[dict[str, Any]] = Field(default_factory=list)


class ArtifactOut(BaseModel):
    id: str
    run_id: str | None
    kind: str
    filename: str
    size_bytes: int | None
    mime: str | None
    download_url: str
    created_at: str
