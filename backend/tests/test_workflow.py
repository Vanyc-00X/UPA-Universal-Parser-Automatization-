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


def test_dry_run_if_and_loop() -> None:
    html = build_form_html()
    definition = WorkflowDefinition(
        url="https://forms.example.com/order",
        title="Control flow",
        steps=[
            ActionStep(
                type=ActionType.IF,
                condition="exists:#field-name",
                children=[
                    ActionStep(type=ActionType.FILL, selector="#field-name", value="{{name}}"),
                ],
            ),
            ActionStep(
                type=ActionType.LOOP,
                loop_times=2,
                children=[
                    ActionStep(type=ActionType.ASSERT_ELEMENT, selector="#field-email"),
                ],
            ),
            ActionStep(
                type=ActionType.IF,
                condition="missing:#nope",
                children=[
                    ActionStep(type=ActionType.EXTRACT, selector="h1", key="heading"),
                ],
            ),
        ],
    )
    result = dry_run.run_row_dry(definition, {"name": "Иван"}, html=html, index=0)
    assert result.ok, result.error
    assert result.extracted.get("heading") == "Форма заявки"
    assert any(line.startswith("loop") for line in result.log)


def test_dry_run_upload_file_skipped() -> None:
    html = build_form_html().replace(
        "</form>",
        '<input type="file" id="field-file" name="file" /></form>',
    )
    definition = WorkflowDefinition(
        url="https://forms.example.com/order",
        title="Upload",
        steps=[
            ActionStep(
                type=ActionType.UPLOAD_FILE,
                selector="#field-file",
                path="{{file}}",
            )
        ],
    )
    result = dry_run.run_row_dry(definition, {"file": "doc.pdf"}, html=html, index=0)
    assert result.ok, result.error
    assert result.skipped


def test_dry_run_twenty_rows_report() -> None:
    html = build_form_html()
    definition = _workflow(dangerous_submit=True)
    rows = [
        {"name": f"User{i}", "email": f"u{i}@ex.com", "city": "msk" if i % 2 == 0 else "spb"}
        for i in range(20)
    ]
    results = [
        dry_run.run_row_dry(definition, row, html=html, index=index)
        for index, row in enumerate(rows)
    ]
    assert len(results) == 20
    assert all(item.ok for item in results)


def test_recording_humanize_suggests_columns() -> None:
    from app.workflow import record
    from app.workflow.schema import RecordedEvent

    events = [
        RecordedEvent(type="goto", url="https://forms.example.com/order"),
        RecordedEvent(type="fill", selector="#field-name", value="Иван", name="name"),
        RecordedEvent(type="fill", selector="#field-name", value="Иван Иванов", name="name"),
        RecordedEvent(type="fill", selector="#field-email", value="a@b.c"),
        RecordedEvent(type="click", selector="#btn-submit", text="Отправить", input_type="submit"),
    ]
    workflow = record.build_workflow_from_recording(
        url="https://forms.example.com/order",
        title="Rec",
        events=events,
        humanize=True,
    )
    fills = [step for step in workflow.steps if step.type is ActionType.FILL]
    assert len(fills) == 2  # два fill по #field-name склеены
    assert fills[0].value == "{{name}}"
    assert fills[1].value == "{{email}}"
    submit = workflow.steps[-1]
    assert submit.confirm_required


def test_parse_xlsx_bytes() -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["name", "email"])
    sheet.append(["Иван", "a@b.c"])
    sheet.append(["Мария", "m@x.y"])
    buffer = __import__("io").BytesIO()
    workbook.save(buffer)
    rows = params.parse_rows_xlsx(buffer.getvalue())
    assert len(rows) == 2
    assert rows[0]["name"] == "Иван"
