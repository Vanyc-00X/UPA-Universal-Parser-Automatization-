"""Сервис воркфлоу: dry-run / live, сохранение отчёта, codegen."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.crawler import store
from app.editor import scenario as scenario_service
from app.editor.schema import ExtractionPlan, ScenarioDefinition
from app.storage.models import Run, RunStatus, RunTrigger, Scenario, ScenarioVersion
from app.workflow import codegen, dry_run, params
from app.workflow.schema import WorkflowDefinition, WorkflowReport

log = get_logger(__name__)


def _shell_definition(
    definition: WorkflowDefinition, description: str | None
) -> ScenarioDefinition:
    """Оболочка ScenarioDefinition — совместима с хранилищем версий."""
    return ScenarioDefinition(
        url=definition.url,
        title=definition.title,
        description=description or definition.description,
        fields=[],
        plan=ExtractionPlan(mode="single"),
        limits={
            "workflow": True,
            "max_rows": definition.max_rows,
            "max_actions": definition.max_actions,
        },
        created_from="editor",
    )


def _version_payload(
    shell: ScenarioDefinition, definition: WorkflowDefinition, description: str | None
) -> dict[str, Any]:
    return {
        **shell.model_dump(mode="json"),
        "kind": "form_fill",
        "workflow": definition.model_dump(mode="json"),
        "description": description or definition.description,
    }


async def save_workflow_scenario(
    session: AsyncSession,
    definition: WorkflowDefinition,
    *,
    site_id: str,
    name: str,
    description: str | None = None,
    scenario_id: str | None = None,
) -> tuple[Scenario, ScenarioVersion]:
    """Сохраняет воркфлоу как сценарий kind=form_fill."""
    shell = _shell_definition(definition, description)
    scenario, version = await scenario_service.save_scenario(
        session,
        shell,
        name=name,
        site_id=site_id,
        description=description or definition.description,
        change_note="воркфлоу ввода данных",
        scenario_id=scenario_id,
        created_by="workflow",
    )
    version.definition = _version_payload(shell, definition, description)
    scenario.kind = "form_fill"
    await session.flush()
    return scenario, version


def workflow_from_scenario_definition(payload: dict[str, Any]) -> WorkflowDefinition:
    """Достаёт WorkflowDefinition из version.definition."""
    raw = payload.get("workflow")
    if raw is None:
        raise ValidationError("В версии сценария нет блока workflow")
    try:
        return WorkflowDefinition.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(
            "Определение воркфлоу повреждено", details={"reason": str(exc)[:300]}
        ) from exc


async def get_workflow(
    session: AsyncSession, scenario_id: str
) -> tuple[Scenario, ScenarioVersion, WorkflowDefinition]:
    scenario = await scenario_service.get_scenario(session, scenario_id)
    version = await scenario_service.get_current_version(session, scenario)
    if version is None:
        raise ValidationError("У сценария нет версий")
    definition = workflow_from_scenario_definition(version.definition or {})
    return scenario, version, definition


async def run_workflow(
    session: AsyncSession,
    settings: Settings,
    *,
    definition: WorkflowDefinition,
    rows: list[dict[str, str]],
    mode: Literal["dry_run", "live"] = "dry_run",
    snapshot_id: str | None = None,
    scenario_id: str,
    scenario_version_id: str | None = None,
    confirm_dangerous: bool = False,
    persist: bool = True,
) -> tuple[Run | None, WorkflowReport]:
    """Прогоняет воркфлоу по строкам. При persist=True сохраняет запуск."""
    rows = params.limit_rows(rows, definition.max_rows)

    if definition.total_actions() > definition.max_actions:
        raise ValidationError(
            f"Слишком много шагов: {definition.total_actions()} > {definition.max_actions}"
        )

    if mode == "live" and definition.require_confirm_submit:
        dangerous = [step for step in definition.steps if step.looks_dangerous()]
        if dangerous and not confirm_dangerous:
            raise ValidationError(
                "Воркфлоу содержит опасные действия (отправка/оплата). "
                "Передайте confirm_dangerous=true для подтверждения.",
                details={"dangerous_steps": len(dangerous)},
            )

    html: str | None = None
    if mode == "dry_run":
        if not snapshot_id:
            raise ValidationError("Для dry-run нужен snapshot_id")
        html = store.load_text(settings, snapshot_id, store.TRIMMED_HTML)
        if html is None:
            html = store.load_text(settings, snapshot_id, store.PAGE_HTML)
        if html is None:
            raise NotFoundError(
                "DOM снапшота не найден", details={"snapshot_id": snapshot_id}
            )

    results = []
    if mode == "dry_run":
        assert html is not None
        for index, row in enumerate(rows):
            results.append(dry_run.run_row_dry(definition, row, html=html, index=index))
    else:
        from app.workflow.live import run_rows_live

        results = await run_rows_live(settings, definition, rows)

    succeeded = sum(1 for item in results if item.ok)
    failed = len(results) - succeeded
    report = WorkflowReport(
        mode=mode,
        total=len(results),
        succeeded=succeeded,
        failed=failed,
        rows=results,
    )

    if not persist:
        return None, report

    run = Run(
        scenario_id=scenario_id,
        scenario_version_id=scenario_version_id,
        status=RunStatus.SUCCEEDED if failed == 0 else RunStatus.FAILED,
        trigger=RunTrigger.MANUAL,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        pages_done=1,
        items_count=succeeded,
        errors_count=failed,
        error=None if failed == 0 else f"ошибок: {failed} из {len(results)}",
        params={"mode": mode, "snapshot_id": snapshot_id, "rows": len(rows)},
        stats={
            "workflow": True,
            "mode": mode,
            "report": report.model_dump(mode="json"),
            **report.summary(),
        },
    )
    session.add(run)
    await session.flush()

    log.info(
        "workflow.finished",
        run_id=run.id,
        mode=mode,
        total=report.total,
        succeeded=succeeded,
        failed=failed,
    )
    return run, report


def export_script(
    definition: WorkflowDefinition, rows: list[dict[str, str]] | None = None
) -> str:
    return codegen.render_playwright_script(definition, rows=rows)
