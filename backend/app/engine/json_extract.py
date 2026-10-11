"""Извлечение записей из JSON/XHR ответов снапшота (режим plan.mode=api)."""

from __future__ import annotations

import json
import re
from typing import Any

from app.crawler import store
from app.core.config import Settings
from app.editor.schema import FieldSpec, ScenarioDefinition
from app.engine.extractor import ExtractedRecord, ExtractionResult

ARRAY_MARK = re.compile(r"\[\*\]|\[\]")


def parse_json_lenient(raw: str | None) -> Any | None:
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def walk_path(data: Any, path: str) -> Any:
    """Простой путь: ``data.items`` / ``data.items[*]`` / ``0.name``."""
    if not path or path in (".", "$"):
        return data
    cleaned = path.lstrip("$.").strip()
    if not cleaned:
        return data
    current = data
    for part in cleaned.split("."):
        if current is None:
            return None
        token = part.strip()
        if not token:
            continue
        is_array = bool(ARRAY_MARK.search(token))
        key = ARRAY_MARK.sub("", token)
        if key == "":
            if not isinstance(current, list):
                return None
            continue
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list) and key.isdigit():
            index = int(key)
            current = current[index] if 0 <= index < len(current) else None
        else:
            return None
        if is_array:
            if not isinstance(current, list):
                return None
    return current


def pick_network_payload(
    settings: Settings,
    snapshot_id: str,
    *,
    api_url: str | None = None,
) -> tuple[Any | None, str | None]:
    """Выбирает JSON-тело из network.json снапшота."""
    payload = store.load_json(settings, snapshot_id, store.NETWORK_JSON) or {}
    requests = payload.get("requests") or []
    candidates: list[dict[str, Any]] = []
    for entry in requests:
        if not isinstance(entry, dict):
            continue
        mime = (entry.get("mime") or "").lower()
        body = entry.get("body")
        if body is None:
            continue
        if "json" not in mime and not str(body).lstrip().startswith(("{", "[")):
            continue
        candidates.append(entry)

    if not candidates:
        return None, None

    if api_url:
        needle = api_url.lower()
        for entry in candidates:
            if needle in (entry.get("url") or "").lower():
                parsed = parse_json_lenient(entry.get("body"))
                if parsed is not None:
                    return parsed, entry.get("url")

    # Берём самый «богатый» JSON (больше ключей / элементов).
    best: tuple[Any, str | None, int] | None = None
    for entry in candidates:
        parsed = parse_json_lenient(entry.get("body"))
        if parsed is None:
            continue
        score = _richness(parsed)
        if best is None or score > best[2]:
            best = (parsed, entry.get("url"), score)
    if best is None:
        return None, None
    return best[0], best[1]


def _richness(value: Any) -> int:
    if isinstance(value, list):
        return len(value) * 10
    if isinstance(value, dict):
        return len(value) + sum(_richness(v) for v in value.values() if isinstance(v, (list, dict)))
    return 1


def extract_from_json(
    payload: Any,
    definition: ScenarioDefinition,
    *,
    source_url: str | None = None,
    limit: int | None = None,
) -> ExtractionResult:
    """Разбирает JSON по ``plan.records_path`` и полям (json-path в selector)."""
    result = ExtractionResult(mode="api")
    if not definition.fields:
        result.errors.append("в сценарии нет полей")
        return result

    records_path = definition.plan.records_path or ""
    items = walk_path(payload, records_path) if records_path else payload
    if items is None:
        result.errors.append(f"путь к записям не найден: {records_path or '(корень)'}")
        return result

    if isinstance(items, dict):
        # Один объект — одна запись.
        rows = [items]
    elif isinstance(items, list):
        rows = items
    else:
        result.errors.append("источник JSON не является списком или объектом")
        return result

    if not rows:
        result.errors.append("в JSON нет записей")
        return result

    result.item_matches = len(rows)
    result.container_matches = 1
    result.container_selector = records_path or "$"

    for position, row in enumerate(rows):
        if limit is not None and position >= limit:
            result.warnings.append(f"обработка ограничена {limit} записями")
            break
        if not isinstance(row, dict):
            # Примитив в массиве — кладём как value.
            row = {"value": row}
        record = _record_from_row(row, definition.fields, source_url=source_url)
        record.position = position
        result.records.append(record)

    if result.records and all(record.filled == 0 for record in result.records):
        result.errors.append(
            "в JSON-записях не заполнилось ни одно поле: проверьте пути в селекторах"
        )
    return result


def _record_from_row(
    row: dict[str, Any], fields: list[FieldSpec], *, source_url: str | None
) -> ExtractedRecord:
    record = ExtractedRecord(source_url=source_url)
    for field in fields:
        path = field.selector or field.key
        raw_value = walk_path(row, path)
        if raw_value is None and field.fallback_selectors:
            for alt in field.fallback_selectors:
                raw_value = walk_path(row, alt)
                if raw_value is not None:
                    path = alt
                    record.used_fallback[field.key] = True
                    break
        text = None if raw_value is None else str(raw_value)
        value = raw_value
        if isinstance(raw_value, (dict, list)):
            text = json.dumps(raw_value, ensure_ascii=False)
            value = text
        if isinstance(value, str):
            value = value.strip()
        record.values[field.key] = value if value not in ("", None) else None
        record.raws[field.key] = text
        record.selectors_used[field.key] = path
        if record.values[field.key] in (None, ""):
            record.problems[field.key] = "empty" if field.required else "missing"
    return record
