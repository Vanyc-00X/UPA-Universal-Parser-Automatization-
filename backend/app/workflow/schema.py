"""Схема сценария ввода данных (Этап 7)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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

    В ``value`` и ``url`` допускаются подстановки ``{{column}}`` из строки параметров.
    """

    type: ActionType
    selector: str | None = None
    value: str | None = None
    url: str | None = None
    key: str | None = Field(None, description="Имя переменной для extract / assert")
    timeout_ms: int = Field(5_000, ge=0, le=120_000)
    # Явный флаг: шаг опасный (отправка формы / платёж).
    confirm_required: bool = False
    note: str | None = None

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
        }
        if action in needs and not (value or "").strip():
            raise ValueError(f"для действия {action} нужен selector")
        return value

    def looks_dangerous(self) -> bool:
        if self.confirm_required:
            return True
        if self.type is not ActionType.CLICK:
            return False
        haystack = " ".join(
            part for part in (self.selector or "", self.value or "", self.note or "")
        ).lower()
        return any(hint in haystack for hint in DANGEROUS_CLICK_HINTS)


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

    def summary(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "steps": len(self.steps),
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
