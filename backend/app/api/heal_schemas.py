"""Схемы API self-healing (Этап 6)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FieldPatchOut(BaseModel):
    key: str
    title: str
    old_selector: str
    new_selector: str
    reason: str
    matches: int
    source: str
    required: bool = False


class HealProposalOut(BaseModel):
    run_id: str
    scenario_id: str
    snapshot_id: str | None = None
    needed: bool
    coverage: float
    min_coverage: float
    broken_fields: list[str] = Field(default_factory=list)
    patches: list[FieldPatchOut] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    apply_hint: str = "Патч применяется только по явному подтверждению пользователя"


class HealApplyRequest(BaseModel):
    keys: list[str] | None = Field(None, description="Какие поля чинить; пусто — все предложенные")
    change_note: str | None = None


class HealApplyResponse(BaseModel):
    scenario_id: str
    version: int
    applied: list[FieldPatchOut]
    definition: dict[str, Any]


class JournalStepOut(BaseModel):
    name: str
    message: str
    level: str
    duration_ms: int = 0
    details: dict[str, Any] = Field(default_factory=dict)


class RobotsCheckOut(BaseModel):
    url: str
    allowed: bool
    fetched: bool
    robots_url: str
    detail: str
    user_agent: str
