"""Сервис сценариев: сохранение, версии, чтение.

Сценарий — это версионируемый артефакт. Правка вёрстки порождает новую версию, а
не потерю работы: старые версии остаются, и по ним видно, что менялось.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.editor.schema import ScenarioDefinition, ScenarioOut, ScenarioVersionOut
from app.storage.models import Scenario, ScenarioVersion, Site, utcnow

log = get_logger(__name__)


async def save_scenario(
    session: AsyncSession,
    definition: ScenarioDefinition,
    *,
    name: str,
    site_id: str,
    description: str | None = None,
    change_note: str | None = None,
    scenario_id: str | None = None,
    created_by: str = "editor",
) -> tuple[Scenario, ScenarioVersion]:
    """Сохраняет сценарий: создаёт новый или добавляет версию к существующему.

    Возвращает запись сценария и только что созданную версию.
    """
    if scenario_id:
        scenario = await session.get(Scenario, scenario_id)
        if scenario is None:
            raise NotFoundError("Сценарий не найден", details={"scenario_id": scenario_id})
        if scenario.site_id != site_id:
            raise ValidationError(
                "Сценарий принадлежит другому сайту",
                details={"scenario_site": scenario.site_id, "requested_site": site_id},
            )
    else:
        scenario = await _find_by_name(session, site_id, name)
        if scenario is None:
            scenario = Scenario(
                site_id=site_id,
                name=name,
                description=description,
                kind="collection",
                is_active=True,
                current_version=0,
            )
            session.add(scenario)
            await session.flush()
            log.info("scenario.created", scenario_id=scenario.id, site_id=site_id, name=name)

    version_number = int(scenario.current_version or 0) + 1
    payload = definition.model_dump(mode="json")
    version = ScenarioVersion(
        scenario_id=scenario.id,
        version=version_number,
        definition=payload,
        change_note=change_note,
        created_by=created_by,
    )
    session.add(version)

    scenario.current_version = version_number
    scenario.name = name
    if description is not None:
        scenario.description = description
    scenario.updated_at = utcnow()
    await session.flush()

    log.info(
        "scenario.version_saved",
        scenario_id=scenario.id,
        version=version_number,
        fields=len(definition.fields),
    )
    return scenario, version


async def _find_by_name(session: AsyncSession, site_id: str, name: str) -> Scenario | None:
    """Ищет сценарий того же сайта с таким именем: тогда добавляется версия."""
    result = await session.execute(
        select(Scenario).where(Scenario.site_id == site_id, Scenario.name == name)
    )
    return result.scalar_one_or_none()


async def get_scenario(session: AsyncSession, scenario_id: str) -> Scenario:
    """Сценарий или понятная ошибка 404."""
    scenario = await session.get(Scenario, scenario_id)
    if scenario is None:
        raise NotFoundError("Сценарий не найден", details={"scenario_id": scenario_id})
    return scenario


async def get_current_version(session: AsyncSession, scenario: Scenario) -> ScenarioVersion | None:
    """Актуальная версия сценария."""
    if not scenario.current_version:
        return None
    result = await session.execute(
        select(ScenarioVersion).where(
            ScenarioVersion.scenario_id == scenario.id,
            ScenarioVersion.version == scenario.current_version,
        )
    )
    return result.scalar_one_or_none()


async def list_versions(
    session: AsyncSession, scenario_id: str, *, limit: int = 50
) -> list[ScenarioVersion]:
    """История версий, свежие сверху."""
    result = await session.execute(
        select(ScenarioVersion)
        .where(ScenarioVersion.scenario_id == scenario_id)
        .order_by(ScenarioVersion.version.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_scenarios(
    session: AsyncSession, *, site_id: str | None = None, limit: int = 100, offset: int = 0
) -> list[Scenario]:
    """Список сценариев, недавно обновлённые сверху."""
    statement = select(Scenario).order_by(Scenario.updated_at.desc()).limit(limit).offset(offset)
    if site_id:
        statement = statement.where(Scenario.site_id == site_id)
    result = await session.execute(statement)
    return list(result.scalars().all())


async def count_scenarios(session: AsyncSession, site_id: str | None = None) -> int:
    """Сколько сценариев есть в базе."""
    statement = select(func.count()).select_from(Scenario)
    if site_id:
        statement = statement.where(Scenario.site_id == site_id)
    return int((await session.execute(statement)).scalar_one())


async def delete_scenario(session: AsyncSession, scenario_id: str) -> None:
    """Удаляет сценарий вместе со всеми версиями."""
    scenario = await get_scenario(session, scenario_id)
    await session.delete(scenario)
    await session.flush()
    log.info("scenario.deleted", scenario_id=scenario_id)


def scenario_to_out(
    scenario: Scenario, definition: ScenarioDefinition | None = None
) -> ScenarioOut:
    """Представление сценария для API."""
    return ScenarioOut(
        id=scenario.id,
        site_id=scenario.site_id,
        name=scenario.name,
        description=scenario.description,
        kind=scenario.kind,
        is_active=scenario.is_active,
        current_version=scenario.current_version,
        definition=definition,
        created_at=scenario.created_at,
        updated_at=scenario.updated_at,
    )


def version_to_out(version: ScenarioVersion) -> ScenarioVersionOut:
    """Представление версии для API."""
    return ScenarioVersionOut(
        id=version.id,
        scenario_id=version.scenario_id,
        version=version.version,
        definition=ScenarioDefinition.model_validate(version.definition or {}),
        change_note=version.change_note,
        created_by=version.created_by,
        created_at=version.created_at,
    )


def definition_from_version(version: ScenarioVersion) -> ScenarioDefinition:
    """Разбирает определение из версии с понятной ошибкой при порче данных."""
    try:
        return ScenarioDefinition.model_validate(version.definition or {})
    except Exception as exc:  # noqa: BLE001 — повреждённая запись в базе
        raise ValidationError(
            "Определение сценария повреждено и не читается",
            details={"version": version.version, "reason": str(exc)[:200]},
        ) from exc


async def site_for_definition(session: AsyncSession, site_id: str) -> Site:
    """Проверяет существование сайта — сценарий всегда привязан к сайту."""
    site = await session.get(Site, site_id)
    if site is None:
        raise NotFoundError("Сайт не найден", details={"site_id": site_id})
    return site


def definition_as_dict(definition: ScenarioDefinition) -> dict[str, Any]:
    """Определение в виде обычного словаря — для логов и отладки."""
    return definition.model_dump(mode="json")
