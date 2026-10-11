"""Запись и «очеловечивание» шагов воркфлоу (codegen-подобный режим)."""

from __future__ import annotations

import re
from typing import Any

from app.workflow.schema import (
    DANGEROUS_CLICK_HINTS,
    ActionStep,
    ActionType,
    RecordedEvent,
    WorkflowDefinition,
)

_VALUE_COLUMN_HINTS = {
    "name": "name",
    "имя": "name",
    "email": "email",
    "почта": "email",
    "phone": "phone",
    "тел": "phone",
    "city": "city",
    "город": "city",
    "price": "price",
    "цена": "price",
    "title": "title",
    "название": "title",
}


def events_to_steps(events: list[RecordedEvent]) -> list[ActionStep]:
    """Превращает сырые события записи в шаги ActionStep."""
    steps: list[ActionStep] = []
    for event in events:
        action = ActionType(event.type)
        selector = _prefer_selector(event.selector)
        step = ActionStep(
            type=action,
            selector=selector,
            value=event.value,
            url=event.url,
            path=event.path,
            key=event.key,
            note=_event_note(event),
            confirm_required=_looks_submit(event),
        )
        steps.append(step)
    return compact_steps(steps)


def build_workflow_from_recording(
    *,
    url: str,
    title: str = "Записанный сценарий",
    events: list[RecordedEvent],
    humanize: bool = True,
) -> WorkflowDefinition:
    """Собирает WorkflowDefinition из записанных событий."""
    steps = events_to_steps(events)
    if humanize:
        steps = humanize_steps(steps)
    if not steps:
        steps = [ActionStep(type=ActionType.GOTO, url=url)]
    elif steps[0].type is not ActionType.GOTO:
        steps.insert(0, ActionStep(type=ActionType.GOTO, url=url))
    return WorkflowDefinition(url=url, title=title, steps=steps)


def compact_steps(steps: list[ActionStep]) -> list[ActionStep]:
    """Склеивает подряд идущие fill/select по одному селектору."""
    if not steps:
        return []
    result: list[ActionStep] = [steps[0]]
    for step in steps[1:]:
        prev = result[-1]
        same_target = (
            prev.type is step.type
            and prev.type in {ActionType.FILL, ActionType.SELECT}
            and prev.selector == step.selector
            and prev.selector
        )
        if same_target:
            result[-1] = step
            continue
        result.append(step)
    return result


def humanize_steps(steps: list[ActionStep]) -> list[ActionStep]:
    """Правила «очеловечивания»: короткие селекторы, {{column}}, флаг submit."""
    used_columns: set[str] = set()
    result: list[ActionStep] = []
    for step in steps:
        selector = _prefer_selector(step.selector)
        value = step.value
        note = step.note
        confirm = step.confirm_required or (
            step.type is ActionType.CLICK and _selector_has_danger(selector, note)
        )

        if step.type is ActionType.FILL and value and "{{" not in value:
            column = _suggest_column(selector, note, value, used_columns)
            if column:
                used_columns.add(column)
                value = f"{{{{{column}}}}}"
                note = note or f"параметр {column}"

        if step.type is ActionType.CLICK and confirm and not note:
            note = "отправка формы"

        result.append(
            step.model_copy(
                update={
                    "selector": selector,
                    "value": value,
                    "note": note,
                    "confirm_required": confirm,
                }
            )
        )
    return compact_steps(result)


def humanize_workflow(definition: WorkflowDefinition) -> WorkflowDefinition:
    """Очеловечивает шаги уже готового определения."""
    return definition.model_copy(update={"steps": humanize_steps(definition.steps)})


def recording_summary(steps: list[ActionStep]) -> dict[str, Any]:
    return {
        "steps": len(steps),
        "fills": sum(1 for step in steps if step.type is ActionType.FILL),
        "clicks": sum(1 for step in steps if step.type is ActionType.CLICK),
        "dangerous": sum(1 for step in steps if step.looks_dangerous()),
        "params": sorted(
            {
                match.group(1)
                for step in steps
                for match in re.finditer(r"\{\{\s*([\w.-]+)\s*\}\}", step.value or "")
            }
        ),
    }


def _prefer_selector(selector: str | None) -> str | None:
    if not selector:
        return selector
    cleaned = selector.strip()
    # Берём самый короткий из цепочки через запятую (часто id идёт первым).
    if "," in cleaned:
        parts = [part.strip() for part in cleaned.split(",") if part.strip()]
        cleaned = min(parts, key=len)
    # Укорачиваем глубокие пути: оставляем хвост с id/классом.
    if " " in cleaned and ("#" in cleaned or "." in cleaned):
        tokens = cleaned.split()
        for token in reversed(tokens):
            if token.startswith("#") or token.startswith("."):
                return token
        return " ".join(tokens[-2:])
    return cleaned


def _suggest_column(
    selector: str | None, note: str | None, value: str, used: set[str]
) -> str | None:
    haystack = f"{selector or ''} {note or ''}".lower()
    for hint, column in _VALUE_COLUMN_HINTS.items():
        if hint in haystack and column not in used:
            return column
    # id="field-email" → email
    if selector:
        match = re.search(r"(?:#|name=|\[name=['\"]?)([a-zA-Z_][\w-]*)", selector)
        if match:
            token = match.group(1).lower().replace("field-", "").replace("input-", "")
            for hint, column in _VALUE_COLUMN_HINTS.items():
                if hint in token and column not in used:
                    return column
            if token.isidentifier() and token not in used and not token.startswith("btn"):
                return token
    if "@" in value and "email" not in used:
        return "email"
    return None


def _event_note(event: RecordedEvent) -> str | None:
    parts = [part for part in (event.name, event.text, event.tag) if part]
    if not parts:
        return None
    return " / ".join(parts)[:120]


def _looks_submit(event: RecordedEvent) -> bool:
    if event.type != "click":
        return False
    haystack = " ".join(
        part
        for part in (event.selector, event.text, event.name, event.input_type, event.value)
        if part
    ).lower()
    if event.input_type == "submit":
        return True
    return any(hint in haystack for hint in DANGEROUS_CLICK_HINTS) or "submit" in haystack


def _selector_has_danger(selector: str | None, note: str | None) -> bool:
    haystack = f"{selector or ''} {note or ''}".lower()
    return any(hint in haystack for hint in DANGEROUS_CLICK_HINTS)
