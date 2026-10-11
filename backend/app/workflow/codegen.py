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
from pathlib import Path
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


def eval_condition(page, condition, row, extracted):
    condition = (condition or "").strip()
    if condition.startswith("exists:"):
        return page.locator(condition[7:].strip()).count() > 0
    if condition.startswith("missing:"):
        return page.locator(condition[8:].strip()).count() == 0
    if condition.startswith("text:"):
        return condition[5:] in page.content()
    if condition.startswith("column:"):
        return bool((row.get(condition[7:].strip()) or "").strip())
    if condition.startswith("equals:") and "=" in condition[7:]:
        key, expected = condition[7:].split("=", 1)
        actual = extracted.get(key.strip(), row.get(key.strip()))
        return str(actual) == expected
    return condition in page.content()


def run_steps(page, steps, row, extracted):
    for step in steps:
        action = step["type"]
        if action == "if":
            if eval_condition(page, step.get("condition"), row, extracted):
                run_steps(page, step.get("children") or [], row, extracted)
            continue
        if action == "loop":
            if step.get("loop_over"):
                raw = row.get(step["loop_over"]) or ""
                items = [p.strip() for p in raw.split(",") if p.strip()] or [""]
            else:
                items = [str(i) for i in range(int(step.get("loop_times") or 1))]
            for item_index, item in enumerate(items):
                nested = dict(row)
                nested["_index"] = str(item_index)
                nested["_item"] = item
                run_steps(page, step.get("children") or [], nested, extracted)
            continue

        selector = substitute(step.get("selector"), row)
        value = substitute(step.get("value"), row)
        url = substitute(step.get("url"), row)
        path = substitute(step.get("path"), row)

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
            key = step.get("key") or selector
            extracted[key] = text
            print("extract", key, text)
        elif action == "upload_file":
            page.set_input_files(selector, str(Path(path or value or "")))


def run_row(page, row):
    run_steps(page, STEPS, row, {})


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
    if step.type is ActionType.UPLOAD_FILE:
        return f"page.set_input_files({step.selector!r}, {step.path or step.value!r})"
    if step.type is ActionType.IF:
        return f"if {step.condition}: ({len(step.children)} steps)"
    if step.type is ActionType.LOOP:
        target = step.loop_over or f"×{step.loop_times}"
        return f"loop {target}: ({len(step.children)} steps)"
    return f"# {step.type.value}"
