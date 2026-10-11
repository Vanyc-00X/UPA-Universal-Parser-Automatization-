"""Эндпоинты воркфлоу ввода данных (Этап 7)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.workflow_schemas import (
    ParseCsvRequest,
    ParseCsvResponse,
    WorkflowDryRunRequest,
    WorkflowExportDraftRequest,
    WorkflowExportRequest,
    WorkflowExportResponse,
    WorkflowLiveRunRequest,
    WorkflowOut,
    WorkflowPreviewRequest,
    WorkflowRunResponse,
    WorkflowSaveRequest,
    WorkflowSaveResponse,
    WorkflowStepPreview,
)
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import ValidationError
from app.workflow import codegen, params
from app.workflow import service as workflow_service
from app.workflow.schema import WorkflowDefinition

router = APIRouter(tags=["workflow"])


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _resolve_rows(
    rows: list[dict[str, Any]] | None, csv_text: str | None
) -> list[dict[str, str]]:
    if csv_text:
        return params.parse_rows_csv(csv_text)
    if rows:
        return params.parse_rows_json(rows)
    raise ValidationError("Передайте rows или csv_text")


@router.post(
    "/workflows",
    response_model=WorkflowSaveResponse,
    summary="Сохранить воркфлоу как сценарий",
)
async def save_workflow(
    payload: WorkflowSaveRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowSaveResponse:
    scenario, version = await workflow_service.save_workflow_scenario(
        db,
        payload.workflow,
        site_id=payload.site_id,
        name=payload.name,
        description=payload.description,
        scenario_id=payload.scenario_id,
    )
    return WorkflowSaveResponse(
        scenario_id=scenario.id,
        version=version.version,
        kind=scenario.kind,
        summary=payload.workflow.summary(),
    )


@router.get(
    "/workflows/{scenario_id}",
    response_model=WorkflowOut,
    summary="Получить воркфлоу сценария",
)
async def get_workflow(
    scenario_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkflowOut:
    scenario, version, definition = await workflow_service.get_workflow(db, scenario_id)
    return WorkflowOut(
        scenario_id=scenario.id,
        site_id=scenario.site_id,
        name=scenario.name,
        version=version.version,
        kind=scenario.kind,
        workflow=definition,
        summary=definition.summary(),
    )


@router.post(
    "/workflows/{scenario_id}/dry-run",
    response_model=WorkflowRunResponse,
    summary="Сухой прогон воркфлоу по DOM снапшота",
    description="Опасные click пропускаются. Реальная форма не отправляется.",
)
async def dry_run_workflow(
    scenario_id: str,
    payload: WorkflowDryRunRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    settings = _settings(request)
    scenario, version, definition = await workflow_service.get_workflow(db, scenario_id)
    rows = _resolve_rows(payload.rows, payload.csv_text)
    run, report = await workflow_service.run_workflow(
        db,
        settings,
        definition=definition,
        rows=rows,
        mode="dry_run",
        snapshot_id=payload.snapshot_id,
        scenario_id=scenario.id,
        scenario_version_id=version.id,
        persist=payload.persist,
    )
    return WorkflowRunResponse(
        run_id=run.id if run else None,
        mode="dry_run",
        report=report,
        summary=report.summary(),
    )


@router.post(
    "/workflows/{scenario_id}/run",
    response_model=WorkflowRunResponse,
    summary="Живой прогон воркфлоу через Playwright",
)
async def live_run_workflow(
    scenario_id: str,
    payload: WorkflowLiveRunRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    settings = _settings(request)
    scenario, version, definition = await workflow_service.get_workflow(db, scenario_id)
    rows = _resolve_rows(payload.rows, payload.csv_text)
    run, report = await workflow_service.run_workflow(
        db,
        settings,
        definition=definition,
        rows=rows,
        mode="live",
        scenario_id=scenario.id,
        scenario_version_id=version.id,
        confirm_dangerous=payload.confirm_dangerous,
        persist=payload.persist,
    )
    return WorkflowRunResponse(
        run_id=run.id if run else None,
        mode="live",
        report=report,
        summary=report.summary(),
    )


@router.post(
    "/workflows/preview-dry-run",
    response_model=WorkflowRunResponse,
    summary="Dry-run черновика без сохранения сценария",
)
async def preview_dry_run(
    payload: WorkflowPreviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    settings = _settings(request)
    rows = _resolve_rows(payload.rows, payload.csv_text)
    _, report = await workflow_service.run_workflow(
        db,
        settings,
        definition=payload.workflow,
        rows=rows,
        mode="dry_run",
        snapshot_id=payload.snapshot_id,
        scenario_id="preview",  # не используется при persist=False
        persist=False,
    )
    return WorkflowRunResponse(
        run_id=None,
        mode="dry_run",
        report=report,
        summary=report.summary(),
    )


@router.post(
    "/workflows/{scenario_id}/export-script",
    response_model=WorkflowExportResponse,
    summary="Экспорт воркфлоу в Python-скрипт Playwright",
)
async def export_script(
    scenario_id: str,
    payload: WorkflowExportRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowExportResponse:
    _, _, definition = await workflow_service.get_workflow(db, scenario_id)
    rows = None
    if payload.csv_text or payload.rows:
        rows = _resolve_rows(payload.rows, payload.csv_text)
    script = workflow_service.export_script(definition, rows=rows)
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in definition.title)
    return WorkflowExportResponse(
        filename=f"upa_workflow_{safe_name or 'script'}.py",
        script=script,
    )


@router.post(
    "/workflows/export-script",
    response_model=WorkflowExportResponse,
    summary="Экспорт черновика воркфлоу в Python-скрипт",
)
async def export_draft_script(payload: WorkflowExportDraftRequest) -> WorkflowExportResponse:
    rows = None
    if payload.csv_text or payload.rows:
        rows = _resolve_rows(payload.rows, payload.csv_text)
    script = workflow_service.export_script(payload.workflow, rows=rows)
    safe_name = "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in payload.workflow.title
    )
    return WorkflowExportResponse(
        filename=f"upa_workflow_{safe_name or 'script'}.py",
        script=script,
    )


@router.get(
    "/workflows/{scenario_id}/export-script.txt",
    response_class=PlainTextResponse,
    summary="Скачать скрипт как text/plain",
)
async def download_script(
    scenario_id: str,
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    _, _, definition = await workflow_service.get_workflow(db, scenario_id)
    script = workflow_service.export_script(definition)
    return PlainTextResponse(
        script,
        media_type="text/x-python; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="upa_workflow_{scenario_id[:8]}.py"'
        },
    )


@router.post(
    "/workflows/parse-csv",
    response_model=ParseCsvResponse,
    summary="Разобрать CSV параметров в строки",
)
async def parse_csv(payload: ParseCsvRequest) -> ParseCsvResponse:
    rows = params.parse_rows_csv(payload.csv_text, delimiter=payload.delimiter)
    columns = list(rows[0].keys()) if rows else []
    return ParseCsvResponse(rows=rows, columns=columns, count=len(rows))


@router.post(
    "/workflows/preview-steps",
    response_model=list[WorkflowStepPreview],
    summary="Превью шагов как строк Playwright",
)
async def preview_steps(workflow: WorkflowDefinition) -> list[WorkflowStepPreview]:
    return [
        WorkflowStepPreview(
            index=index,
            type=step.type.value,
            playwright=codegen.step_to_playwright_line(step),
            dangerous=step.looks_dangerous(),
            note=step.note,
        )
        for index, step in enumerate(workflow.steps)
    ]
