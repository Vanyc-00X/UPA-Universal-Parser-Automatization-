"""Журнал шагов запуска — чтобы понять причину любого падения."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

StepLevel = Literal["info", "warn", "error"]


@dataclass
class JournalStep:
    """Один шаг выполнения сценария."""

    name: str
    message: str
    level: StepLevel = "info"
    duration_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "message": self.message,
            "level": self.level,
            "duration_ms": self.duration_ms,
            "details": self.details,
        }


@dataclass
class RunJournal:
    """Накопленный журнал запуска."""

    steps: list[JournalStep] = field(default_factory=list)
    _started: dict[str, float] = field(default_factory=dict, repr=False)

    def start(self, name: str) -> None:
        self._started[name] = time.monotonic()

    def add(
        self,
        name: str,
        message: str,
        *,
        level: StepLevel = "info",
        details: dict[str, Any] | None = None,
        finish_timer: bool = False,
    ) -> JournalStep:
        duration = 0
        if finish_timer and name in self._started:
            duration = int((time.monotonic() - self._started.pop(name)) * 1000)
        step = JournalStep(
            name=name,
            message=message,
            level=level,
            duration_ms=duration,
            details=details or {},
        )
        self.steps.append(step)
        return step

    def error(self, name: str, message: str, **details: Any) -> JournalStep:
        return self.add(name, message, level="error", details=details, finish_timer=True)

    def warn(self, name: str, message: str, **details: Any) -> JournalStep:
        return self.add(name, message, level="warn", details=details, finish_timer=True)

    def info(self, name: str, message: str, **details: Any) -> JournalStep:
        return self.add(name, message, level="info", details=details, finish_timer=True)

    def as_list(self) -> list[dict[str, Any]]:
        return [step.as_dict() for step in self.steps]
