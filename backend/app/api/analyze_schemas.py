"""Схемы API для карты элементов (Этап 2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SelectorOut(BaseModel):
    """Вариант селектора с оценкой устойчивости."""

    selector: str
    kind: str
    score: float


class ElementOut(BaseModel):
    """Описанный элемент страницы."""

    role: str
    label: str
    description: str
    selector: str
    selectors: list[SelectorOut] = Field(default_factory=list)
    selector_quality: float = 0.0
    confidence: float = 0.0
    count: int = 1
    sample: str | None = None
    tag: str = ""
    source: str = "heuristic"
    path: str = ""
    repeat_signature: str | None = None
    attrs: dict[str, str] = Field(default_factory=dict)


class RepeatGroupOut(BaseModel):
    """Найденный список: контейнер и однотипные элементы внутри."""

    count: int = Field(..., description="Полный размер списка на исходной странице")
    items_in_dom: int = Field(..., description="Сколько элементов дошло до обрезанного DOM")
    collapsed: int = Field(0, description="Сколько элементов скрыла обрезка")
    signature: str
    similarity: float
    container_path: str
    container_tag: str
    container_classes: list[str] = Field(default_factory=list)
    sample_text: str | None = None


class LLMInfoOut(BaseModel):
    """Сведения об участии модели в анализе."""

    used: bool = False
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    summary: str | None = None
    detail: str | None = None
    latency_ms: int = 0
    from_cache: bool = False


class AnalyzeRequest(BaseModel):
    """Запрос на анализ снапшота."""

    use_llm: bool = Field(True, description="Уточнять роли локальной моделью, если она доступна")
    force: bool = Field(False, description="Перестроить карту, даже если она уже есть")


class ElementMapOut(BaseModel):
    """Карта элементов страницы."""

    id: str
    snapshot_id: str
    version: int
    elements: list[ElementOut]
    by_role: dict[str, int] = Field(default_factory=dict)
    report: str | None = None
    warnings: list[str] = Field(default_factory=list)
    repeats: list[RepeatGroupOut] = Field(default_factory=list)
    confidence: float | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    prompt_version: str | None = None
    edited_by_user: bool = False
    reused: bool = False
    llm: LLMInfoOut = Field(default_factory=LLMInfoOut)
    page: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ElementMapSummaryOut(BaseModel):
    """Краткие сведения о карте для списков."""

    id: str
    snapshot_id: str
    version: int
    elements_count: int
    confidence: float | None = None
    llm_provider: str | None = None
    edited_by_user: bool = False
    created_at: datetime
    updated_at: datetime


class ElementMapListResponse(BaseModel):
    items: list[ElementMapSummaryOut]
    total: int


class ElementUpdateRequest(BaseModel):
    """Правка одного элемента карты (основа визуального редактора)."""

    role: str | None = None
    label: str | None = None
    description: str | None = None


class RoleInfo(BaseModel):
    """Справочник ролей: какие бывают и как называются."""

    role: str
    label: str
    is_data: bool


class RolesResponse(BaseModel):
    items: list[RoleInfo]


class ReportResponse(BaseModel):
    """Человекочитаемый отчёт о странице."""

    snapshot_id: str
    element_map_id: str
    report: str
    generated_by: Literal["heuristics", "heuristics+llm"]
