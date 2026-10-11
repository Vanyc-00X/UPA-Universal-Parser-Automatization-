"""Параметры воркфлоу: CSV/JSON/XLSX и подстановка {{column}}."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any

from app.core.errors import ValidationError

TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z_][\w.-]*)\s*\}\}")


def parse_rows_json(payload: list[dict[str, Any]] | dict[str, Any]) -> list[dict[str, str]]:
    """Разбирает JSON-массив строк или объект с ключом rows."""
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise ValidationError("Ожидался объект с массивом rows")
    else:
        rows = payload
    if not rows:
        raise ValidationError("Список строк параметров пуст")
    result: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValidationError(f"Строка {index}: ожидался объект")
        result.append({str(key): "" if value is None else str(value) for key, value in row.items()})
    return result


def parse_rows_csv(text: str, *, delimiter: str = ",") -> list[dict[str, str]]:
    """Разбирает CSV с заголовком в список словарей."""
    if not text.strip():
        raise ValidationError("CSV пуст")
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValidationError("В CSV нет заголовка")
    rows: list[dict[str, str]] = []
    for index, row in enumerate(reader):
        cleaned = {
            (key or "").strip(): (value or "").strip()
            for key, value in row.items()
            if key is not None
        }
        if not any(cleaned.values()):
            continue
        rows.append(cleaned)
        if index > 10_000:
            raise ValidationError("Слишком много строк в CSV")
    if not rows:
        raise ValidationError("В CSV нет данных")
    return rows


def substitute(template: str | None, row: dict[str, str]) -> str | None:
    """Подставляет ``{{column}}`` значениями строки. Неизвестные колонки → ошибка."""
    if template is None:
        return None

    missing: list[str] = []

    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in row:
            missing.append(key)
            return match.group(0)
        return row[key]

    result = TEMPLATE_RE.sub(replacer, template)
    if missing:
        raise ValidationError(
            f"В строке нет колонок для подстановки: {sorted(set(missing))}",
            details={"missing": sorted(set(missing))},
        )
    return result


def parse_rows_xlsx(data: bytes) -> list[dict[str, str]]:
    """Разбирает первую книгу XLSX (openpyxl) в список словарей."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover
        raise ValidationError("openpyxl не установлен") from exc

    if not data:
        raise ValidationError("XLSX пуст")
    workbook = load_workbook(filename=io.BytesIO(data), read_only=True, data_only=True)
    sheet = workbook.active
    if sheet is None:
        raise ValidationError("В XLSX нет листа")
    rows_iter = sheet.iter_rows(values_only=True)
    try:
        header = next(rows_iter)
    except StopIteration as exc:
        raise ValidationError("В XLSX нет заголовка") from exc
    columns = [str(cell).strip() if cell is not None else "" for cell in header]
    if not any(columns):
        raise ValidationError("В XLSX пустой заголовок")

    rows: list[dict[str, str]] = []
    for index, values in enumerate(rows_iter):
        cleaned: dict[str, str] = {}
        for col_index, column in enumerate(columns):
            if not column:
                continue
            raw = values[col_index] if col_index < len(values) else None
            cleaned[column] = "" if raw is None else str(raw).strip()
        if not any(cleaned.values()):
            continue
        rows.append(cleaned)
        if index > 10_000:
            raise ValidationError("Слишком много строк в XLSX")
    if not rows:
        raise ValidationError("В XLSX нет данных")
    return rows


def parse_rows_xlsx_path(path: str | Path) -> list[dict[str, str]]:
    return parse_rows_xlsx(Path(path).read_bytes())


def limit_rows(rows: list[dict[str, str]], max_rows: int) -> list[dict[str, str]]:
    if len(rows) > max_rows:
        raise ValidationError(
            f"Слишком много строк: {len(rows)} (лимит {max_rows})",
            details={"rows": len(rows), "max_rows": max_rows},
        )
    return rows
