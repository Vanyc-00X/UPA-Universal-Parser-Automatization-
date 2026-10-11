"""Эндпоинты визуального редактора (Этап 3).

Редактор — это диалог: пользователь правит поле и немедленно видит, сколько узлов
находит его селектор. Поэтому почти каждый эндпоинт возвращает полное состояние
(черновик плюс проверку), а не только подтверждение.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer import service as analyze_service
from app.analyzer.roles import Role, label_for
from app.api.editor_schemas import (
    DraftUpdateRequest,
    EditorStateResponse,
    ElementAddRequest,
    FieldAddRequest,
    FieldOrderRequest,
    FieldPreviewOut,
    FieldUpdateRequest,
    InspectorResponse,
    PlanUpdateRequest,
    PreviewResponse,
    ScenarioSavedResponse,
    SelectorReportOut,
    SelectorTestRequest,
    SuggestKeyResponse,
)
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import ValidationError
from app.crawler import store
from app.editor import scenario as scenario_service
from app.editor import service as editor
from app.editor.inspector import assign_ids
from app.editor.schema import (
    ExtractionPlan,
    FieldSpec,
    PaginationSpec,
    SaveScenarioRequest,
    ScenarioDefinition,
    ScenarioListResponse,
    ScenarioVersionOut,
    SelectStrategy,
)

router = APIRouter(tags=["editor"])


def _settings(request: Request) -> Settings:
    return request.app.state.settings


async def _state(
    session: AsyncSession, settings: Settings, snapshot_id: str
) -> EditorStateResponse:
    """Состояние редактора в виде ответа API."""
    state = await editor.get_state(session, settings, snapshot_id)
    return EditorStateResponse(**state.as_dict())


# ---------------------------------------------------------------------------
# Инспектор и проверка селекторов
# ---------------------------------------------------------------------------


@router.get(
    "/snapshots/{snapshot_id}/inspector",
    response_model=InspectorResponse,
    summary="Дерево элементов страницы для визуального редактора",
    description=(
        "Отдаёт список узлов снапшота с оценкой положения на странице, а также "
        "скриншот: по ним фронтенд рисует подсветку элементов и позволяет выбрать "
        "нужный мышью."
    ),
)
async def get_inspector(
    snapshot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    max_nodes: int = Query(400, ge=20, le=2000),
) -> InspectorResponse:
    payload = await editor.build_inspector_payload(
        db, _settings(request), snapshot_id, max_nodes=max_nodes
    )
    return InspectorResponse(**payload.as_dict())


@router.post(
    "/snapshots/{snapshot_id}/element-selector",
    response_model=SelectorReportOut,
    summary="Проверить селектор на странице снапшота",
    description=(
        "Возвращает число найденных узлов и примеры. Незаменимо при ручном подборе: "
        "сразу видно, что селектор находит 3 узла из 24."
    ),
)
async def test_selector(
    snapshot_id: str,
    payload: SelectorTestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SelectorReportOut:
    settings = _settings(request)
    await analyze_service.require_element_map(db, snapshot_id)
    html = store.load_text(settings, snapshot_id, store.TRIMMED_HTML)
    if html is None:
        html = store.load_text(settings, snapshot_id, store.PAGE_HTML)
    if html is None:
        raise ValidationError("Артефакты снапшота не найдены", details={"snapshot_id": snapshot_id})
    report = editor.resolve_selector(html, payload.selector)
    return SelectorReportOut(**report)


# ---------------------------------------------------------------------------
# Черновик сценария
# ---------------------------------------------------------------------------


@router.get(
    "/snapshots/{snapshot_id}/draft",
    response_model=EditorStateResponse,
    summary="Черновик сценария и результат его проверки",
)
async def get_draft(
    snapshot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EditorStateResponse:
    return await _state(db, _settings(request), snapshot_id)


@router.put(
    "/snapshots/{snapshot_id}/draft",
    response_model=EditorStateResponse,
    summary="Заменить черновик целиком",
)
async def put_draft(
    snapshot_id: str,
    payload: DraftUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EditorStateResponse:
    # Определение приходит как обычный словарь, поэтому проверяем его сами: иначе
    # ошибка в данных превратилась бы в 500 вместо понятного 422.
    try:
        definition = ScenarioDefinition.model_validate(payload.definition)
    except Exception as exc:  # noqa: BLE001 — ошибки валидации pydantic
        raise ValidationError(
            "Определение сценария заполнено неверно",
            details={"reason": _first_error(exc)},
        ) from exc

    state = await editor.save_draft(db, _settings(request), snapshot_id, definition)
    return EditorStateResponse(**state.as_dict())


def _first_error(exc: Exception) -> str:
    """Первое понятное сообщение об ошибке валидации."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            items = errors()
        except Exception:  # noqa: BLE001
            items = []
        if items:
            first = items[0]
            location = ".".join(str(part) for part in first.get("loc", ()))
            return f"{location}: {first.get('msg', 'неверное значение')}"
    return str(exc)[:300]


