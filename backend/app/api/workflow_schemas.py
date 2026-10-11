"""Схемы API воркфлоу ввода данных (Этап 7)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.workflow.schema import ActionStep, RowResult, WorkflowDefinition, WorkflowReport


class WorkflowSaveRequest(BaseModel):
    """Сохранение воркфлоу как сценария form_fill."""

    site_id: str
    name: str = Field(..., min_length=1, max_length=256)
    description: str | None = None
    scenario_id: str | None = None
    workflow: WorkflowDefinition


class WorkflowSaveResponse(BaseModel):
    scenario_id: str
    version: int
    kind: str = "form_fill"
    summary: dict[str, Any] = Field(default_factory=dict)


class WorkflowOut(BaseModel):
    scenario_id: str
    site_id: str
    name: str
    version: int
    kind: str
    workflow: WorkflowDefinition
    summary: dict[str, Any] = Field(default_factory=dict)


class WorkflowRowsPayload(BaseModel):
    """Строки параметров: JSON-массив или вложенный rows."""

    rows: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowDryRunRequest(BaseModel):
    """Сухой прогон на DOM снапшота."""

    snapshot_id: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    csv_text: str | None = Field(None, description="Альтернатива rows: CSV с заголовком")
    persist: bool = True


class WorkflowLiveRunRequest(BaseModel):
    """Живой прогон через Playwright."""

    rows: list[dict[str, Any]] = Field(default_factory=list)
    csv_text: str | None = None
    confirm_dangerous: bool = False
    persist: bool = True


class WorkflowPreviewRequest(BaseModel):
    """Dry-run черновика без сохранения сценария."""

    snapshot_id: str
    workflow: WorkflowDefinition
    rows: list[dict[str, Any]] = Field(default_factory=list)
    csv_text: str | None = None


class WorkflowRunResponse(BaseModel):
    run_id: str | None = None
    mode: Literal["dry_run", "live"]
    report: WorkflowReport
    summary: dict[str, Any] = Field(default_factory=dict)


class WorkflowExportRequest(BaseModel):
    rows: list[dict[str, Any]] | None = None
    csv_text: str | None = None


class WorkflowExportResponse(BaseModel):
    filename: str
    language: str = "python"
    script: str


class WorkflowExportDraftRequest(BaseModel):
    workflow: WorkflowDefinition
    rows: list[dict[str, Any]] | None = None
    csv_text: str | None = None


class ParseCsvRequest(BaseModel):
    csv_text: str
    delimiter: str = ","


class ParseCsvResponse(BaseModel):
    rows: list[dict[str, str]]
    columns: list[str]
    count: int


class WorkflowStepPreview(BaseModel):
    index: int
    type: str
    playwright: str
    dangerous: bool = False
    note: str | None = None


# Реэкспорт для удобства OpenAPI.
__all__ = [
    "ActionStep",
    "ParseCsvRequest",
    "ParseCsvResponse",
    "RowResult",
    "WorkflowDefinition",
    "WorkflowDryRunRequest",
    "WorkflowExportDraftRequest",
    "WorkflowExportRequest",
    "WorkflowExportResponse",
    "WorkflowLiveRunRequest",
    "WorkflowOut",
    "WorkflowPreviewRequest",
    "WorkflowReport",
    "WorkflowRunResponse",
    "WorkflowRowsPayload",
    "WorkflowSaveRequest",
    "WorkflowSaveResponse",
    "WorkflowStepPreview",
]
