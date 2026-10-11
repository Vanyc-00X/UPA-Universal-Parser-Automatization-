"""Сухой прогон воркфлоу по DOM снапшота — без реальной отправки форм."""

from __future__ import annotations

from typing import Any

from app.analyzer.domlite import Document, parse
from app.editor import resolver
from app.workflow.params import substitute
from app.workflow.schema import ActionStep, ActionType, RowResult, WorkflowDefinition


def run_row_dry(
    definition: WorkflowDefinition,
    row: dict[str, str],
    *,
    html: str,
    index: int,
) -> RowResult:
    """Выполняет шаги одной строки на разобранном DOM.

    ``fill``/``select``/``check`` пишутся в имитацию формы. Опасные ``click``
    пропускаются, если включён ``skip_dangerous_in_dry_run``.
    """
    document = parse(html)
    form_state: dict[str, str] = {}
    extracted: dict[str, Any] = {}
    skipped: list[str] = []
    log: list[str] = []
    steps_done = 0

    try:
        if len(definition.steps) > definition.max_actions:
            raise RuntimeError(
                f"слишком много шагов: {len(definition.steps)} > {definition.max_actions}"
            )

        for step_index, step in enumerate(definition.steps):
            _execute_step(
                document,
                step,
                row,
                form_state=form_state,
                extracted=extracted,
                skipped=skipped,
                log=log,
                skip_dangerous=definition.skip_dangerous_in_dry_run,
                require_confirm=definition.require_confirm_submit,
            )
            steps_done = step_index + 1

        return RowResult(
            index=index,
            ok=True,
            steps_done=steps_done,
            extracted=extracted,
            skipped=skipped,
            log=log,
        )
    except Exception as exc:  # noqa: BLE001 — отчёт по строке
        return RowResult(
            index=index,
            ok=False,
            steps_done=steps_done,
            error=str(exc),
            extracted=extracted,
            skipped=skipped,
            log=log,
        )


def _execute_step(
    document: Document,
    step: ActionStep,
    row: dict[str, str],
    *,
    form_state: dict[str, str],
    extracted: dict[str, Any],
    skipped: list[str],
    log: list[str],
    skip_dangerous: bool,
    require_confirm: bool,
) -> None:
    action = step.type
    selector = substitute(step.selector, row)
    value = substitute(step.value, row)
    url = substitute(step.url, row)

    if action is ActionType.GOTO:
        target = url or value
        if not target:
            raise RuntimeError("goto: не задан url")
        log.append(f"goto {target}")
        return

    if action is ActionType.SCREENSHOT:
        log.append("screenshot (dry-run: пропуск)")
        skipped.append("screenshot")
        return

    if action is ActionType.WAIT_FOR:
        _require_matches(document, selector, f"wait_for {selector}")
        log.append(f"wait_for {selector}")
        return

    if action is ActionType.ASSERT_ELEMENT:
        _require_matches(document, selector, f"assert_element {selector}")
        log.append(f"assert_element {selector}")
        return

    if action is ActionType.ASSERT_TEXT:
        needle = value or ""
        if not needle:
            raise RuntimeError("assert_text: пустое значение")
        text = document.root.all_text(limit=50_000) or ""
        if needle not in text:
            # Иногда текст только в конкретном узле.
            if selector:
                nodes = _nodes(document, selector)
                scoped = " ".join(node.all_text(limit=2_000) or "" for node in nodes)
                if needle not in scoped:
                    raise RuntimeError(f"assert_text: не найден текст «{needle}»")
            else:
                raise RuntimeError(f"assert_text: не найден текст «{needle}»")
        log.append(f"assert_text «{needle}»")
        return

    if action is ActionType.FILL:
        _require_matches(document, selector, f"fill {selector}")
        form_state[selector or ""] = value or ""
        log.append(f"fill {selector} = {value!r}")
        return

    if action is ActionType.SELECT:
        _require_matches(document, selector, f"select {selector}")
        form_state[selector or ""] = value or ""
        log.append(f"select {selector} = {value!r}")
        return

    if action is ActionType.CHECK:
        _require_matches(document, selector, f"check {selector}")
        form_state[selector or ""] = "true"
        log.append(f"check {selector}")
        return

    if action is ActionType.PRESS:
        _require_matches(document, selector, f"press {selector}")
        log.append(f"press {value or 'Enter'} on {selector}")
        return

    if action is ActionType.EXTRACT:
        nodes = _require_matches(document, selector, f"extract {selector}")
        text = nodes[0].all_text(limit=400) if nodes else ""
        key = step.key or selector or "value"
        extracted[key] = text
        log.append(f"extract {key} = {text!r}")
        return

    if action is ActionType.CLICK:
        _require_matches(document, selector, f"click {selector}")
        dangerous = step.looks_dangerous() or (
            require_confirm and _selector_looks_submit(selector or "")
        )
        if dangerous and skip_dangerous:
            skipped.append(f"click {selector}")
            log.append(f"click {selector} — пропущен (dry-run / опасное действие)")
            return
        if dangerous and require_confirm:
            raise RuntimeError(
                f"click {selector}: требуется явное подтверждение отправки формы"
            )
        log.append(f"click {selector}")
        return

    raise RuntimeError(f"неизвестное действие: {action}")


def _selector_looks_submit(selector: str) -> bool:
    lowered = selector.lower()
    return any(
        token in lowered
        for token in ("submit", "type=submit", "btn-primary", "оплат", "send")
    )


def _nodes(document: Document, selector: str | None) -> list[Any]:
    if not selector:
        return []
    report = resolver.resolve(document.root, selector)
    return list(report.nodes) if report.valid else []


def _require_matches(document: Document, selector: str | None, label: str) -> list[Any]:
    if not selector:
        raise RuntimeError(f"{label}: селектор не задан")
    report = resolver.resolve(document.root, selector)
    if not report.valid:
        raise RuntimeError(f"{label}: селектор не поддерживается ({report.error})")
    if report.count == 0:
        raise RuntimeError(f"{label}: элемент не найден")
    return list(report.nodes)
