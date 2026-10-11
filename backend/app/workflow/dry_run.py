"""Сухой прогон воркфлоу по DOM снапшота — без реальной отправки форм."""

from __future__ import annotations

from typing import Any

from app.analyzer.domlite import Document, parse
from app.editor import resolver
from app.workflow.params import substitute
from app.workflow.schema import ActionStep, ActionType, RowResult, WorkflowDefinition

# Селекторы типичных сообщений валидации форм.
_FORM_ERROR_SELECTORS = (
    ".error",
    ".field-error",
    ".invalid-feedback",
    "[role='alert']",
    ".form-error",
    ".validation-error",
)


def run_row_dry(
    definition: WorkflowDefinition,
    row: dict[str, str],
    *,
    html: str,
    index: int,
) -> RowResult:
    """Выполняет шаги одной строки на разобранном DOM."""
    document = parse(html)
    form_state: dict[str, str] = {}
    extracted: dict[str, Any] = {}
    skipped: list[str] = []
    log: list[str] = []
    form_errors: list[str] = []
    budget = {"left": definition.max_actions}
    counter = {"n": 0}

    try:
        if definition.total_actions() > definition.max_actions:
            raise RuntimeError(
                f"слишком много шагов: {definition.total_actions()} > {definition.max_actions}"
            )

        _run_steps(
            document,
            definition.steps,
            row,
            form_state=form_state,
            extracted=extracted,
            skipped=skipped,
            log=log,
            form_errors=form_errors,
            skip_dangerous=definition.skip_dangerous_in_dry_run,
            require_confirm=definition.require_confirm_submit,
            budget=budget,
            counter=counter,
        )

        return RowResult(
            index=index,
            ok=True,
            steps_done=counter["n"],
            extracted=extracted,
            skipped=skipped,
            log=log,
            form_errors=form_errors,
        )
    except Exception as exc:  # noqa: BLE001 — отчёт по строке
        if not form_errors:
            form_errors.extend(collect_form_errors(document))
        return RowResult(
            index=index,
            ok=False,
            steps_done=counter["n"],
            error=str(exc),
            extracted=extracted,
            skipped=skipped,
            log=log,
            form_errors=form_errors,
        )


def collect_form_errors(document: Document) -> list[str]:
    """Собирает тексты типичных сообщений об ошибках формы."""
    messages: list[str] = []
    seen: set[str] = set()
    for selector in _FORM_ERROR_SELECTORS:
        report = resolver.resolve(document.root, selector)
        if not report.valid:
            continue
        for node in report.nodes:
            text = (node.all_text(limit=200) or "").strip()
            if text and text not in seen:
                seen.add(text)
                messages.append(text)
    return messages


def _run_steps(
    document: Document,
    steps: list[ActionStep],
    row: dict[str, str],
    *,
    form_state: dict[str, str],
    extracted: dict[str, Any],
    skipped: list[str],
    log: list[str],
    form_errors: list[str],
    skip_dangerous: bool,
    require_confirm: bool,
    budget: dict[str, int],
    counter: dict[str, int],
) -> None:
    for step in steps:
        if budget["left"] <= 0:
            raise RuntimeError("превышен лимит max_actions")
        _execute_step(
            document,
            step,
            row,
            form_state=form_state,
            extracted=extracted,
            skipped=skipped,
            log=log,
            form_errors=form_errors,
            skip_dangerous=skip_dangerous,
            require_confirm=require_confirm,
            budget=budget,
            counter=counter,
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
    form_errors: list[str],
    skip_dangerous: bool,
    require_confirm: bool,
    budget: dict[str, int],
    counter: dict[str, int],
) -> None:
    action = step.type
    budget["left"] -= 1
    counter["n"] += 1

    if action is ActionType.IF:
        ok = _eval_condition(document, step.condition or "", row, extracted)
        log.append(f"if {step.condition} → {ok}")
        if ok:
            _run_steps(
                document,
                step.children,
                row,
                form_state=form_state,
                extracted=extracted,
                skipped=skipped,
                log=log,
                form_errors=form_errors,
                skip_dangerous=skip_dangerous,
                require_confirm=require_confirm,
                budget=budget,
                counter=counter,
            )
        else:
            skipped.append(f"if {step.condition}")
        return

    if action is ActionType.LOOP:
        iterations = _loop_iterations(step, row)
        log.append(f"loop ×{len(iterations)}")
        for item_index, item in enumerate(iterations):
            nested = dict(row)
            nested["_index"] = str(item_index)
            nested["_item"] = item
            _run_steps(
                document,
                step.children,
                nested,
                form_state=form_state,
                extracted=extracted,
                skipped=skipped,
                log=log,
                form_errors=form_errors,
                skip_dangerous=skip_dangerous,
                require_confirm=require_confirm,
                budget=budget,
                counter=counter,
            )
        return

    selector = substitute(step.selector, row)
    value = substitute(step.value, row)
    url = substitute(step.url, row)
    path = substitute(step.path, row)

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

    if action is ActionType.UPLOAD_FILE:
        _require_matches(document, selector, f"upload_file {selector}")
        file_path = path or value or ""
        log.append(f"upload_file {selector} ← {file_path} (dry-run: без записи)")
        skipped.append(f"upload_file {selector}")
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
            if selector:
                nodes = _nodes(document, selector)
                scoped = " ".join(node.all_text(limit=2_000) or "" for node in nodes)
                if needle not in scoped:
                    form_errors.extend(collect_form_errors(document))
                    raise RuntimeError(f"assert_text: не найден текст «{needle}»")
            else:
                form_errors.extend(collect_form_errors(document))
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


def _loop_iterations(step: ActionStep, row: dict[str, str]) -> list[str]:
    if step.loop_over:
        raw = row.get(step.loop_over, "")
        items = [part.strip() for part in raw.split(",") if part.strip()]
        return items or [""]
    times = step.loop_times or 1
    return [str(i) for i in range(times)]


def _eval_condition(
    document: Document,
    condition: str,
    row: dict[str, str],
    extracted: dict[str, Any],
) -> bool:
    condition = condition.strip()
    if not condition:
        return False
    if condition.startswith("exists:"):
        selector = condition[7:].strip()
        return len(_nodes(document, selector)) > 0
    if condition.startswith("missing:"):
        selector = condition[8:].strip()
        return len(_nodes(document, selector)) == 0
    if condition.startswith("text:"):
        needle = condition[5:]
        text = document.root.all_text(limit=50_000) or ""
        return needle in text
    if condition.startswith("column:"):
        key = condition[7:].strip()
        return bool((row.get(key) or "").strip())
    if condition.startswith("equals:"):
        body = condition[7:]
        if "=" not in body:
            return False
        key, expected = body.split("=", 1)
        key = key.strip()
        actual = extracted.get(key)
        if actual is None:
            actual = row.get(key)
        return str(actual) == expected
    # Неизвестный формат — считаем как text:
    text = document.root.all_text(limit=50_000) or ""
    return condition in text


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
