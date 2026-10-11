"""Эндпоинты экспорта и сравнения запусков (Этап 5)."""

from __future__ import annotations

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.export_schemas import ArtifactOut, ExportMetaOut, RunDiffOut, SpecOut
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import NotFoundError, ValidationError
from app.exporters import service as export_service
from app.exporters.service import ExportFormat
from app.storage.models import Artifact

router = APIRouter(tags=["export"])


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _parse_format(value: str) -> ExportFormat:
    try:
        return ExportFormat(value.lower())
    except ValueError as exc:
        raise ValidationError(
            "Формат экспорта: csv, xlsx, json, jsonl или md",
            details={"format": value},
        ) from exc


def _attachment(filename: str, mime: str, content: bytes) -> Response:
    ascii_name = filename.encode("ascii", "ignore").decode() or "export.bin"
    encoded = quote(filename)
    return Response(
        content=content,
        media_type=mime,
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"
            )
        },
    )


@router.get(
    "/runs/{run_id}/export",
    summary="Скачать результаты запуска",
    description="Форматы: csv, xlsx, json, jsonl, md. Файл сохраняется в артефакты запуска.",
)
async def export_run_file(
    run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Literal["csv", "xlsx", "json", "jsonl", "md"] = Query("csv"),
    delimiter: Literal[",", ";", "tab"] = Query(","),
    q: str | None = Query(None, description="Поиск по значениям ячеек"),
    only_invalid: bool = Query(False),
    persist: bool = Query(True),
) -> Response:
    settings = _settings(request)
    sep = "\t" if delimiter == "tab" else delimiter
    result = await export_service.export_run(
        db,
        settings,
        run_id,
        fmt=_parse_format(format),
        delimiter=sep,
        query=q,
        only_invalid=only_invalid,
        persist=persist,
    )
    return _attachment(result.filename, result.mime, result.content)


@router.get(
    "/runs/{run_id}/export/meta",
    response_model=ExportMetaOut,
    summary="Собрать экспорт и вернуть ссылку на скачивание",
)
async def export_run_meta(
    run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    format: Literal["csv", "xlsx", "json", "jsonl", "md"] = Query("csv"),
    delimiter: Literal[",", ";", "tab"] = Query(","),
    q: str | None = Query(None),
    only_invalid: bool = Query(False),
) -> ExportMetaOut:
    settings = _settings(request)
    sep = "\t" if delimiter == "tab" else delimiter
    result = await export_service.export_run(
        db,
        settings,
        run_id,
        fmt=_parse_format(format),
        delimiter=sep,
        query=q,
        only_invalid=only_invalid,
        persist=True,
    )
    return ExportMetaOut(
        run_id=run_id,
        format=result.format.value,  # type: ignore[arg-type]
        filename=result.filename,
        records=result.records,
        artifact_id=result.artifact_id,
        download_url=f"/api/v1/runs/{run_id}/artifacts/{result.artifact_id}",
    )


@router.get(
    "/runs/{run_id}/spec",
    response_model=SpecOut,
    summary="Markdown-ТЗ по запуску",
)
async def run_spec(run_id: str, db: AsyncSession = Depends(get_db)) -> SpecOut:
    text, filename = await export_service.build_spec_markdown(db, run_id=run_id)
    return SpecOut(filename=filename, markdown=text, run_id=run_id)


@router.get(
    "/scenarios/{scenario_id}/spec",
    response_model=SpecOut,
    summary="Markdown-ТЗ по сценарию",
)
async def scenario_spec(scenario_id: str, db: AsyncSession = Depends(get_db)) -> SpecOut:
    text, filename = await export_service.build_spec_markdown(db, scenario_id=scenario_id)
    return SpecOut(filename=filename, markdown=text, scenario_id=scenario_id)


@router.get(
    "/runs/{run_id}/spec.md",
    summary="Скачать Markdown-ТЗ файлом",
)
async def download_run_spec(run_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    text, filename = await export_service.build_spec_markdown(db, run_id=run_id)
    return _attachment(filename, "text/markdown; charset=utf-8", text.encode("utf-8"))


@router.get(
    "/runs/{run_id}/diff",
    response_model=RunDiffOut,
    summary="Сравнить запуск с предыдущим",
)
async def run_diff(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    against: str | None = Query(None, description="ID другого запуска"),
) -> RunDiffOut:
    diff = await export_service.diff_runs(db, run_id, against_run_id=against)
    return RunDiffOut.model_validate(diff.as_dict())


@router.get(
    "/runs/{run_id}/artifacts",
    response_model=list[ArtifactOut],
    summary="Артефакты запуска (экспорты)",
)
async def list_run_artifacts(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[ArtifactOut]:
    from app.engine import service as engine

    await engine.get_run(db, run_id)
    result = await db.execute(
        select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.created_at.desc())
    )
    items = list(result.scalars().all())
    return [
        ArtifactOut(
            id=item.id,
            run_id=item.run_id,
            kind=item.kind,
            filename=(item.meta or {}).get("filename") or item.rel_path.split("/")[-1],
            size_bytes=item.size_bytes,
            mime=item.mime,
            download_url=f"/api/v1/runs/{run_id}/artifacts/{item.id}",
            created_at=item.created_at.isoformat(),
        )
        for item in items
    ]


@router.get(
    "/runs/{run_id}/artifacts/{artifact_id}",
    summary="Скачать артефакт запуска",
)
async def download_run_artifact(
    run_id: str,
    artifact_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    settings = _settings(request)
    artifact = await db.get(Artifact, artifact_id)
    if artifact is None or artifact.run_id != run_id:
        raise NotFoundError(
            "Артефакт не найден",
            details={"run_id": run_id, "artifact_id": artifact_id},
        )
    path = settings.artifacts_dir / artifact.rel_path
    if not path.is_file():
        raise NotFoundError(
            "Файл артефакта отсутствует на диске",
            details={"rel_path": artifact.rel_path},
        )
    filename = (artifact.meta or {}).get("filename") or path.name
    return _attachment(filename, artifact.mime or "application/octet-stream", path.read_bytes())
