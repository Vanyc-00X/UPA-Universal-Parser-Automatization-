"""Экспорт воркфлоу в самостоятельный Python-скрипт на Playwright."""

from __future__ import annotations

import json

from app.workflow.schema import ActionStep, ActionType, WorkflowDefinition

# Шаблон скрипта: плейсхолдеры __TITLE__, __BASE_URL__, __STEPS__, __ROWS__.
_SCRIPT_TEMPLATE = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сгенерировано UPA: сценарий «__TITLE__».

Запуск:
    pip install playwright
    playwright install chromium
    python this_script.py
"""

from __future__ import annotations

import re
from playwright.sync_api import sync_playwright

BASE_URL = __BASE_URL__
STEPS = __STEPS__
ROWS = __ROWS__
TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z_][\w.-]*)\s*\}\}")


def substitute(template, row):
    if template is None:
        return None

    def replacer(match):
        key = match.group(1)
        if key not in row:
            raise KeyError(f"нет колонки {key}")
        return row[key]

    return TEMPLATE_RE.sub(replacer, template)


def run_row(page, row):
    for step in STEPS:
        action = step["type"]
        selector = substitute(step.get("selector"), row)
        value = substitute(step.get("value"), row)
        url = substitute(step.get("url"), row)

        if action == "goto":
            page.goto(url or value or BASE_URL, wait_until="domcontentloaded")
        elif action == "fill":
            page.fill(selector, value or "")
        elif action == "click":
            page.click(selector)
        elif action == "select":
            page.select_option(selector, value or "")
        elif action == "check":
            page.check(selector)
        elif action == "press":
            page.press(selector, value or "Enter")
        elif action == "wait_for":
            page.wait_for_selector(selector, timeout=step.get("timeout_ms", 5000))
        elif action == "assert_text":
            content = page.content()
            assert value in content, f"текст не найден: {value!r}"
        elif action == "assert_element":
            page.wait_for_selector(selector, timeout=step.get("timeout_ms", 5000))
        elif action == "screenshot":
            page.screenshot(path=f"upa_{row.get('id', 'row')}.png", full_page=True)
        elif action == "extract":
            text = page.locator(selector).inner_text()
            print("extract", step.get("key") or selector, text)


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        for index, row in enumerate(ROWS):
            print(f"=== строка {index + 1}/{len(ROWS)} ===")
            run_row(page, row)
        browser.close()


if __name__ == "__main__":
    main()
'''


def render_playwright_script(
    definition: WorkflowDefinition,
    *,
    rows: list[dict[str, str]] | None = None,
) -> str:
    """Генерирует скрипт, который можно запустить без UPA."""
    sample_rows = rows or [{"example": "value"}]
    steps_repr = json.dumps(
        [step.model_dump(mode="json") for step in definition.steps],
        ensure_ascii=False,
        indent=2,
    )
    rows_repr = json.dumps(sample_rows, ensure_ascii=False, indent=2)
    return (
        _SCRIPT_TEMPLATE.replace("__TITLE__", definition.title)
        .replace("__BASE_URL__", repr(definition.url))
        .replace("__STEPS__", steps_repr)
        .replace("__ROWS__", rows_repr)
    )


def step_to_playwright_line(step: ActionStep) -> str:
    """Одна строка для документации/превью."""
    if step.type is ActionType.GOTO:
        return f"page.goto({step.url or step.value!r})"
    if step.type is ActionType.FILL:
        return f"page.fill({step.selector!r}, {step.value!r})"
    if step.type is ActionType.CLICK:
        return f"page.click({step.selector!r})"
    if step.type is ActionType.SELECT:
        return f"page.select_option({step.selector!r}, {step.value!r})"
    if step.type is ActionType.CHECK:
        return f"page.check({step.selector!r})"
    if step.type is ActionType.PRESS:
        return f"page.press({step.selector!r}, {step.value or 'Enter'!r})"
    if step.type is ActionType.WAIT_FOR:
        return f"page.wait_for_selector({step.selector!r})"
    if step.type is ActionType.ASSERT_TEXT:
        return f"assert {step.value!r} in page.content()"
    if step.type is ActionType.ASSERT_ELEMENT:
        return f"page.wait_for_selector({step.selector!r})"
    if step.type is ActionType.SCREENSHOT:
        return 'page.screenshot(path="upa.png", full_page=True)'
    if step.type is ActionType.EXTRACT:
        return f"page.locator({step.selector!r}).inner_text()"
    return f"# {step.type.value}"
