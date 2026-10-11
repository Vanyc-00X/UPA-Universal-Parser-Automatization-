"""Сервис self-healing: предложение и явное применение патча."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer import service as analyze_service
from app.core.config import Settings
from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.crawler import store
from app.editor import scenario as scenario_service
from app.editor.schema import ScenarioDefinition
from app.engine import service as engine
from app.engine.validate import DEFAULT_MIN_COVERAGE
from app.healing.propose import (
    HealProposal,
    apply_patches_to_definition,
    diagnose_broken_fields,
    parse_html,
    propose_field_patches,
)
from app.storage.models import Run

log = get_logger(__name__)


async def build_heal_proposal(
    session: AsyncSession,
    settings: Settings,
    run_id: str,
    *,
    min_coverage: float | None = None,
) -> HealProposal:
    """Строит предложение патча по результатам запуска.

    Патч никогда не применяется здесь — только формируется.
    """
    run = await engine.get_run(session, run_id)
    threshold = (
        min_coverage
        if min_coverage is not None
        else getattr(settings, "heal_min_coverage", DEFAULT_MIN_COVERAGE)
    )

    definition = await _definition_of_run(session, run)
    if definition is None:
        raise ValidationError("У запуска нет определения сценария")

    items = await engine.list_run_items(session, run_id, limit=20_000)
    field_stats = _stats_from_items(items, definition)
    coverage = _required_coverage(field_stats, definition)
    fallback_usage = _fallback_usage_from_stats(run.stats or {})
    broken = diagnose_broken_fields(
        definition,
        field_stats,
        min_coverage=threshold,
        fallback_usage=fallback_usage,
    )

    snapshot_id = (run.params or {}).get("snapshot_id") or definition.snapshot_id
    html = None
    elements: list[dict[str, Any]] = []
    if snapshot_id:
        html = store.load_text(settings, snapshot_id, store.TRIMMED_HTML)
        if html is None:
            html = store.load_text(settings, snapshot_id, store.PAGE_HTML)
        element_map = await analyze_service.get_element_map(session, snapshot_id)
        if element_map is not None:
            elements = list(element_map.elements or [])

    patches = []
    notes: list[str] = []
    if not broken:
        notes.append("критичных поломок селекторов не обнаружено")
    elif html is None:
        notes.append("нет DOM снапшота — нельзя подобрать замену селектора")
    else:
        document = parse_html(html)
        patches = propose_field_patches(document, definition, broken, element_map_elements=elements)
        if not patches:
            notes.append(
                "сломанные поля есть, но автоматическая замена не найдена — "
                "откройте редактор и поправьте селекторы вручную"
            )

    needed = bool(broken) or bool(patches)
    proposal = HealProposal(
        run_id=run.id,
        scenario_id=run.scenario_id,
        snapshot_id=snapshot_id,
        needed=needed,
        coverage=coverage,
        min_coverage=threshold,
        broken_fields=broken,
        patches=patches,
        notes=notes,
    )

    # Кэшируем предложение в stats запуска — UI читает без пересчёта.
    stats = dict(run.stats or {})
    stats["heal"] = proposal.as_dict()
    run.stats = stats
    await session.flush()
    log.info(
        "healing.proposal",
        run_id=run.id,
        needed=needed,
        broken=len(broken),
        patches=len(patches),
        coverage=coverage,
    )
    return proposal


async def proposal_from_run(session: AsyncSession, run_id: str) -> HealProposal | None:
    """Читает сохранённое предложение или None."""
    run = await engine.get_run(session, run_id)
    payload = (run.stats or {}).get("heal")
    if not payload:
        return None
    from app.healing.propose import FieldPatch

    return HealProposal(
        run_id=payload["run_id"],
        scenario_id=payload["scenario_id"],
        snapshot_id=payload.get("snapshot_id"),
        needed=bool(payload.get("needed")),
        coverage=float(payload.get("coverage") or 0),
        min_coverage=float(payload.get("min_coverage") or DEFAULT_MIN_COVERAGE),
        broken_fields=list(payload.get("broken_fields") or []),
        patches=[FieldPatch(**item) for item in payload.get("patches") or []],
        notes=list(payload.get("notes") or []),
    )


async def apply_heal_proposal(
    session: AsyncSession,
    settings: Settings,
    run_id: str,
    *,
    keys: list[str] | None = None,
    change_note: str | None = None,
) -> dict[str, Any]:
    """Применяет выбранные патчи как новую версию сценария.

    Явное действие пользователя: без этого вызова сценарий не меняется.
    """
    proposal = await proposal_from_run(session, run_id)
    if proposal is None:
        proposal = await build_heal_proposal(session, settings, run_id)
    if not proposal.patches:
        raise ValidationError(
            "Нет патчей для применения",
            details={"broken_fields": proposal.broken_fields, "notes": proposal.notes},
        )

    selected = [patch for patch in proposal.patches if keys is None or patch.key in keys]
    if not selected:
        raise ValidationError("Среди выбранных полей нет патчей")

    run = await engine.get_run(session, run_id)
    scenario = await scenario_service.get_scenario(session, run.scenario_id)
    definition = await _definition_of_run(session, run)
    if definition is None:
        raise ValidationError("У запуска нет определения сценария")

    patched = apply_patches_to_definition(definition, selected)
    _, version = await scenario_service.save_scenario(
        session,
        patched,
        name=scenario.name,
        site_id=scenario.site_id,
        description=scenario.description,
        change_note=change_note
        or f"Self-healing после запуска {run_id[:8]}: {[p.key for p in selected]}",
        scenario_id=scenario.id,
        created_by="healing",
    )

    stats = dict(run.stats or {})
    stats["heal_applied"] = {
        "version": version.version,
        "keys": [patch.key for patch in selected],
        "change_note": change_note,
    }
    run.stats = stats
    await session.flush()

    log.info(
        "healing.applied",
        run_id=run.id,
        scenario_id=scenario.id,
        version=version.version,
        keys=[patch.key for patch in selected],
    )
    return {
        "scenario_id": scenario.id,
        "version": version.version,
        "applied": [patch.as_dict() for patch in selected],
        "definition": patched.model_dump(mode="json"),
    }


async def journal_of_run(session: AsyncSession, run_id: str) -> list[dict[str, Any]]:
    """Журнал шагов запуска из stats."""
    run = await engine.get_run(session, run_id)
    return list((run.stats or {}).get("journal") or [])


async def _definition_of_run(session: AsyncSession, run: Run) -> ScenarioDefinition | None:
    if not run.scenario_version_id:
        return None
    from app.storage.models import ScenarioVersion

    version = await session.get(ScenarioVersion, run.scenario_version_id)
    if version is None:
        return None
    try:
        return scenario_service.definition_from_version(version)
    except ValidationError:
        return None


def _stats_from_items(
    items: list[Any], definition: ScenarioDefinition
) -> dict[str, dict[str, Any]]:
    total = len(items)
    stats: dict[str, dict[str, Any]] = {}
    for spec in definition.fields:
        filled = sum(1 for item in items if (item.data or {}).get(spec.key) not in (None, ""))
        problems: dict[str, int] = {}
        for item in items:
            if (item.data or {}).get(spec.key) in (None, ""):
                for message in item.validation_errors or []:
                    if message.startswith(f"{spec.key}:"):
                        problem = message.split(":", 1)[-1].strip()
                        problems[problem] = problems.get(problem, 0) + 1
                if not item.validation_errors:
                    problems["не заполнено"] = problems.get("не заполнено", 0) + 1
        stats[spec.key] = {
            "title": spec.title,
            "required": spec.required,
            "filled": filled,
            "total": total,
            "coverage": round(filled / total, 3) if total else 0.0,
            "problems": problems,
        }
    return stats


def _fallback_usage_from_stats(stats: dict[str, Any]) -> dict[str, int]:
    """Сколько раз поле собиралось через запасной селектор."""
    usage = stats.get("fallback_usage") or {}
    return {str(key): int(value) for key, value in usage.items()}


def _required_coverage(
    field_stats: dict[str, dict[str, Any]], definition: ScenarioDefinition
) -> float:
    required = [spec.key for spec in definition.fields if spec.required]
    if not required:
        if not field_stats:
            return 0.0
        return round(sum(item["coverage"] for item in field_stats.values()) / len(field_stats), 3)
    return round(
        sum(field_stats.get(key, {}).get("coverage", 0.0) for key in required) / len(required),
        3,
    )


__all__ = [
    "HealProposal",
    "apply_heal_proposal",
    "build_heal_proposal",
    "journal_of_run",
    "proposal_from_run",
]
