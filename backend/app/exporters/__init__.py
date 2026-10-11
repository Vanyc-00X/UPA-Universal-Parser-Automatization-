"""Экспорт результатов запусков и генерация Markdown-ТЗ (Этап 5)."""

from app.exporters.diff import RunDiff, compare_runs
from app.exporters.service import (
    ExportFormat,
    ExportResult,
    build_spec_markdown,
    export_run,
    previous_run_id,
)
from app.exporters.table import ExportTable, table_from_items

__all__ = [
    "ExportFormat",
    "ExportResult",
    "ExportTable",
    "RunDiff",
    "build_spec_markdown",
    "compare_runs",
    "export_run",
    "previous_run_id",
    "table_from_items",
]
