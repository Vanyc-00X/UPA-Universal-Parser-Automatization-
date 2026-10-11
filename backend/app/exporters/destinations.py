"""Доставка результатов: webhook, Google Sheets, PostgreSQL."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import create_engine, text

from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.exporters.table import ExportTable

log = get_logger(__name__)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DestinationKind(str, Enum):
    WEBHOOK = "webhook"
    SHEETS = "sheets"
    POSTGRES = "postgres"


@dataclass
class DeliveryResult:
    kind: str
    ok: bool
    records: int
    detail: str
    response: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ok": self.ok,
            "records": self.records,
            "detail": self.detail,
            "response": self.response,
        }


async def deliver(
    table: ExportTable,
    *,
    kind: DestinationKind | str,
    target: str,
    options: dict[str, Any] | None = None,
) -> DeliveryResult:
    """Отправляет таблицу в выбранный приёмник."""
    options = options or {}
    kind_value = DestinationKind(kind) if not isinstance(kind, DestinationKind) else kind
    if kind_value is DestinationKind.WEBHOOK:
        return await _deliver_webhook(table, target, options)
    if kind_value is DestinationKind.SHEETS:
        return await _deliver_sheets(table, target, options)
    if kind_value is DestinationKind.POSTGRES:
        return _deliver_postgres(table, target, options)
    raise ValidationError("Неизвестный приёмник", details={"kind": str(kind)})


async def _deliver_webhook(
    table: ExportTable, url: str, options: dict[str, Any]
) -> DeliveryResult:
    if not url.startswith(("http://", "https://")):
        raise ValidationError("Webhook URL должен начинаться с http:// или https://")
    payload = {
        "meta": table.meta,
        "columns": table.columns,
        "titles": table.titles,
        "records": [
            {key: row.get(key) for key in table.columns} for row in table.rows
        ],
        "count": table.count,
    }
    headers = {"Content-Type": "application/json"}
    extra = options.get("headers")
    if isinstance(extra, dict):
        headers.update({str(k): str(v) for k, v in extra.items()})
    timeout = float(options.get("timeout_sec", 30))
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload, headers=headers)
    ok = 200 <= response.status_code < 300
    body: dict[str, Any] | None
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = {"text": response.text[:500]}
    return DeliveryResult(
        kind=DestinationKind.WEBHOOK.value,
        ok=ok,
        records=table.count,
        detail=f"HTTP {response.status_code}",
        response=body if isinstance(body, dict) else {"body": body},
    )


async def _deliver_sheets(
    table: ExportTable, spreadsheet_id: str, options: dict[str, Any]
) -> DeliveryResult:
    """Дописывает строки в Google Sheet через Sheets API v4.

    Нужен OAuth/access token с правом spreadsheets.
    """
    token = options.get("access_token") or options.get("token")
    if not token:
        raise ValidationError(
            "Для Google Sheets укажите options.access_token (OAuth access token)"
        )
    sheet_range = options.get("range") or "Sheet1!A1"
    include_header = bool(options.get("include_header", True))
    values: list[list[Any]] = []
    if include_header and table.count >= 0:
        values.append(table.header())
    values.extend(table.as_matrix())

    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/"
        f"{sheet_range}:append"
    )
    params = {
        "valueInputOption": options.get("value_input_option", "USER_ENTERED"),
        "insertDataOption": options.get("insert_data_option", "INSERT_ROWS"),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    timeout = float(options.get("timeout_sec", 30))
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            url,
            params=params,
            headers=headers,
            json={"values": values},
        )
    ok = 200 <= response.status_code < 300
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = {"text": response.text[:500]}
    return DeliveryResult(
        kind=DestinationKind.SHEETS.value,
        ok=ok,
        records=table.count,
        detail=f"HTTP {response.status_code}",
        response=body if isinstance(body, dict) else {"body": body},
    )


def _deliver_postgres(
    table: ExportTable, dsn: str, options: dict[str, Any]
) -> DeliveryResult:
    """Вставляет строки в таблицу PostgreSQL (или совместимый DSN SQLAlchemy)."""
    parsed = urlparse(dsn)
    if parsed.scheme not in {
        "postgresql",
        "postgres",
        "postgresql+psycopg",
        "postgresql+psycopg2",
        "sqlite",
        "sqlite+pysqlite",
    }:
        raise ValidationError(
            "DSN должен быть postgresql://… (или sqlite:// для проверки)",
            details={"scheme": parsed.scheme},
        )

    table_name = str(options.get("table") or "upa_export")
    if not _IDENT.match(table_name):
        raise ValidationError("Некорректное имя таблицы", details={"table": table_name})

    # Нормализуем DSN под SQLAlchemy + psycopg3, если драйвер не указан.
    engine_url = dsn
    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        engine_url = dsn.replace("postgres://", "postgresql+psycopg://", 1).replace(
            "postgresql://", "postgresql+psycopg://", 1
        )

    columns = list(table.columns)
    if not columns:
        raise ValidationError("Нет колонок для записи в PostgreSQL")

    for column in columns:
        if not _IDENT.match(column):
            raise ValidationError(
                f"Имя колонки недопустимо для SQL: {column}",
                details={"column": column},
            )

    create_sql = (
        f'CREATE TABLE IF NOT EXISTS "{table_name}" ('
        + ", ".join(f'"{col}" TEXT' for col in columns)
        + ', "_run_id" TEXT, "_exported_at" TEXT)'
    )
    placeholders = ", ".join(f":{col}" for col in columns)
    col_list = ", ".join(f'"{col}"' for col in columns)
    insert_sql = (
        f'INSERT INTO "{table_name}" ({col_list}, "_run_id", "_exported_at") '
        f"VALUES ({placeholders}, :_run_id, :_exported_at)"
    )

    from datetime import datetime, timezone

    run_id = str(table.meta.get("run_id") or "")
    exported_at = datetime.now(timezone.utc).isoformat()

    try:
        engine = create_engine(engine_url)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(
            "Не удалось открыть соединение. Для PostgreSQL установите psycopg: "
            "pip install 'psycopg[binary]'",
            details={"error": str(exc)},
        ) from exc

    inserted = 0
    try:
        with engine.begin() as conn:
            conn.execute(text(create_sql))
            for row in table.rows:
                params = {col: _sql_cell(row.get(col)) for col in columns}
                params["_run_id"] = run_id
                params["_exported_at"] = exported_at
                conn.execute(text(insert_sql), params)
                inserted += 1
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(
            "Ошибка записи в базу",
            details={"error": str(exc)},
        ) from exc
    finally:
        engine.dispose()

    return DeliveryResult(
        kind=DestinationKind.POSTGRES.value,
        ok=True,
        records=inserted,
        detail=f"вставлено {inserted} строк в {table_name}",
        response={"table": table_name, "inserted": inserted},
    )


def _sql_cell(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
