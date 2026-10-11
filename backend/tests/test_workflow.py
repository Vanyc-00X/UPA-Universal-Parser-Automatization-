"""Юнит-тесты воркфлоу: params, dry-run, codegen (Этап 7)."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.workflow import codegen, dry_run, params
from app.workflow.schema import ActionStep, ActionType, WorkflowDefinition
from tests.fakes import build_form_html


def _workflow(*, dangerous_submit: bool = True) -> WorkflowDefinition:
    steps = [
        ActionStep(type=ActionType.GOTO, url="https://forms.example.com/order"),
        ActionStep(type=ActionType.FILL, selector="#field-name", value="{{name}}"),
        ActionStep(type=ActionType.FILL, selector="#field-email", value="{{email}}"),
        ActionStep(type=ActionType.SELECT, selector="#field-city", value="{{city}}"),
        ActionStep(type=ActionType.CHECK, selector="#field-agree"),
        ActionStep(type=ActionType.ASSERT_TEXT, value="Заполните все поля"),
        ActionStep(type=ActionType.EXTRACT, selector="h1", key="heading"),
    ]
    if dangerous_submit:
        steps.append(
            ActionStep(
                type=ActionType.CLICK,
                selector="#btn-submit",
                confirm_required=True,
                note="отправка формы",
            )
        )
    return WorkflowDefinition(
        url="https://forms.example.com/order",
        title="Заявка",
        steps=steps,
        max_rows=50,
    )


def test_parse_csv_and_substitute() -> None:
    rows = params.parse_rows_csv("name,email\nИван,a@b.c\nМария,m@x.y\n")
    assert len(rows) == 2
    assert params.substitute("Привет, {{name}}!", rows[0]) == "Привет, Иван!"
    with pytest.raises(ValidationError):
        params.substitute("{{missing}}", rows[0])


def test_parse_rows_json_wrapper() -> None:
    rows = params.parse_rows_json({"rows": [{"a": 1}, {"a": None}]})
    assert rows == [{"a": "1"}, {"a": ""}]


def test_limit_rows() -> None:
    rows = [{"i": str(i)} for i in range(3)]
    assert params.limit_rows(rows, 3) == rows
    with pytest.raises(ValidationError):
        params.limit_rows(rows, 2)


def test_dry_run_fills_and_skips_dangerous_submit() -> None:
    html = build_form_html()
    definition = _workflow(dangerous_submit=True)
    result = dry_run.run_row_dry(
        definition,
        {"name": "Иван", "email": "a@b.c", "city": "msk"},
        html=html,
        index=0,
    )
    assert result.ok, result.error
    assert result.extracted.get("heading") == "Форма заявки"
    assert any("пропущен" in line for line in result.log)
    assert result.skipped


def test_dry_run_fails_on_missing_selector() -> None:
    html = build_form_html()
    definition = WorkflowDefinition(
        url="https://forms.example.com/order",
        title="Broken",
        steps=[ActionStep(type=ActionType.FILL, selector="#no-such", value="x")],
    )
    result = dry_run.run_row_dry(definition, {}, html=html, index=0)
    assert not result.ok
    assert "не найден" in (result.error or "")


def test_action_step_requires_selector() -> None:
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        ActionStep(type=ActionType.CLICK, selector=None)


def test_looks_dangerous_from_hint() -> None:
    step = ActionStep(type=ActionType.CLICK, selector="button.checkout-pay")
    assert step.looks_dangerous()


def test_codegen_contains_playwright_and_rows() -> None:
    definition = _workflow(dangerous_submit=False)
    script = codegen.render_playwright_script(
        definition, rows=[{"name": "Иван", "email": "a@b.c", "city": "msk"}]
    )
    assert "from playwright.sync_api import sync_playwright" in script
    assert "page.fill" in script
    assert "Иван" in script
    assert "TEMPLATE_RE" in script
    line = codegen.step_to_playwright_line(definition.steps[1])
    assert "page.fill" in line
