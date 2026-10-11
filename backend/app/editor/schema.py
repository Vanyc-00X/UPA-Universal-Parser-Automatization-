"""Схема сценария: что и откуда собирать.

Сценарий — главный артефакт UPA. Он переживает правки вёрстки, версионируется и
служит входом для движка извлечения (Этап 4). Всё, что делает пользователь в
визуальном редакторе (Этап 3), сводится к формированию этого документа.

Схема описана строго (Pydantic): благодаря этому выход сценария всегда валиден, а
данные можно сразу отдавать в код или базу без ручной чистки.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class SelectStrategy(str, Enum):
    """Как получать значение поля."""

    TEXT = "text"  # весь текст элемента
    OWN_TEXT = "own_text"  # только собственный текст, без вложенных
    ATTRIBUTE = "attribute"  # значение атрибута (href, src, data-price)
    HTML = "html"  # внутренняя разметка — для составных блоков
    IMAGE = "image"  # ссылка на изображение
    COUNT = "count"  # количество найденных узлов


class PaginationKind(str, Enum):
    """Способ перехода к следующей странице."""

    NONE = "none"
    NEXT_LINK = "next_link"  # кнопка или ссылка «далее»
    URL_TEMPLATE = "url_template"  # шаблон вида /catalog?page={page}
    SCROLL = "scroll"  # бесконечный скролл
    LOAD_MORE = "load_more"  # кнопка «показать ещё»


class ExtractionPlan(BaseModel):
    """Откуда брать данные на одной странице."""

    mode: Literal["list", "single", "api", "llm"] = Field(
        "list",
        description="list — HTML-список, single — одна HTML-запись, "
        "api — из XHR/JSON снапшота, llm — моделью по очищенному HTML",
    )
    # Селектор контейнера списка или корневого блока записи.
    container_selector: str | None = None
    # Селектор повторов: если задан, контейнер вычисляется как родитель совпадений.
    item_selector: str | None = None
    # Адрес JSON-источника для режима api (подстрока URL из network).
    api_url: str | None = None
    api_method: str = "GET"
    # Путь к массиву записей в JSON, например data.items или results[*].
    records_path: str | None = Field(
        None,
        description="JSON-путь к списку записей для mode=api (например data.items)",
    )


class PaginationSpec(BaseModel):
    """Правила обхода страниц."""

    kind: PaginationKind = PaginationKind.NONE
    selector: str | None = Field(None, description="Селектор кнопки или ссылки «далее»")
    url_template: str | None = Field(
        None, description="Шаблон адреса, например https://site/catalog?page={page}"
    )
    start_page: int = 1
    max_pages: int = Field(10, ge=1, le=1000)
    delay_ms: int = Field(700, ge=0, le=60_000, description="Пауза между страницами")

    @field_validator("url_template")
    @classmethod
    def _check_template(cls, value: str | None) -> str | None:
        if value and "{page}" not in value:
            raise ValueError("в шаблон адреса нужно добавить {page}")
        return value


class FieldSpec(BaseModel):
    """Одно поле сценария: понятное имя плюс адрес значения."""

    key: str = Field(..., description="Машинное имя поля, например title")
    title: str = Field(..., description="Человекочитаемое название для интерфейса")
    selector: str = Field(..., description="CSS-селектор значения")
    strategy: SelectStrategy = SelectStrategy.TEXT
    attribute: str | None = Field(None, description="Имя атрибута для strategy=attribute")
    # Необязательные правила обработки.
    required: bool = False
    role: str | None = Field(None, description="Роль элемента из карты, если известна")
    note: str | None = None
    # Запасные адреса: пригодится самопочинке на Этапе 6.
    fallback_selectors: list[str] = Field(default_factory=list)

    @field_validator("key")
    @classmethod
    def _check_key(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("имя поля не может быть пустым")
        if not all(char.isalnum() or char in "_-" for char in cleaned):
            raise ValueError("имя поля может содержать только буквы, цифры, _ и -")
        return cleaned

    @field_validator("attribute")
    @classmethod
    def _check_attribute(cls, value: str | None, info: Any) -> str | None:
        strategy = info.data.get("strategy")
        if strategy == SelectStrategy.ATTRIBUTE and not value:
            raise ValueError("для strategy=attribute нужно указать имя атрибута")
        return value


class ScenarioDefinition(BaseModel):
    """Полное описание сценария — то, что хранится в версии."""

    url: str = Field(..., description="Адрес страницы, с которой снимался снапшот")
    snapshot_id: str | None = None
    title: str = Field("Без названия", description="Название сценария")
    description: str | None = None
    plan: ExtractionPlan = Field(default_factory=ExtractionPlan)
    pagination: PaginationSpec = Field(default_factory=PaginationSpec)
    fields: list[FieldSpec] = Field(default_factory=list)
    # Служебное: какие ограничения и допущения известны.
    limits: dict[str, Any] = Field(default_factory=dict)
    created_from: Literal["editor", "template", "import"] = "editor"

    @field_validator("fields")
    @classmethod
    def _check_fields(cls, value: list[FieldSpec]) -> list[FieldSpec]:
        keys = [field.key for field in value]
        duplicates = {key for key in keys if keys.count(key) > 1}
        if duplicates:
            raise ValueError(f"повторяющиеся имена полей: {sorted(duplicates)}")
        return value

    @property
    def required_fields(self) -> list[FieldSpec]:
        return [field for field in self.fields if field.required]

    def summary(self) -> dict[str, Any]:
        """Краткая сводка для списков и логов."""
        return {
            "title": self.title,
            "url": self.url,
            "mode": self.plan.mode,
            "fields": len(self.fields),
            "required": len(self.required_fields),
            "pagination": self.pagination.kind.value,
            "max_pages": self.pagination.max_pages,
        }


class FieldValidation(BaseModel):
    """Результат проверки одного поля на живом DOM."""

    key: str
    title: str
    selector: str
    valid: bool
    matches: int = Field(0, description="Сколько узлов находит селектор в обрезанном DOM")
    expected: int = Field(0, description="Сколько записей ожидается по карте элементов")
    coverage: float = Field(0.0, description="Доля совпавших записей: matches / expected")
    sample: str | None = None
    error: str | None = None
    status: Literal["ok", "partial", "empty", "invalid"] = "ok"

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()


class ScenarioValidation(BaseModel):
    """Проверка всего сценария перед сохранением."""

    ok: bool
    fields: list[FieldValidation] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def ready_fields(self) -> list[FieldValidation]:
        return [field for field in self.fields if field.status == "ok"]

    def summary(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "fields": len(self.fields),
            "ok_fields": len(self.ready_fields),
            "problems": len(self.problems),
            "warnings": len(self.warnings),
        }


class ScenarioOut(BaseModel):
    """Сценарий в API."""

    id: str
    site_id: str
    name: str
    description: str | None = None
    kind: str
    is_active: bool
    current_version: int
    definition: ScenarioDefinition | None = None
    created_at: datetime
    updated_at: datetime


class ScenarioVersionOut(BaseModel):
    """Версия сценария."""

    id: str
    scenario_id: str
    version: int
    definition: ScenarioDefinition
    change_note: str | None = None
    created_by: str
    created_at: datetime


class ScenarioListResponse(BaseModel):
    items: list[ScenarioOut]
    total: int


class SaveScenarioRequest(BaseModel):
    """Сохранение черновика редактора как версии сценария."""

    name: str = Field(..., min_length=1, max_length=256)
    description: str | None = None
    change_note: str | None = Field(None, description="Что изменилось в этой версии")
    scenario_id: str | None = Field(
        None, description="Если задан — добавляется новая версия существующего сценария"
    )
