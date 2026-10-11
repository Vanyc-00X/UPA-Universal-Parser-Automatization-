"""Сервис экспорта: сбор таблицы, запись артефакта, сравнение запусков."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.editor import scenario as scenario_service
from app.editor.schema import ScenarioDefinition
from app.engine import service as engine
from app.exporters import csv_export, json_export, markdown, xlsx_export
from app.exporters.diff import RunDiff, compare_runs
from app.exporters.table import ExportTable, table_from_items
from app.storage.models import Artifact, Run, Scenario, ScenarioVersion

log = get_logger(__name__)


class ExportFormat(str, Enum):
    CSV = "csv"
    XLSX = "xlsx"
    JSON = "json"
    JSONL = "jsonl"
    MARKDOWN = "md"


MIME: dict[ExportFormat, str] = {
    ExportFormat.CSV: "text/csv; charset=utf-8",
    ExportFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ExportFormat.JSON: "application/json; charset=utf-8",
    ExportFormat.JSONL: "application/x-ndjson; charset=utf-8",
    ExportFormat.MARKDOWN: "text/markdown; charset=utf-8",
}

EXTENSION: dict[ExportFormat, str] = {
    ExportFormat.CSV: "csv",
    ExportFormat.XLSX: "xlsx",
    ExportFormat.JSON: "json",
    ExportFormat.JSONL: "jsonl",
    ExportFormat.MARKDOWN: "md",
}


@dataclass
class ExportResult:
    """Готовый файл экспорта."""

    content: bytes
    filename: str
    mime: str
    format: ExportFormat
    records: int
    artifact_id: str | None = None
    rel_path: str | None = None


async def load_run_table(
    session: AsyncSession,
    run_id: str,
    *,
    query: str | None = None,
    only_invalid: bool = False,
    keys: list[str] | None = None,
) -> tuple[Run, ExportTable, ScenarioDefinition | None]:
    """Загружает запуск и собирает таблицу для экспорта/UI."""
    run = await engine.get_run(session, run_id)
    items = await engine.list_run_items(session, run_id, limit=20_000)
    definition = await _definition_of_run(session, run)
    titles = {spec.key: spec.title for spec in definition.fields} if definition else {}

    scenario_name: str | None = None
    scenario = await session.get(Scenario, run.scenario_id)
    if scenario is not None:
        scenario_name = scenario.name

    table = table_from_items(
        items,
        field_titles=titles,
        run_id=run.id,
        scenario_name=scenario_name,
    )
    if query or only_invalid or keys:
        table = table.filtered(query=query, only_invalid=only_invalid, keys=keys)
    return run, table, definition


async def export_run(
    session: AsyncSession,
    settings: Settings,
    run_id: str,
    *,
    fmt: ExportFormat,
    delimiter: str = ",",
    query: str | None = None,
    only_invalid: bool = False,
    keys: list[str] | None = None,
    persist: bool = True,
) -> ExportResult:
    """Экспортирует запуск в выбранный формат и при необходимости сохраняет файл."""
    run, table, _definition = await load_run_table(
        session,
        run_id,
        query=query,
        only_invalid=only_invalid,
        keys=keys,
    )
    if not table.rows and fmt is not ExportFormat.MARKDOWN:
        # Пустой экспорт допустим: пользователь всё равно получает файл с заголовками.
        pass

    content = _render(table, fmt, delimiter=delimiter)
    stem = _safe_stem(table.meta.get("scenario_name") or run.scenario_id)
    filename = f"{stem}_{run.id[:8]}.{EXTENSION[fmt]}"

    artifact_id: str | None = None
    rel_path: str | None = None
    if persist:
        artifact = await _persist_artifact(
            session,
            settings,
            run_id=run.id,
            fmt=fmt,
            content=content,
            filename=filename,
        )
        artifact_id = artifact.id
        rel_path = artifact.rel_path

    log.info(
        "export.ready",
        run_id=run.id,
        format=fmt.value,
        records=table.count,
        bytes=len(content),
        artifact_id=artifact_id,
    )
    return ExportResult(
        content=content,
        filename=filename,
        mime=MIME[fmt],
        format=fmt,
        records=table.count,
        artifact_id=artifact_id,
        rel_path=rel_path,
    )


async def build_spec_markdown(
    session: AsyncSession,
    run_id: str | None = None,
    *,
    scenario_id: str | None = None,
) -> tuple[str, str]:
    """Собирает Markdown-ТЗ по запуску или сценарию. Возвращает (текст, имя файла)."""
    if run_id:
        run = await engine.get_run(session, run_id)
        definition = await _definition_of_run(session, run)
        if definition is None:
            raise ValidationError("У запуска нет определения сценария")
        scenario = await session.get(Scenario, run.scenario_id)
        name = scenario.name if scenario else definition.title
        items = await engine.list_run_items(session, run_id, limit=5)
        samples = [dict(item.data or {}) for item in items]
        text = markdown.build_spec_markdown(definition, scenario_name=name, sample_rows=samples)
        return text, f"tz_{_safe_stem(name)}.md"

    if not scenario_id:
        raise ValidationError("Укажите run_id или scenario_id")

    scenario = await scenario_service.get_scenario(session, scenario_id)
    version = await scenario_service.get_current_version(session, scenario)
    if version is None:
        raise ValidationError("У сценария нет версий")
    definition = scenario_service.definition_from_version(version)
    text = markdown.build_spec_markdown(definition, scenario_name=scenario.name)
    return text, f"tz_{_safe_stem(scenario.name)}.md"


async def previous_run_id(session: AsyncSession, run: Run) -> str | None:
    """Предыдущий запуск того же сценария (для diff)."""
    result = await session.execute(
        select(Run)
        .where(Run.scenario_id == run.scenario_id, Run.created_at < run.created_at)
        .order_by(Run.created_at.desc())
        .limit(1)
    )
    previous = result.scalar_one_or_none()
    return previous.id if previous else None


async def diff_runs(
    session: AsyncSession,
    run_id: str,
    *,
    against_run_id: str | None = None,
) -> RunDiff:
    """Сравнивает запуск с указанным или с предыдущим того же сценария."""
    run = await engine.get_run(session, run_id)
    other_id = against_run_id or await previous_run_id(session, run)
    if other_id is None:
        raise NotFoundError(
            "Нет предыдущего запуска для сравнения",
            details={"run_id": run_id},
        )
    other = await engine.get_run(session, other_id)
    current_items = await engine.list_run_items(session, run.id, limit=20_000)
    previous_items = await engine.list_run_items(session, other.id, limit=20_000)
    return compare_runs(
        current_run_id=run.id,
        previous_run_id=other.id,
        current_items=current_items,
        previous_items=previous_items,
    )


def _render(table: ExportTable, fmt: ExportFormat, *, delimiter: str) -> bytes:
    if fmt is ExportFormat.CSV:
        if delimiter not in {",", ";", "\t"}:
            raise ValidationError("Разделитель CSV: ',', ';' или табуляция")
        return csv_export.render_csv(table, delimiter=delimiter)  # type: ignore[arg-type]
    if fmt is ExportFormat.XLSX:
        return xlsx_export.render_xlsx(table)
    if fmt is ExportFormat.JSON:
        return json_export.render_json(table)
    if fmt is ExportFormat.JSONL:
        return json_export.render_jsonl(table)
    if fmt is ExportFormat.MARKDOWN:
        return markdown.render_markdown_table(table).encode("utf-8")
    raise ValidationError(f"Неизвестный формат: {fmt}")


async def _persist_artifact(
    session: AsyncSession,
    settings: Settings,
    *,
    run_id: str,
    fmt: ExportFormat,
    content: bytes,
    filename: str,
) -> Artifact:
    """Пишет файл в data/artifacts/runs/<run_id>/ и регистрирует Artifact."""
    settings.ensure_directories()
    rel_dir = Path("runs") / run_id
    abs_dir = settings.artifacts_dir / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    abs_path = abs_dir / filename
    abs_path.write_bytes(content)
    rel_path = (rel_dir / filename).as_posix()

    artifact = Artifact(
        run_id=run_id,
        kind=f"export_{fmt.value}",
        rel_path=rel_path,
        size_bytes=len(content),
        mime=MIME[fmt],
        meta={"filename": filename, "format": fmt.value},
    )
    session.add(artifact)
    await session.flush()
    return artifact


async def _definition_of_run(session: AsyncSession, run: Run) -> ScenarioDefinition | None:
    if not run.scenario_version_id:
        return None
    version = await session.get(ScenarioVersion, run.scenario_version_id)
    if version is None:
        return None
    try:
        return scenario_service.definition_from_version(version)
    except ValidationError:
        return None


def _safe_stem(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_" else "_" for char in value.strip())
    cleaned = cleaned.strip("_") or "export"
    return cleaned[:48]