@router.post(
    "/snapshots/{snapshot_id}/draft/reset",
    response_model=EditorStateResponse,
    summary="Откатить черновик к базовому сценарию",
)
async def reset_draft(
    snapshot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EditorStateResponse:
    state = await editor.reset_draft(db, _settings(request), snapshot_id)
    return EditorStateResponse(**state.as_dict())


@router.post(
    "/snapshots/{snapshot_id}/draft/suggest-key",
    response_model=SuggestKeyResponse,
    summary="Предложить машинное имя поля",
    description="Транслитерирует русское название в латиницу — имена полей попадают в CSV.",
)
async def suggest_key(
    snapshot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    title: str = Query(..., min_length=1),
) -> SuggestKeyResponse:
    state = await editor.get_state(db, _settings(request), snapshot_id)
    used = {item.key for item in state.draft.fields}
    return SuggestKeyResponse(key=editor.suggest_key(title, used))


# ---------------------------------------------------------------------------
# Поля
# ---------------------------------------------------------------------------


@router.post(
    "/snapshots/{snapshot_id}/draft/fields",
    response_model=EditorStateResponse,
    summary="Добавить поле в черновик",
)
async def add_field(
    snapshot_id: str,
    payload: FieldAddRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EditorStateResponse:
    state = await editor.get_state(db, _settings(request), snapshot_id)
    used = {item.key for item in state.draft.fields}
    key = payload.key or editor.suggest_key(payload.title, used)

    try:
        field = FieldSpec(
            key=key,
            title=payload.title,
            selector=payload.selector,
            strategy=payload.strategy,
            attribute=payload.attribute,
            required=payload.required,
            role=payload.role,
            note=payload.note,
            fallback_selectors=payload.fallback_selectors,
        )
    except Exception as exc:  # noqa: BLE001 — ошибки валидации pydantic
        raise ValidationError("Поле заполнено неверно", details={"reason": str(exc)[:300]}) from exc

    result = await editor.mutate_fields(
        db, _settings(request), snapshot_id, action="add", field=field
    )
    return EditorStateResponse(**result.as_dict())


@router.patch(
    "/snapshots/{snapshot_id}/draft/fields",
    response_model=EditorStateResponse,
    summary="Изменить поле черновика",
)
async def update_field(
    snapshot_id: str,
    payload: FieldUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EditorStateResponse:
    settings = _settings(request)
    state = await editor.get_state(db, settings, snapshot_id)
    current = next((item for item in state.draft.fields if item.key == payload.key), None)
    if current is None:
        raise ValidationError("Поле не найдено", details={"key": payload.key})

    updated = current.model_copy(
        update={
            key: value
            for key, value in payload.model_dump(exclude_none=True).items()
            if key != "key"
        }
    )
    result = await editor.mutate_fields(db, settings, snapshot_id, action="update", field=updated)
    return EditorStateResponse(**result.as_dict())


@router.delete(
    "/snapshots/{snapshot_id}/draft/fields/{key}",
    response_model=EditorStateResponse,
    summary="Удалить поле из черновика",
)
async def remove_field(
    snapshot_id: str,
    key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EditorStateResponse:
    result = await editor.mutate_fields(
        db, _settings(request), snapshot_id, action="remove", key=key
    )
    return EditorStateResponse(**result.as_dict())


@router.post(
    "/snapshots/{snapshot_id}/draft/order",
    response_model=EditorStateResponse,
    summary="Изменить порядок полей",
)
async def order_fields(
    snapshot_id: str,
    payload: FieldOrderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EditorStateResponse:
    result = await editor.mutate_fields(
        db, _settings(request), snapshot_id, action="order", order=payload.order
    )
    return EditorStateResponse(**result.as_dict())


@router.post(
    "/snapshots/{snapshot_id}/draft/fields/from-element",
    response_model=EditorStateResponse,
    summary="Добавить поле по выбранному элементу страницы",
    description=(
        "Пользователь выбирает блок в инспекторе, UPA предлагает название и "
        "селектор — это основной способ ручного добавления полей."
    ),
)
async def add_field_from_element(
    snapshot_id: str,
    payload: ElementAddRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EditorStateResponse:
    settings = _settings(request)
    snapshot, document = await editor.load_document(db, settings, snapshot_id)

    selector = payload.selector
    node = None
    if payload.node_id:
        mapping = assign_ids(document.root)
        node = mapping.get(payload.node_id)
        if node is None:
            raise ValidationError(
                "Узел не найден на странице", details={"node_id": payload.node_id}
            )
        selector = selector or node.css_path()
    if not selector:
        raise ValidationError("Нужно передать идентификатор узла или селектор")

    if node is None:
        # Селектор передан напрямую: находим первый подходящий узел, чтобы понять
        # тег и атрибуты. Без этого ссылка получила бы стратегию «текст».
        from app.editor import resolver

        report = resolver.resolve(document.root, selector)
        if not report.valid:
            raise ValidationError(
                "Селектор не поддерживается", details={"selector": selector, "error": report.error}
            )
        if not report.nodes:
            raise ValidationError(
                "Селектор не находит элементов на странице",
                details={"selector": selector},
            )
        node = report.nodes[0]

    title = payload.title
    if title is None:
        from app.analyzer.roles import guess_roles

        roles = guess_roles(node)
        role = roles[0] if roles else Role.UNKNOWN
        title = label_for(role)
        text = node.all_text(limit=40)
        # Если роль не определилась, но у элемента есть текст — он и есть название.
        if role is Role.UNKNOWN and text:
            title = text
    if title is None:
        title = "Новое поле"

    state = await editor.get_state(db, settings, snapshot_id)
    used = {item.key for item in state.draft.fields}
    key = payload.key or editor.suggest_key(title, used)

    strategy = payload.strategy
    attribute = payload.attribute
    if strategy is SelectStrategy.TEXT:
        # Догадка о стратегии по самому элементу: ссылка — берём href.
        if node.tag == "a" and node.get("href"):
            strategy, attribute = SelectStrategy.ATTRIBUTE, "href"
        elif node.tag == "img":
            strategy, attribute = SelectStrategy.IMAGE, "src"

    try:
        field = FieldSpec(
            key=key,
            title=title,
            selector=selector,
            strategy=strategy,
            attribute=attribute,
            required=payload.required,
            note=payload.note,
        )
    except Exception as exc:  # noqa: BLE001
        raise ValidationError("Поле заполнено неверно", details={"reason": str(exc)[:300]}) from exc

    result = await editor.mutate_fields(db, settings, snapshot_id, action="add", field=field)
    return EditorStateResponse(**result.as_dict())


# ---------------------------------------------------------------------------
# План и пагинация
# ---------------------------------------------------------------------------


@router.patch(
    "/snapshots/{snapshot_id}/draft/plan",
    response_model=EditorStateResponse,
    summary="Изменить план извлечения и переход по страницам",
)
async def update_plan(
    snapshot_id: str,
    payload: PlanUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EditorStateResponse:
    settings = _settings(request)
    state = await editor.get_state(db, settings, snapshot_id)
    draft = state.draft

    plan_data: dict[str, Any] = draft.plan.model_dump()
    if payload.plan_mode is not None:
        plan_data["mode"] = payload.plan_mode
    for name in ("container_selector", "item_selector", "api_url", "records_path"):
        value = getattr(payload, name)
        if value is not None:
            plan_data[name] = value or None
    if payload.plan_mode == "single":
        # В одиночном режиме контейнер списка не нужен и только путает.
        plan_data["container_selector"] = None
        plan_data["item_selector"] = None

    pagination: PaginationSpec = payload.pagination or draft.pagination
    updated = draft.model_copy(
        update={
            "plan": ExtractionPlan.model_validate(plan_data),
            "pagination": pagination,
        }
    )
    result = await editor.save_draft(db, settings, snapshot_id, updated)
    return EditorStateResponse(**result.as_dict())


# ---------------------------------------------------------------------------
# Предпросмотр и сохранение
# ---------------------------------------------------------------------------


@router.get(
    "/snapshots/{snapshot_id}/draft/preview",
    response_model=PreviewResponse,
    summary="Предпросмотр значений полей на текущей странице",
    description="Показывает, что именно соберёт сценарий, до его сохранения.",
)
async def preview_draft(
    snapshot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PreviewResponse:
    settings = _settings(request)
    state = await editor.get_state(db, settings, snapshot_id)
    _snapshot, document = await editor.load_document(db, settings, snapshot_id)

    from app.editor import resolver

    previews: list[FieldPreviewOut] = []
    for spec in state.draft.fields:
        report = resolver.resolve(document.root, spec.selector)
        values: list[str] = []
        for node in report.nodes[:5]:
            if spec.strategy is SelectStrategy.ATTRIBUTE and spec.attribute:
                values.append(node.get(spec.attribute))
            elif spec.strategy is SelectStrategy.IMAGE:
                values.append(node.get("src") or node.get("data-src"))
            elif spec.strategy is SelectStrategy.HTML:
                values.append(node.all_text(limit=80))
            else:
                values.append(node.all_text(limit=80))
        previews.append(
            FieldPreviewOut(
                key=spec.key,
                matches=report.count,
                values=[value for value in values if value],
                error=report.error,
            )
        )

    return PreviewResponse(
        snapshot_id=snapshot_id,
        mode=state.draft.plan.mode,
        items_in_dom=state.items_in_dom,
        fields=previews,
    )


@router.post(
    "/snapshots/{snapshot_id}/draft/save-as-scenario",
    response_model=ScenarioSavedResponse,
    summary="Сохранить черновик как сценарий",
    description=(
        "Первое сохранение создаёт сценарий и версию 1, последующие добавляют "
        "новую версию. Старые версии остаются: правка вёрстки не должна означать "
        "потерю работы."
    ),
)
async def save_as_scenario(
    snapshot_id: str,
    payload: SaveScenarioRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ScenarioSavedResponse:
    settings = _settings(request)
    state = await editor.get_state(db, settings, snapshot_id)
    if not state.validation.ok:
        raise ValidationError(
            "Сценарий не готов: исправьте найденные проблемы",
            details={"problems": state.validation.problems},
        )

    saved = await editor.build_scenario(
        db,
        settings,
        snapshot_id,
        name=payload.name,
        description=payload.description,
        change_note=payload.change_note,
        scenario_id=payload.scenario_id,
    )
    return ScenarioSavedResponse(
        scenario_id=saved.scenario.id,
        site_id=saved.scenario.site_id,
        scenario_name=saved.scenario.name,
        version=saved.version.version,
        fields=len(saved.definition.fields),
        definition=saved.definition,
    )


# ---------------------------------------------------------------------------
# Сценарии
# ---------------------------------------------------------------------------


@router.get(
    "/scenarios",
    response_model=ScenarioListResponse,
    summary="Список сценариев",
)
async def list_scenarios(
    db: AsyncSession = Depends(get_db),
    site_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ScenarioListResponse:
    records = await scenario_service.list_scenarios(db, site_id=site_id, limit=limit, offset=offset)
    total = await scenario_service.count_scenarios(db, site_id)
    items = []
    for record in records:
        version = await scenario_service.get_current_version(db, record)
        definition = scenario_service.definition_from_version(version) if version else None
        items.append(scenario_service.scenario_to_out(record, definition))
    return ScenarioListResponse(items=items, total=total)


@router.get(
    "/scenarios/{scenario_id}/versions",
    response_model=list[ScenarioVersionOut],
    summary="История версий сценария",
)
async def list_scenario_versions(
    scenario_id: str,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> list[ScenarioVersionOut]:
    await scenario_service.get_scenario(db, scenario_id)
    versions = await scenario_service.list_versions(db, scenario_id, limit=limit)
    return [scenario_service.version_to_out(version) for version in versions]


@router.delete(
    "/scenarios/{scenario_id}",
    summary="Удалить сценарий вместе со всеми версиями",
)
async def delete_scenario(
    scenario_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await scenario_service.delete_scenario(db, scenario_id)
    return {"scenario_id": scenario_id, "deleted": True}
