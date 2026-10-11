"""Живой прогон воркфлоу через Playwright."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.workflow.params import substitute
from app.workflow.schema import ActionStep, ActionType, RowResult, WorkflowDefinition

log = get_logger(__name__)


async def run_rows_live(
    settings: Settings,
    definition: WorkflowDefinition,
    rows: list[dict[str, str]],
) -> list[RowResult]:
    """Выполняет воркфлоу в реальном браузере построчно."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Playwright не установлен") from exc

    results: list[RowResult] = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=settings.browser_headless)
        context = await browser.new_context(
            locale=settings.browser_locale,
            user_agent=settings.browser_user_agent or None,
            viewport={
                "width": settings.browser_viewport_width,
                "height": settings.browser_viewport_height,
            },
        )
        page = await context.new_page()
        try:
            for index, row in enumerate(rows):
                results.append(await _run_one(page, definition, row, index=index))
        finally:
            await context.close()
            await browser.close()
    return results


async def _run_one(
    page: Any, definition: WorkflowDefinition, row: dict[str, str], *, index: int
) -> RowResult:
    log_lines: list[str] = []
    extracted: dict[str, Any] = {}
    skipped: list[str] = []
    form_errors: list[str] = []
    counter = {"n": 0}
    budget = {"left": definition.max_actions}
    try:
        await _run_steps(
            page,
            definition.steps,
            row,
            definition=definition,
            extracted=extracted,
            skipped=skipped,
            log_lines=log_lines,
            form_errors=form_errors,
            counter=counter,
            budget=budget,
            row_index=index,
        )
        return RowResult(
            index=index,
            ok=True,
            steps_done=counter["n"],
            extracted=extracted,
            skipped=skipped,
            log=log_lines,
            form_errors=form_errors,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("workflow.row_failed", index=index, error=str(exc)[:200])
        if not form_errors:
            form_errors.extend(await _collect_page_errors(page))
        return RowResult(
            index=index,
            ok=False,
            steps_done=counter["n"],
            error=str(exc),
            extracted=extracted,
            skipped=skipped,
            log=log_lines,
            form_errors=form_errors,
        )


async def _run_steps(
    page: Any,
    steps: list[ActionStep],
    row: dict[str, str],
    *,
    definition: WorkflowDefinition,
    extracted: dict[str, Any],
    skipped: list[str],
    log_lines: list[str],
    form_errors: list[str],
    counter: dict[str, int],
    budget: dict[str, int],
    row_index: int,
) -> None:
    for step in steps:
        if budget["left"] <= 0:
            raise RuntimeError("превышен лимит max_actions")
        await _execute_step(
            page,
            step,
            row,
            definition=definition,
            extracted=extracted,
            skipped=skipped,
            log_lines=log_lines,
            form_errors=form_errors,
            counter=counter,
            budget=budget,
            row_index=row_index,
        )


async def _execute_step(
    page: Any,
    step: ActionStep,
    row: dict[str, str],
    *,
    definition: WorkflowDefinition,
    extracted: dict[str, Any],
    skipped: list[str],
    log_lines: list[str],
    form_errors: list[str],
    counter: dict[str, int],
    budget: dict[str, int],
    row_index: int,
) -> None:
    budget["left"] -= 1
    counter["n"] += 1
    action = step.type
    timeout = step.timeout_ms

    if action is ActionType.IF:
        ok = await _eval_condition(page, step.condition or "", row, extracted)
        log_lines.append(f"if {step.condition} → {ok}")
        if ok:
            await _run_steps(
                page,
                step.children,
                row,
                definition=definition,
                extracted=extracted,
                skipped=skipped,
                log_lines=log_lines,
                form_errors=form_errors,
                counter=counter,
                budget=budget,
                row_index=row_index,
            )
        else:
            skipped.append(f"if {step.condition}")
        return

    if action is ActionType.LOOP:
        iterations = _loop_iterations(step, row)
        log_lines.append(f"loop ×{len(iterations)}")
        for item_index, item in enumerate(iterations):
            nested = dict(row)
            nested["_index"] = str(item_index)
            nested["_item"] = item
            await _run_steps(
                page,
                step.children,
                nested,
                definition=definition,
                extracted=extracted,
                skipped=skipped,
                log_lines=log_lines,
                form_errors=form_errors,
                counter=counter,
                budget=budget,
                row_index=row_index,
            )
        return

    selector = substitute(step.selector, row)
    value = substitute(step.value, row)
    url = substitute(step.url, row)
    path = substitute(step.path, row)

    if action is ActionType.GOTO:
        target = url or value or definition.url
        await page.goto(target, wait_until="domcontentloaded", timeout=timeout)
        log_lines.append(f"goto {target}")
    elif action is ActionType.FILL:
        await page.fill(selector, value or "", timeout=timeout)
        log_lines.append(f"fill {selector}")
    elif action is ActionType.CLICK:
        await page.click(selector, timeout=timeout)
        log_lines.append(f"click {selector}")
    elif action is ActionType.SELECT:
        await page.select_option(selector, value or "", timeout=timeout)
        log_lines.append(f"select {selector}")
    elif action is ActionType.CHECK:
        await page.check(selector, timeout=timeout)
        log_lines.append(f"check {selector}")
    elif action is ActionType.PRESS:
        await page.press(selector, value or "Enter", timeout=timeout)
        log_lines.append(f"press {selector}")
    elif action is ActionType.WAIT_FOR:
        await page.wait_for_selector(selector, timeout=timeout)
        log_lines.append(f"wait_for {selector}")
    elif action is ActionType.ASSERT_TEXT:
        content = await page.content()
        if value not in content:
            form_errors.extend(await _collect_page_errors(page))
            raise RuntimeError(f"assert_text: не найден текст «{value}»")
        log_lines.append(f"assert_text «{value}»")
    elif action is ActionType.ASSERT_ELEMENT:
        await page.wait_for_selector(selector, timeout=timeout)
        log_lines.append(f"assert_element {selector}")
    elif action is ActionType.SCREENSHOT:
        out = f"upa_row_{row_index}.png"
        await page.screenshot(path=out, full_page=True)
        log_lines.append(f"screenshot {out}")
    elif action is ActionType.EXTRACT:
        text = await page.locator(selector).inner_text(timeout=timeout)
        key = step.key or selector or "value"
        extracted[key] = text
        log_lines.append(f"extract {key}")
    elif action is ActionType.UPLOAD_FILE:
        file_path = path or value or ""
        exists = bool(file_path) and await asyncio.to_thread(os.path.isfile, file_path)
        if not exists:
            raise RuntimeError(f"upload_file: файл не найден «{file_path}»")
        await page.set_input_files(selector, file_path, timeout=timeout)
        log_lines.append(f"upload_file {selector}")
    else:
        raise RuntimeError(f"неизвестное действие: {action}")


def _loop_iterations(step: ActionStep, row: dict[str, str]) -> list[str]:
    if step.loop_over:
        raw = row.get(step.loop_over, "")
        items = [part.strip() for part in raw.split(",") if part.strip()]
        return items or [""]
    times = step.loop_times or 1
    return [str(i) for i in range(times)]


async def _eval_condition(
    page: Any, condition: str, row: dict[str, str], extracted: dict[str, Any]
) -> bool:
    condition = condition.strip()
    if condition.startswith("exists:"):
        selector = condition[7:].strip()
        return await page.locator(selector).count() > 0
    if condition.startswith("missing:"):
        selector = condition[8:].strip()
        return await page.locator(selector).count() == 0
    if condition.startswith("text:"):
        needle = condition[5:]
        content = await page.content()
        return needle in content
    if condition.startswith("column:"):
        key = condition[7:].strip()
        return bool((row.get(key) or "").strip())
    if condition.startswith("equals:"):
        body = condition[7:]
        if "=" not in body:
            return False
        key, expected = body.split("=", 1)
        actual = extracted.get(key.strip())
        if actual is None:
            actual = row.get(key.strip())
        return str(actual) == expected
    content = await page.content()
    return condition in content


async def _collect_page_errors(page: Any) -> list[str]:
    messages: list[str] = []
    for selector in (
        ".error",
        ".field-error",
        ".invalid-feedback",
        "[role='alert']",
        ".form-error",
    ):
        try:
            loc = page.locator(selector)
            count = await loc.count()
            for index in range(min(count, 10)):
                text = (await loc.nth(index).inner_text()).strip()
                if text and text not in messages:
                    messages.append(text)
        except Exception:  # noqa: BLE001
            continue
    return messages
