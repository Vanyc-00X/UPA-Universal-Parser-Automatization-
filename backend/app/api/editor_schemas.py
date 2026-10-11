"""Схемы API визуального редактора (Этап 3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.editor.schema import (
    FieldSpec,
    PaginationSpec,
    ScenarioDefinition,
    ScenarioValidation,
    SelectStrategy,
)


class BoxOut(BaseModel):
    """Оценка положения элемента на странице."""

    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


class InspectNodeOut(BaseModel):
    """Узел страницы в инспекторе."""

    node_id: str
    tag: str
    role: str
    label: str
    text: str = ""
    selector: str = ""
    path: str = ""
    depth: int = 0
    parent_id: str | None = None
    children_ids: list[str] = Field(default_factory=list)
    classes: list[str] = Field(default_factory=list)
    attrs: dict[str, str] = Field(default_factory=dict)
    hidden: bool = False
    box: BoxOut = Field(default_factory=BoxOut)
    matched_by: list[str] = Field(default_factory=list)


class InspectorResponse(BaseModel):
    """Данные для отрисовки страницы в редакторе."""

    snapshot_id: str
    url: str
    title: str | None = None
    screenshot_url: str | None = Field(
        None, description="Ссылка на полный скриншот страницы для подсветки элементов"
    )
    page: dict[str, int] = Field(default_factory=dict)
    nodes: list[InspectNodeOut] = Field(default_factory=list)
    total: int = 0
    selectors: list[str] = Field(default_factory=list)


class MatchSampleOut(BaseModel):
    """Пример найденного узла."""

    tag: str
    text: str = ""
    path: str = ""
    classes: list[str] = Field(default_factory=list)
    hidden: bool = False


class SelectorReportOut(BaseModel):
    """Результат проверки селектора."""

    selector: str
    valid: bool
    count: int
    visible_count: int
    unique: bool
    error: str | None = None
    samples: list[MatchSampleOut] = Field(default_factory=list)


class SelectorTestRequest(BaseModel):
    """Запрос проверки селектора."""

    selector: str = Field(..., description="CSS-селектор для проверки")
    snapshot_id: str | None = Field(
        None, description="Если не указан, используется снапшот из пути"
    )


class EditorStateResponse(BaseModel):
    """Состояние редактора: базовый сценарий, черновик и проверка."""

    snapshot_id: str
    element_map_id: str
    url: str
    baseline: ScenarioDefinition
    draft: ScenarioDefinition
    changed: bool
    validation: ScenarioValidation
    items_expected: int = 0
    items_in_dom: int = 0
    collapsed: int = 0


class DraftUpdateRequest(BaseModel):
    """Полная замена черновика."""

    definition: ScenarioDefinition


class FieldAddRequest(BaseModel):
    """Добавление поля в черновик."""

    title: str = Field(..., min_length=1, description="Название поля для интерфейса")
    selector: str = Field(..., min_length=1, description="CSS-селектор значения")
    key: str | None = Field(None, description="Машинное имя; по умолчанию выводится из названия")
    strategy: SelectStrategy = SelectStrategy.TEXT
    attribute: str | None = None
    required: bool = False
    role: str | None = None
    note: str | None = None
    fallback_selectors: list[str] = Field(default_factory=list)


class FieldUpdateRequest(BaseModel):
    """Изменение существующего поля."""

    key: str = Field(..., min_length=1, description="Имя изменяемого поля")
    title: str | None = None
    selector: str | None = None
    strategy: SelectStrategy | None = None
    attribute: str | None = None
    required: bool | None = None
    note: str | None = None
    fallback_selectors: list[str] | None = None


class FieldRemoveRequest(BaseModel):
    """Удаление поля."""

    key: str


class FieldOrderRequest(BaseModel):
    """Порядок полей."""

    order: list[str]


class PlanUpdateRequest(BaseModel):
    """Изменение плана извлечения и пагинации."""

    plan_mode: Literal["list", "single", "api", "llm"] | None = None
    container_selector: str | None = None
    item_selector: str | None = None
    api_url: str | None = None
    pagination: PaginationSpec | None = None


class SuggestKeyResponse(BaseModel):
    """Предложенное машинное имя поля."""

    key: str


class ScenarioSavedResponse(BaseModel):
    """Результат сохранения сценария."""

    scenario_id: str
    site_id: str
    scenario_name: str
    version: int
    fields: int
    definition: ScenarioDefinition


class FieldPreviewOut(BaseModel):
    """Предпросмотр значений поля на текущей странице."""

    key: str
    matches: int
    values: list[str] = Field(default_factory=list)
    error: str | None = None


class PreviewResponse(BaseModel):
    """Предпросмотр первых записей сценария."""

    snapshot_id: str
    mode: str
    items_in_dom: int
    fields: list[FieldPreviewOut] = Field(default_factory=list)


class FieldSpecOut(FieldSpec):
    """Поле сценария в ответах списка."""


class ElementAddRequest(BaseModel):
    """Поле, добавленное по выбранному в инспекторе элементу."""

    node_id: str | None = Field(None, description="Идентификатор узла из инспектора")
    selector: str | None = Field(None, description="Готовый селектор вместо узла")
    title: str | None = None
    key: str | None = None
    strategy: SelectStrategy = SelectStrategy.TEXT
    attribute: str | None = None
    required: bool = False
    note: str | None = None
