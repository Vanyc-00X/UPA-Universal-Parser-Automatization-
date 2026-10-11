"""Экспорт таблицы в JSON и JSONL."""

from __future__ import annotations

import json

from app.exporters.table import ExportTable


def render_json(table: ExportTable, *, pretty: bool = True) -> bytes:
    """Массив объектов + метаданные запуска."""
    payload = {
        "meta": table.meta,
        "columns": [{"key": key, "title": table.titles.get(key, key)} for key in table.columns],
        "records": [{key: row.get(key) for key in table.columns} for row in table.rows],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None)
    return (text + "\n").encode("utf-8")


def render_jsonl(table: ExportTable) -> bytes:
    """По одной JSON-записи на строку — удобно для потоковой обработки."""
    lines = [
        json.dumps({key: row.get(key) for key in table.columns}, ensure_ascii=False)
        for row in table.rows
    ]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
