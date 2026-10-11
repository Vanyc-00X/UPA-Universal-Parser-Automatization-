"""Схема сценария ввода данных (Этап 7)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ActionType(str, Enum):
    """Поддерживаемые действия воркфлоу."""

    GOTO = "goto"
    FILL = "fill"
    CLICK = "click"
    SELECT = "select"
    CHECK = "check"
    PRESS = "press"
    WAIT_FOR = "wait_for"
    ASSERT_TEXT = "assert_text"
    ASSERT_ELEMENT = "assert_element"
    SCREENSHOT = "screenshot"
    EXTRACT = "extract"
    UPLOAD_FILE = "upload_file"
    LOOP = "loop"
    IF = "if"


# Действия, которые меняют данные на сайте и требуют подтверждения.
DANGEROUS_CLICK_HINTS = (
    "submit",
    "send",
    "оплат",
    "платить",
    "pay",
    "checkout",
    "купить",
    "заказать",
    "удалить",
    "delete",
)


class ActionStep(BaseModel):
    """Один шаг воркфлоу.

    В ``value``, ``url`` и ``path`` допускаются подстановки ``{{column}}``.
    У ``loop``/``if`` дочерние шаги лежат в ``children``.
    """

    type: ActionType
    selector: str | None = None
    value: str | None = None
    url: str | None = None
    path: str | None = Field(None, description="Путь к файлу для upload_file")
    key: str | None = Field(None, description="Имя переменной для extract / assert")
    timeout_ms: int = Field(5_000, ge=0, le=120_000)
    confirm_required: bool = False
    note: str | None = None
    # Условия if: exists:#sel | missing:#sel | text:… | column:name | equals:key=value
    condition: str | None = None
    # loop: либо фиксированное число, либо колонка со списком через запятую.
    loop_times: int | None = Field(None, ge=1, le=500)
    loop_over: str | None = Field(None, description="Колонка CSV для цикла")
    children: list[ActionStep] = Field(default_factory=list)

    @field_validator("selector")
    @classmethod
    def _selector_needed(cls, value: str | None, info: Any) -> str | None:
        action = info.data.get("type")
        needs = {
            ActionType.FILL,
            ActionType.CLICK,
            ActionType.SELECT,
            ActionType.CHECK,
            ActionType.PRESS,
            ActionType.WAIT_FOR,
            ActionType.ASSERT_ELEMENT,
            ActionType.EXTRACT,
            ActionType.UPLOAD_FILE,
        }
        if action in needs and not (value or "").strip():
            raise ValueError(f"для действия {action} нужен selector")
        return value

    @model_validator(mode="after")
    def _check_control_flow(self) -> ActionStep:
        if self.type is ActionType.IF:
            if not (self.condition or "").strip():
                raise ValueError("для if нужно condition")
            if not self.children:
                raise ValueError("для if нужны children")
        if self.type is ActionType.LOOP:
            if not self.children:
                raise ValueError("для loop нужны children")
            if self.loop_times is None and not (self.loop_over or "").strip():
                raise ValueError("для loop укажите loop_times или loop_over")
        if self.type is ActionType.UPLOAD_FILE and not (self.path or self.value or "").strip():
            raise ValueError("для upload_file нужен path или value")
        return self

    def looks_dangerous(self) -> bool:
        if self.confirm_required:
            return True
        if self.type is ActionType.UPLOAD_FILE:
            return False
        if self.type is not ActionType.CLICK:
            # Опасность внутри вложенных шагов учитываем при обходе.
            return any(child.looks_dangerous() for child in self.children)
        haystack = " ".join(
            part for part in (self.selector or "", self.value or "", self.note or "")
        ).lower()
        return any(hint in haystack for hint in DANGEROUS_CLICK_HINTS)

    def count_actions(self) -> int:
        """Считает листовые и управляющие шаги (для лимита max_actions)."""
        total = 1
        for child in self.children:
            total += child.count_actions()
        return total


class WorkflowDefinition(BaseModel):
    """Сценарий ввода: последовательность действий + лимиты-предохранители."""

    url: str
    title: str = "Сценарий ввода"
    description: str | None = None
    steps: list[ActionStep] = Field(default_factory=list)
    max_actions: int = Field(200, ge=1, le=2_000)
    max_rows: int = Field(100, ge=1, le=5_000)
    require_confirm_submit: bool = True
    # В dry-run опасные click пропускаются всегда.
    skip_dangerous_in_dry_run: bool = True

    @field_validator("steps")
    @classmethod
    def _not_empty(cls, value: list[ActionStep]) -> list[ActionStep]:
        if not value:
            raise ValueError("воркфлоу должен содержать хотя бы один шаг")
        return value

    def total_actions(self) -> int:
        return sum(step.count_actions() for step in self.steps)

    def summary(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "steps": len(self.steps),
            "actions": self.total_actions(),
            "dangerous": sum(1 for step in self.steps if step.looks_dangerous()),
            "max_rows": self.max_rows,
        }


class RowResult(BaseModel):
    """Итог прогона одной строки параметров."""

    index: int
    ok: bool
    steps_done: int = 0
    error: str | None = None
    extracted: dict[str, Any] = Field(default_factory=dict)
    skipped: list[str] = Field(default_factory=list)
    log: list[str] = Field(default_factory=list)
    form_errors: list[str] = Field(default_factory=list)


class WorkflowReport(BaseModel):
    """Отчёт по всем строкам."""

    mode: Literal["dry_run", "live"]
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    rows: list[RowResult] = Field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
        }


class RecordedEvent(BaseModel):
    """Событие записи действий пользователя (codegen-подобный режим)."""

    type: Literal[
        "goto",
        "fill",
        "click",
        "select",
        "check",
        "press",
        "upload_file",
        "assert_text",
        "assert_element",
        "extract",
        "wait_for",
        "screenshot",
    ]
    selector: str | None = None
    value: str | None = None
    url: str | None = None
    path: str | None = None
    key: str | None = None
    tag: str | None = None
    text: str | None = None
    name: str | None = None
    input_type: str | None = None
    timestamp_ms: int | None = None
