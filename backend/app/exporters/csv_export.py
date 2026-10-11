"""Экспорт таблицы в CSV."""

from __future__ import annotations

import csv
import io
from typing import Literal

from app.exporters.table import ExportTable

Delimiter = Literal[",", ";", "\t"]


def render_csv(
    table: ExportTable,
    *,
    delimiter: Delimiter = ",",
    encoding: str = "utf-8-sig",
) -> bytes:
    """Собирает CSV. По умолчанию UTF-8 с BOM — Excel на Windows открывает кириллицу."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(table.header())
    for row in table.as_matrix():
        writer.writerow(row)
    return buffer.getvalue().encode(encoding)
