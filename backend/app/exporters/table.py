"""Таблица результатов: единый формат для всех экспортёров."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExportTable:
    """Плоская таблица: заголовки + строки значений."""

    columns: list[str]
    titles: dict[str, str] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.rows)

    def header(self) -> list[str]:
        """Человекочитаемые заголовки в порядке колонок."""
        return [self.titles.get(key, key) for key in self.columns]

    def as_matrix(self) -> list[list[Any]]:
        """Матрица значений без заголовка — для XLSX/CSV."""
        matrix: list[list[Any]] = []
        for row in self.rows:
            matrix.append([_cell(row.get(key)) for key in self.columns])
        return matrix

    def filtered(
        self,
        *,
        query: str | None = None,
        only_invalid: bool = False,
        keys: list[str] | None = None,
    ) -> ExportTable:
        """Копия таблицы с отбором строк и колонок."""
        columns = [key for key in (keys or self.columns) if key in self.columns]
        if not columns:
            columns = list(self.columns)

        needle = (query or "").strip().lower()
        rows: list[dict[str, Any]] = []
        for row in self.rows:
            if only_invalid and row.get("_valid", True):
                continue
            if needle:
                haystack = " ".join(str(row.get(key, "") or "") for key in columns).lower()
                if needle not in haystack:
                    continue
            rows.append(
                {key: row.get(key) for key in columns} | {"_valid": row.get("_valid", True)}
            )

        return ExportTable(
            columns=columns,
            titles={key: self.titles.get(key, key) for key in columns},
            rows=rows,
            meta=dict(self.meta),
        )


def table_from_items(
    items: list[Any],
    *,
    field_titles: dict[str, str] | None = None,
    run_id: str | None = None,
    scenario_name: str | None = None,
) -> ExportTable:
    """Собирает таблицу из записей запуска.

    Служебные ключи ``_valid`` и ``_position`` не попадают в колонки экспорта,
    но используются для фильтрации и сортировки в интерфейсе.
    """
    titles = dict(field_titles or {})
    columns: list[str] = []
    seen: set[str] = set()

    # Порядок колонок: сначала известные поля сценария, затем остальные по появлению.
    for key in titles:
        if key not in seen:
            columns.append(key)
            seen.add(key)

    rows: list[dict[str, Any]] = []
    for item in items:
        data = dict(getattr(item, "data", None) or {})
        for key in data:
            if key not in seen and not key.startswith("_"):
                columns.append(key)
                seen.add(key)
                titles.setdefault(key, key)
        row = {key: data.get(key) for key in columns}
        row["_valid"] = bool(getattr(item, "is_valid", True))
        row["_position"] = int(getattr(item, "position", 0))
        rows.append(row)

    return ExportTable(
        columns=columns,
        titles=titles,
        rows=rows,
        meta={
            "run_id": run_id,
            "scenario_name": scenario_name,
            "records": len(rows),
        },
    )


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
