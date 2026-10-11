"""Живой прогон воркфлоу через Playwright."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.workflow.params import substitute
from app.workflow.schema import ActionType, RowResult, WorkflowDefinition

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
    steps_done = 0
    try:
        for step_index, step in enumerate(definition.steps):
            selector = substitute(step.selector, row)
            value = substitute(step.value, row)
            url = substitute(step.url, row)
            action = step.type
            timeout = step.timeout_ms

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
                    raise RuntimeError(f"assert_text: не найден текст «{value}»")
                log_lines.append(f"assert_text «{value}»")
            elif action is ActionType.ASSERT_ELEMENT:
                await page.wait_for_selector(selector, timeout=timeout)
                log_lines.append(f"assert_element {selector}")
            elif action is ActionType.SCREENSHOT:
                path = f"upa_row_{index}.png"
                await page.screenshot(path=path, full_page=True)
                log_lines.append(f"screenshot {path}")
            elif action is ActionType.EXTRACT:
                text = await page.locator(selector).inner_text(timeout=timeout)
                key = step.key or selector or "value"
                extracted[key] = text
                log_lines.append(f"extract {key}")
            else:
                raise RuntimeError(f"неизвестное действие: {action}")
            steps_done = step_index + 1

        return RowResult(
            index=index,
            ok=True,
            steps_done=steps_done,
            extracted=extracted,
            skipped=skipped,
            log=log_lines,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("workflow.row_failed", index=index, error=str(exc)[:200])
        return RowResult(
            index=index,
            ok=False,
            steps_done=steps_done,
            error=str(exc),
            extracted=extracted,
            skipped=skipped,
            log=log_lines,
        )
