"""Сервис визуального редактора: черновик сценария, проверка, сохранение.

Работает поверх карты элементов (Этап 2). Пользователь меняет роли и адреса
полей, добавляет собственные, а сервис немедленно проверяет каждую правку на
живом DOM снапшота: «селектор находит 3 узла из 24» — это то, что нужно видеть
сразу, а не выяснять при запуске сбора.

Черновик хранится в базе (``ElementMap.edit_draft``), поэтому правки не теряются
при перезагрузке страницы и перезапуске приложения.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer import service as analyze_service
from app.analyzer.domlite import Document, parse
from app.analyzer.roles import Role
from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.crawler import service as crawl_service
from app.crawler import store
from app.editor import resolver
from app.editor.inspector import build_inspector
from app.editor.schema import (
    ExtractionPlan,
    FieldSpec,
    FieldValidation,
    PaginationKind,
    PaginationSpec,
    ScenarioDefinition,
    ScenarioValidation,
    SelectStrategy,
)
from app.storage.models import ElementMap, Snapshot

log = get_logger(__name__)

# Роль → машинное имя поля. Имена английские: они попадают в CSV и в код.
ROLE_KEYS: dict[str, str] = {
    Role.ITEM_TITLE.value: "title",
    Role.ITEM_PRICE.value: "price",
    Role.ITEM_LINK.value: "url",
    Role.ITEM_IMAGE.value: "image",
    Role.ITEM_DESCRIPTION.value: "description",
    Role.ITEM_LINK.value: "url",
}

# Стратегии извлечения по умолчанию для ролей.
ROLE_STRATEGIES: dict[str, tuple[SelectStrategy, str | None]] = {
    Role.ITEM_LINK.value: (SelectStrategy.ATTRIBUTE, "href"),
    Role.ITEM_IMAGE.value: (SelectStrategy.IMAGE, "src"),
    Role.ITEM_TITLE.value: (SelectStrategy.TEXT, None),
    Role.ITEM_PRICE.value: (SelectStrategy.TEXT, None),
    Role.ITEM_DESCRIPTION.value: (SelectStrategy.TEXT, None),
}

# Роли, из которых имеет смысл собирать данные.
COLLECTABLE_ROLES = {
    Role.ITEM_TITLE.value,
    Role.ITEM_PRICE.value,
    Role.ITEM_LINK.value,
    Role.ITEM_IMAGE.value,
    Role.ITEM_DESCRIPTION.value,
}


@dataclass
class InspectorPayload:
    """Всё, что нужно интерфейсу редактора для отрисовки страницы."""

    snapshot_id: str
    url: str
    title: str | None
    screenshot_url: str | None
    page: dict[str, int] = field(default_factory=dict)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    selectors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "url": self.url,
            "title": self.title,
            "screenshot_url": self.screenshot_url,
            "page": self.page,
            "nodes": self.nodes,
            "total": self.total,
            "selectors": self.selectors,
        }


@dataclass
class EditorState:
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "element_map_id": self.element_map_id,
            "url": self.url,
            "baseline": self.baseline.model_dump(mode="json"),
            "draft": self.draft.model_dump(mode="json"),
            "changed": self.changed,
            "validation": self.validation.model_dump(mode="json"),
            "items_expected": self.items_expected,
            "items_in_dom": self.items_in_dom,
            "collapsed": self.collapsed,
        }


# ---------------------------------------------------------------------------
# Чтение страницы
# ---------------------------------------------------------------------------


async def load_document(
    session: AsyncSession, settings: Settings, snapshot_id: str
) -> tuple[Snapshot, Document]:
    """Отдаёт снапшот и разобранный обрезанный DOM.

    Работаем именно с обрезанным DOM: это то, что видит анализатор и что уходит в
    модель. Пользователь в редакторе должен проверять селекторы на тех же данных.
    """
    snapshot = await crawl_service.get_snapshot(session, snapshot_id)
    html = store.load_text(settings, snapshot_id, store.TRIMMED_HTML)
    if html is None:
        html = store.load_text(settings, snapshot_id, store.PAGE_HTML)
    if html is None:
        raise NotFoundError(
            "Артефакты снапшота не найдены — снимите снапшот заново",
            details={"snapshot_id": snapshot_id},
        )
    return snapshot, parse(html)


async def build_inspector_payload(
    session: AsyncSession,
    settings: Settings,
    snapshot_id: str,
    *,
    max_nodes: int = 400,
) -> InspectorPayload:
    """Собирает данные для инспектора: узлы, рамки и связи с картой."""
    snapshot, document = await load_document(session, settings, snapshot_id)
    record = await analyze_service.require_element_map(session, snapshot_id)
    selectors = [
        str(element.get("selector"))
        for element in (record.elements or [])
        if element.get("selector")
    ]

    html = store.load_text(settings, snapshot_id, store.TRIMMED_HTML) or document.html
    result = build_inspector(html, selectors=selectors, max_nodes=max_nodes)

    artifacts = dict(snapshot.artifacts or {})
    screenshot_url = (
        f"/api/v1/snapshots/{snapshot_id}/artifacts/{store.SCREENSHOT_FULL_PNG}"
        if store.SCREENSHOT_FULL_PNG in artifacts
        else None
    )

    return InspectorPayload(
        snapshot_id=snapshot_id,
        url=snapshot.final_url or snapshot.url,
        title=snapshot.title,
        screenshot_url=screenshot_url,
        page=result.page,
        nodes=[node.as_dict() for node in result.nodes],
        total=result.total,
        selectors=selectors,
    )


# ---------------------------------------------------------------------------
# Черновик: построение, чтение, правка
# ---------------------------------------------------------------------------


def _field_key(role: str, used: set[str]) -> str:
    """Машинное имя поля по роли, с разведением повторов."""
    base = ROLE_KEYS.get(role, re.sub(r"[^a-z0-9_]+", "_", role.lower()).strip("_") or "field")
    key = base
    index = 2
    while key in used:
        key = f"{base}_{index}"
        index += 1
    used.add(key)
    return key


def build_baseline(
    record: ElementMap,
    snapshot: Snapshot,
    *,
    items_expected: int = 0,
) -> ScenarioDefinition:
    """Строит сценарий из карты элементов.

    Это отправная точка для пользователя: он не собирает сценарий с нуля, а
    правит уже готовый. Из карты берутся поля данных, адрес страницы и переход
    по страницам.
    """
    elements: list[dict[str, Any]] = list(record.elements or [])
    fields: list[FieldSpec] = []
    used_keys: set[str] = set()
    container_selector: str | None = None
    next_selector: str | None = None

    for element in elements:
        role = str(element.get("role", ""))
        selector = str(element.get("selector") or "")
        if not selector:
            continue

        if role == Role.LIST_CONTAINER.value and container_selector is None:
            container_selector = selector
            continue
        if role == Role.PAGINATION_NEXT.value and next_selector is None:
            next_selector = selector
            continue
        if role not in COLLECTABLE_ROLES:
            continue

        strategy, attribute = ROLE_STRATEGIES.get(role, (SelectStrategy.TEXT, None))
        fallbacks = [
            str(candidate.get("selector"))
            for candidate in (element.get("selectors") or [])[1:4]
            if candidate.get("selector") and candidate.get("selector") != selector
        ]
        fields.append(
            FieldSpec(
                key=_field_key(role, used_keys),
                title=str(element.get("label") or role),
                selector=selector,
                strategy=strategy,
                attribute=attribute,
                required=role in {Role.ITEM_TITLE.value, Role.ITEM_PRICE.value},
                role=role,
                note=element.get("description"),
                fallback_selectors=fallbacks,
            )
        )

    plan = ExtractionPlan(
        mode="list" if container_selector else "single",
        container_selector=container_selector,
        item_selector=None,
    )

    pagination = PaginationSpec(kind=PaginationKind.NONE)
    if next_selector:
        template = _url_template(snapshot.final_url or snapshot.url)
        pagination = PaginationSpec(
            kind=PaginationKind.URL_TEMPLATE if template else PaginationKind.NEXT_LINK,
            selector=next_selector,
            url_template=template,
            max_pages=10,
        )

    return ScenarioDefinition(
        url=snapshot.final_url or snapshot.url,
        snapshot_id=snapshot.id,
        title=snapshot.title or "Сценарий сбора",
        description=f"Собран из карты элементов снапшота {snapshot.id}",
        plan=plan,
        pagination=pagination,
        fields=fields,
        limits={
            "items_expected": items_expected,
            "dom_items_kept": _items_in_dom(record),
            "source": "element_map",
        },
    )


def _url_template(url: str) -> str | None:
    """Превращает адрес страницы в шаблон с подстановкой номера страницы.

    Если в адресе уже есть параметр страницы, он заменяется на ``{page}``.
    Иначе шаблон не строится: придумывать структуру адреса за сайт нельзя.
    """
    parts = urlsplit(url)
    if not parts.query:
        return None
    params = parse_qsl(parts.query, keep_blank_values=True)
    page_keys = {"page", "p", "pg", "paged", "page_number", "start"}
    found = False
    updated: list[tuple[str, str]] = []
    for name, value in params:
        if name.lower() in page_keys and value.isdigit():
            updated.append((name, "{page}"))
            found = True
        else:
            updated.append((name, value))
    if not found:
        return None
    query = urlencode(updated, safe="{page}")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _items_in_dom(record: ElementMap) -> int:
    """Сколько записей реально осталось в обрезанном DOM.

    Поле ``count`` в карте — это **полный** размер списка на исходной странице.
    Число оставшихся в DOM лежит рядом (``items_in_dom``) или вычисляется как
    ``count - collapsed``. Пользователь редактора должен видеть оба числа: по ним
    понятно, почему селектор находит три узла из двенадцати.
    """
    for element in record.elements or []:
        if element.get("role") != Role.LIST_CONTAINER.value:
            continue
        if element.get("items_in_dom") is not None:
            return int(element["items_in_dom"])
        total = int(element.get("count") or 0)
        collapsed = int(element.get("collapsed") or 0)
        return max(total - collapsed, 0)
    return 0


def _marker_total(document: Document) -> int:
    """Полный размер списка, сохранённый обрезкой DOM."""
    from app.analyzer.domlite import marker_counts

    counts = marker_counts(document.html)
    return max(counts) if counts else 0


def draft_from_record(record: ElementMap, baseline: ScenarioDefinition) -> ScenarioDefinition:
    """Черновик из базы, если он есть; иначе — базовая версия."""
    raw = record.edit_draft
    if not raw:
        return baseline
    try:
        return ScenarioDefinition.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 — повреждённый черновик не должен ломать редактор
        log.warning("editor.draft_unreadable", reason=str(exc)[:200])
        return baseline


async def get_state(session: AsyncSession, settings: Settings, snapshot_id: str) -> EditorState:
    """Текущее состояние редактора: базовый сценарий, черновик и проверка."""
    snapshot, document = await load_document(session, settings, snapshot_id)
    record = await analyze_service.require_element_map(session, snapshot_id)

    expected = _marker_total(document)
    baseline = build_baseline(record, snapshot, items_expected=expected)
    draft = draft_from_record(record, baseline)
    in_dom = int(baseline.limits.get("dom_items_kept", 0) or 0)
    validation = validate_definition(document, draft, items_expected=expected, items_in_dom=in_dom)

    return EditorState(
        snapshot_id=snapshot_id,
        element_map_id=record.id,
        url=snapshot.final_url or snapshot.url,
        baseline=baseline,
        draft=draft,
        changed=_differs(baseline, draft),
        validation=validation,
        items_expected=expected,
        items_in_dom=in_dom,
        collapsed=max(expected - in_dom, 0),
    )


def _differs(baseline: ScenarioDefinition, draft: ScenarioDefinition) -> bool:
    """Отличается ли черновик от базового сценария."""
    return baseline.model_dump(mode="json") != draft.model_dump(mode="json")


async def save_draft(
    session: AsyncSession,
    settings: Settings,
    snapshot_id: str,
    draft: ScenarioDefinition,
) -> EditorState:
    """Сохраняет черновик в базу и возвращает обновлённое состояние."""
    record = await analyze_service.require_element_map(session, snapshot_id)
    record.edit_draft = draft.model_dump(mode="json")
    record.edited_by_user = True
    await session.flush()
    log.info("editor.draft_saved", snapshot_id=snapshot_id, fields=len(draft.fields))
    return await get_state(session, settings, snapshot_id)


@dataclass
class SavedScenario:
    """Результат сохранения черновика как сценария."""

    scenario: Any
    version: Any
    definition: ScenarioDefinition


async def build_scenario(
    session: AsyncSession,
    settings: Settings,
    snapshot_id: str,
    *,
    name: str,
    description: str | None = None,
    change_note: str | None = None,
    scenario_id: str | None = None,
) -> SavedScenario:
    """Сохраняет текущий черновик как сценарий и его версию.

    Проверка селекторов уже выполнена при чтении состояния, поэтому здесь
    остаётся только запись. Название и описание подставляются в определение:
    сценарий должен быть самодостаточным документом.
    """
    from app.editor import scenario as scenario_service

    state = await get_state(session, settings, snapshot_id)
    snapshot = await session.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise NotFoundError("Снапшот не найден", details={"snapshot_id": snapshot_id})

    definition = state.draft.model_copy(
        update={
            "title": name,
            "description": description or state.draft.description,
        }
    )
    scenario, version = await scenario_service.save_scenario(
        session,
        definition,
        name=name,
        site_id=snapshot.site_id,
        description=description,
        change_note=change_note,
        scenario_id=scenario_id,
    )
    return SavedScenario(scenario=scenario, version=version, definition=definition)


async def reset_draft(session: AsyncSession, settings: Settings, snapshot_id: str) -> EditorState:
    """Откатывает черновик к базовому сценарию."""
    record = await analyze_service.require_element_map(session, snapshot_id)
    record.edit_draft = None
    await session.flush()
    log.info("editor.draft_reset", snapshot_id=snapshot_id)
    return await get_state(session, settings, snapshot_id)


async def mutate_fields(
    session: AsyncSession,
    settings: Settings,
    snapshot_id: str,
    *,
    action: str,
    field: FieldSpec | None = None,
    key: str | None = None,
    order: list[str] | None = None,
) -> EditorState:
    """Меняет набор полей черновика: добавить, изменить, удалить, упорядочить."""
    state = await get_state(session, settings, snapshot_id)
    draft = state.draft
    fields = list(draft.fields)

    if action == "add":
        if field is None:
            raise ValidationError("Не передано описание поля")
        if any(item.key == field.key for item in fields):
            raise ValidationError("Поле с таким именем уже есть", details={"key": field.key})
        fields.append(field)
    elif action == "update":
        if field is None:
            raise ValidationError("Не передано описание поля")
        position = next((i for i, item in enumerate(fields) if item.key == field.key), None)
        if position is None:
            raise NotFoundError("Поле не найдено", details={"key": field.key})
        fields[position] = field
    elif action == "remove":
        if not key:
            raise ValidationError("Не передано имя поля")
        remaining = [item for item in fields if item.key != key]
        if len(remaining) == len(fields):
            raise NotFoundError("Поле не найдено", details={"key": key})
        fields = remaining
    elif action == "order":
        if not order:
            raise ValidationError("Не передан порядок полей")
        by_key = {item.key: item for item in fields}
        missing = [item for item in order if item not in by_key]
        if missing:
            raise NotFoundError("Неизвестные поля в порядке", details={"keys": missing})
        extra = [item.key for item in fields if item.key not in order]
        fields = [by_key[item] for item in order] + [by_key[item] for item in extra]
    else:
        raise ValidationError("Неизвестное действие", details={"action": action})

    updated = draft.model_copy(update={"fields": fields})
    return await save_draft(session, settings, snapshot_id, updated)


# ---------------------------------------------------------------------------
# Проверка селекторов
# ---------------------------------------------------------------------------


def validate_definition(
    document: Document,
    definition: ScenarioDefinition,
    *,
    items_expected: int = 0,
    items_in_dom: int = 0,
) -> ScenarioValidation:
    """Проверяет каждый селектор сценария на живом DOM.

    Статусы:

    * ``ok`` — селектор нашёл все записи, которые физически есть на странице;
    * ``partial`` — нашёл меньше, чем доступно: часть записей потеряется;
    * ``empty`` — не находит ничего: сценарий в таком виде не сработает;
    * ``invalid`` — селектор не поддерживается.

    ``items_in_dom`` важен, потому что обрезка DOM оставляет несколько
    показательных карточек: требовать от селектора 24 совпадения там, где в
    разметке осталось три, — значит ругаться на исправный сценарий.
    """
    validations: list[FieldValidation] = []
    problems: list[str] = []
    warnings: list[str] = []

    for spec in definition.fields:
        report = resolver.resolve(document.root, spec.selector)
        expected = items_expected if definition.plan.mode == "list" else 1
        # Если обрезка DOM удалила часть записей, селектор физически не может
        # найти больше. Такой результат — рабочий, а не «частичный».
        available = min(expected, items_in_dom) if items_in_dom else expected

        if not report.valid:
            status = "invalid"
            problems.append(f"Поле «{spec.title}»: {report.error}")
        elif report.count == 0:
            status = "empty"
            problems.append(f"Поле «{spec.title}»: селектор не находит элементов")
        elif expected > 1 and report.count < min(expected, available):
            status = "partial"
            warnings.append(
                f"Поле «{spec.title}»: найдено {report.count} из {expected} записей "
                f"(остальные скрыты обрезкой DOM)"
            )
        else:
            status = "ok"

        sample = None
        if report.nodes:
            first = report.nodes[0]
            if spec.strategy is SelectStrategy.ATTRIBUTE and spec.attribute:
                sample = first.get(spec.attribute) or None
            elif spec.strategy is SelectStrategy.IMAGE:
                sample = first.get("src") or first.get("data-src") or None
            else:
                sample = first.all_text(limit=80) or None

        validations.append(
            FieldValidation(
                key=spec.key,
                title=spec.title,
                selector=spec.selector,
                valid=report.valid,
                matches=report.count,
                expected=expected,
                coverage=round(report.count / expected, 3) if expected else 0.0,
                sample=sample,
                error=report.error,
                status=status,  # type: ignore[arg-type]
            )
        )

    if definition.plan.mode == "list":
        if not definition.plan.container_selector and not definition.plan.item_selector:
            problems.append("Не задан контейнер списка: неизвестно, откуда брать записи")
        elif definition.plan.container_selector:
            container = resolver.resolve(document.root, definition.plan.container_selector)
            if not container.valid:
                problems.append(f"Контейнер списка: {container.error}")
            elif container.count == 0:
                problems.append("Контейнер списка не найден на странице")

    if definition.plan.mode == "api":
        if not definition.plan.records_path:
            problems.append(
                "Режим XHR/JSON: укажите путь к списку записей (records_path), например data.items"
            )
        # api_url необязателен: UPA сама выберет самый богатый JSON из network.

    if definition.pagination.kind is not PaginationKind.NONE:
        pagination = definition.pagination
        if pagination.kind is PaginationKind.NEXT_LINK and not pagination.selector:
            problems.append("Переход по страницам выбран, но селектор кнопки не задан")
        elif pagination.kind is PaginationKind.NEXT_LINK and pagination.selector:
            report = resolver.resolve(document.root, pagination.selector)
            if report.count == 0:
                problems.append("Селектор перехода по страницам ничего не находит")
        if pagination.kind is PaginationKind.URL_TEMPLATE and not pagination.url_template:
            problems.append("Выбран шаблон адреса, но сам шаблон не задан")

    if not definition.fields:
        problems.append("В сценарии нет ни одного поля: собирать будет нечего")

    return ScenarioValidation(
        ok=not problems,
        fields=validations,
        problems=problems,
        warnings=warnings,
    )


def resolve_selector(snapshot_html: str, selector: str) -> dict[str, Any]:
    """Проверка одного произвольного селектора — для панели редактора."""
    document = parse(snapshot_html)
    return resolver.resolve(document.root, selector).as_dict()


def parse_html_for_validation(html: str) -> Document:
    """Разбирает HTML для проверки сценария без базы и снапшота."""
    return parse(html)


def suggest_key(title: str, used: set[str]) -> str:
    """Предлагает машинное имя для нового поля по его названию."""
    transliteration = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "c",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
    lowered = title.strip().lower()
    transliterated = "".join(transliteration.get(char, char) for char in lowered)
    slug = re.sub(r"[^a-z0-9]+", "_", transliterated).strip("_")
    if not slug:
        slug = "field"
    if slug[0].isdigit():
        slug = f"f_{slug}"
    key = slug
    index = 2
    while key in used:
        key = f"{slug}_{index}"
        index += 1
    used.add(key)
    return key
