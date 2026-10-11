"""Поиск рабочих замен селекторов и сборка патча сценария."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.analyzer.domlite import Document, parse
from app.editor import resolver
from app.editor.schema import FieldSpec, ScenarioDefinition
from app.engine.validate import DEFAULT_MIN_COVERAGE


@dataclass
class FieldPatch:
    """Предложение заменить селектор одного поля."""

    key: str
    title: str
    old_selector: str
    new_selector: str
    reason: str
    matches: int
    source: str  # fallback | element_map | role_remap
    required: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "old_selector": self.old_selector,
            "new_selector": self.new_selector,
            "reason": self.reason,
            "matches": self.matches,
            "source": self.source,
            "required": self.required,
        }


@dataclass
class HealProposal:
    """Патч сценария: никогда не применяется молча."""

    run_id: str
    scenario_id: str
    snapshot_id: str | None
    needed: bool
    coverage: float
    min_coverage: float
    broken_fields: list[str] = field(default_factory=list)
    patches: list[FieldPatch] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "snapshot_id": self.snapshot_id,
            "needed": self.needed,
            "coverage": self.coverage,
            "min_coverage": self.min_coverage,
            "broken_fields": self.broken_fields,
            "patches": [patch.as_dict() for patch in self.patches],
            "notes": self.notes,
            "apply_hint": "Патч применяется только по явному подтверждению пользователя",
        }


def diagnose_broken_fields(
    definition: ScenarioDefinition,
    field_stats: dict[str, dict[str, Any]],
    *,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
    fallback_usage: dict[str, int] | None = None,
) -> list[str]:
    """Поля, у которых заполненность ниже порога, селектор пустой или сработал fallback."""
    broken: list[str] = []
    fallback_usage = fallback_usage or {}
    for spec in definition.fields:
        stats = field_stats.get(spec.key) or {}
        coverage = float(stats.get("coverage") or 0.0)
        filled = int(stats.get("filled") or 0)
        total = int(stats.get("total") or 0)
        if total == 0 and spec.required:
            broken.append(spec.key)
            continue
        threshold = min_coverage if spec.required else 0.5
        if total > 0 and coverage < threshold and filled < total:
            broken.append(spec.key)
        problems = stats.get("problems") or {}
        selector_broken = "селектор не находит элементов" in problems or any(
            "запасной" in str(name) for name in problems
        )
        if selector_broken and spec.key not in broken:
            broken.append(spec.key)
        # Основной селектор жив за счёт fallback — всё равно нужна починка.
        if fallback_usage.get(spec.key, 0) > 0 and spec.key not in broken:
            broken.append(spec.key)
    return broken


def propose_field_patches(
    document: Document,
    definition: ScenarioDefinition,
    broken_keys: list[str],
    *,
    element_map_elements: list[dict[str, Any]] | None = None,
) -> list[FieldPatch]:
    """Ищет рабочие селекторы: сначала fallback, затем карта элементов по роли."""
    patches: list[FieldPatch] = []
    by_key = {spec.key: spec for spec in definition.fields}
    elements = element_map_elements or []

    for key in broken_keys:
        spec = by_key.get(key)
        if spec is None:
            continue
        primary_report = resolver.resolve(document.root, spec.selector)
        if primary_report.valid and primary_report.count > 0:
            # Селектор находит узлы — проблема может быть в стратегии/типе, не чиним.
            continue

        patch = _from_fallbacks(document, spec)
        if patch is None:
            patch = _from_element_map(document, spec, elements)
        if patch is not None:
            patches.append(patch)

    return patches


def apply_patches_to_definition(
    definition: ScenarioDefinition, patches: list[FieldPatch]
) -> ScenarioDefinition:
    """Возвращает копию определения с применёнными заменами селекторов."""
    by_key = {patch.key: patch for patch in patches}
    fields: list[FieldSpec] = []
    for spec in definition.fields:
        patch = by_key.get(spec.key)
        if patch is None:
            fields.append(spec)
            continue
        # Старый селектор уходит в запасные — пригодится, если вёрстку откатят.
        fallbacks = [
            item
            for item in [spec.selector, *spec.fallback_selectors]
            if item and item != patch.new_selector
        ]
        fields.append(
            spec.model_copy(
                update={
                    "selector": patch.new_selector,
                    "fallback_selectors": fallbacks[:5],
                    "note": (spec.note or "")
                    + (f" | healing: {patch.reason}" if patch.reason else ""),
                }
            )
        )
    return definition.model_copy(update={"fields": fields})


def _from_fallbacks(document: Document, spec: FieldSpec) -> FieldPatch | None:
    # Сначала проверяем: основной действительно мёртв?
    primary = resolver.resolve(document.root, spec.selector)
    primary_dead = not primary.valid or primary.count == 0

    for candidate in spec.fallback_selectors:
        report = resolver.resolve(document.root, candidate)
        if report.valid and report.count > 0:
            reason = (
                "основной селектор не находит элементы, запасной работает — повысить до основного"
                if primary_dead
                else "запасной селектор находит элементы на текущей странице"
            )
            return FieldPatch(
                key=spec.key,
                title=spec.title,
                old_selector=spec.selector,
                new_selector=candidate,
                reason=reason,
                matches=report.count,
                source="fallback",
                required=spec.required,
            )
    return None


def _from_element_map(
    document: Document,
    spec: FieldSpec,
    elements: list[dict[str, Any]],
) -> FieldPatch | None:
    if not spec.role:
        return None
    for element in elements:
        if str(element.get("role") or "") != spec.role:
            continue
        selectors = _selectors_of(element)
        for candidate in selectors:
            if candidate == spec.selector:
                continue
            report = resolver.resolve(document.root, candidate)
            if report.valid and report.count > 0:
                return FieldPatch(
                    key=spec.key,
                    title=spec.title,
                    old_selector=spec.selector,
                    new_selector=candidate,
                    reason=f"кандидат из карты элементов (роль «{spec.role}»)",
                    matches=report.count,
                    source="element_map",
                    required=spec.required,
                )
    return None


def _selectors_of(element: dict[str, Any]) -> list[str]:
    ordered: list[str] = []
    primary = element.get("selector")
    if primary:
        ordered.append(str(primary))
    for item in element.get("selectors") or []:
        selector = item.get("selector") if isinstance(item, dict) else None
        if selector and str(selector) not in ordered:
            ordered.append(str(selector))
    return ordered


def parse_html(html: str) -> Document:
    return parse(html)
