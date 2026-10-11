"""Тесты сервиса визуального редактора: черновик, проверка, сохранение сценария."""

from __future__ import annotations

import pytest

from app.analyzer import service as analyze
from app.core.config import Settings
from app.core.db import session_scope
from app.core.errors import NotFoundError, ValidationError
from app.crawler import service as crawl
from app.editor import scenario as scenario_service
from app.editor import service as editor
from app.editor.domlite_helpers import scenario_for_html
from app.editor.schema import (
    ExtractionPlan,
    FieldSpec,
    PaginationKind,
    PaginationSpec,
    ScenarioDefinition,
    SelectStrategy,
)
from tests.fakes import patch_capture
from tests.pages import CATALOG


async def analyzed_snapshot(
    settings: Settings, monkeypatch, *, url: str = "https://shop.example.com/catalog"
):
    """Снапшот с готовой картой элементов — основа для редактора."""
    settings.llm_provider = "none"
    patch_capture(monkeypatch, settings)
    async with session_scope() as db:
        outcome = await crawl.capture(db, settings, url)
        snapshot_id = outcome.snapshot.id
    async with session_scope() as db:
        await analyze.analyze_snapshot(db, settings, snapshot_id, use_llm=False)
    return snapshot_id


# --- Построение базового сценария -------------------------------------------


def test_baseline_from_element_map() -> None:
    """Базовый сценарий собирается из карты: поля, контейнер, пагинация."""
    analysis, _report = analyze.analyze_now(CATALOG.html)
    record = _fake_record(analysis)
    snapshot = _fake_snapshot(CATALOG.html, "https://shop.example.com/catalog?page=1")

    baseline = editor.build_baseline(record, snapshot, items_expected=12)

    assert baseline.url.startswith("https://shop.example.com")
    assert baseline.plan.mode == "list"
    assert baseline.plan.container_selector
    keys = {field.key for field in baseline.fields}
    assert "title" in keys
    assert "price" in keys
    assert "url" in keys
    assert "image" in keys
    assert baseline.pagination.kind is PaginationKind.URL_TEMPLATE
    assert baseline.pagination.url_template
    assert "{page}" in (baseline.pagination.url_template or "")
    # Ссылка берётся из href, картинка — из src.
    url_field = next(field for field in baseline.fields if field.key == "url")
    assert url_field.strategy is SelectStrategy.ATTRIBUTE
    assert url_field.attribute == "href"
    image_field = next(field for field in baseline.fields if field.key == "image")
    assert image_field.strategy is SelectStrategy.IMAGE


def test_baseline_without_next_link() -> None:
    analysis, _report = analyze.analyze_now(
        "<html><body><div class='product-list'>"
        "<div class='product-card'><h3 class='product-card__title'>Т1</h3></div>"
        "<div class='product-card'><h3 class='product-card__title'>Т2</h3></div>"
        "<div class='product-card'><h3 class='product-card__title'>Т3</h3></div>"
        "</div></body></html>"
    )
    record = _fake_record(analysis)
    snapshot = _fake_snapshot("<html><body></body></html>", "https://shop.example.com/catalog")

    baseline = editor.build_baseline(record, snapshot)
    assert baseline.pagination.kind is PaginationKind.NONE


def test_url_template_detection() -> None:
    assert (
        editor._url_template("https://a.com/catalog?page=2") == "https://a.com/catalog?page={page}"
    )
    assert editor._url_template("https://a.com/catalog?page=2&sort=asc") == (
        "https://a.com/catalog?page={page}&sort=asc"
    )
    # Без цифрового номера страницы шаблон не строится: структуру адреса не угадываем.
    assert editor._url_template("https://a.com/catalog") is None
    assert editor._url_template("https://a.com/catalog?sort=asc") is None


def test_suggest_key_transliterates_russian() -> None:
    used: set[str] = set()
    assert editor.suggest_key("Наименование товара", used) == "naimenovanie_tovara"
    # «Цена» → cena: в таблице транслитерации ц → c.
    assert editor.suggest_key("Цена", used) == "cena"
    assert editor.suggest_key("Цена", used) == "cena_2"
    assert editor.suggest_key("!!!", used) == "field"


def test_suggest_key_avoids_leading_digit() -> None:
    used: set[str] = set()
    assert editor.suggest_key("1 поле", used).startswith("f_")


# --- Проверка определения ----------------------------------------------------


def test_validate_definition_ok_and_partial() -> None:
    analysis, _report = analyze.analyze_now(CATALOG.html)
    record = _fake_record(analysis)
    snapshot = _fake_snapshot(CATALOG.html, "https://shop.example.com/catalog")
    baseline = editor.build_baseline(record, snapshot, items_expected=12)

    from app.analyzer.domlite import parse

    # В DOM 12 карточек, ожидается 12 — всё сходится.
    ok = editor.validate_definition(parse(CATALOG.html), baseline, items_expected=12)
    assert ok.ok is True
    assert all(field.status == "ok" for field in ok.fields)
    assert ok.problems == []

    # Если ожидать больше, чем есть, поля отмечаются как частичные.
    partial = editor.validate_definition(parse(CATALOG.html), baseline, items_expected=100)
    assert partial.ok is True
    assert any(field.status == "partial" for field in partial.fields)
    assert partial.warnings


def test_validate_definition_reports_broken_selector() -> None:
    definition = ScenarioDefinition(
        url="https://a.com",
        plan=ExtractionPlan(mode="list", container_selector=".catalog"),
        fields=[
            FieldSpec(key="title", title="Название", selector=".product-card__title"),
            FieldSpec(key="nope", title="Чего нет", selector=".no-such-thing"),
        ],
    )
    result = editor.validate_definition(editor.parse_html_for_validation(CATALOG.html), definition)

    assert result.ok is False
    assert any("не находит" in problem for problem in result.problems)
    statuses = {field.key: field.status for field in result.fields}
    assert statuses["nope"] == "empty"
    assert statuses["title"] == "ok"


def test_validate_definition_without_fields() -> None:
    definition = ScenarioDefinition(url="https://a.com", fields=[])
    result = editor.validate_definition(editor.parse_html_for_validation(CATALOG.html), definition)

    assert result.ok is False
    assert any("нет ни одного поля" in problem for problem in result.problems)


def test_validate_definition_requires_container_in_list_mode() -> None:
    definition = ScenarioDefinition(
        url="https://a.com",
        plan=ExtractionPlan(mode="list"),
        fields=[FieldSpec(key="t", title="Т", selector=".product-card__title")],
    )
    result = editor.validate_definition(editor.parse_html_for_validation(CATALOG.html), definition)
    assert any("контейнер списка" in problem.lower() for problem in result.problems)


def test_validate_pagination_requirements() -> None:
    base = ScenarioDefinition(
        url="https://a.com",
        plan=ExtractionPlan(mode="single"),
        fields=[FieldSpec(key="t", title="Т", selector="h1")],
    )
    missing_selector = base.model_copy(
        update={"pagination": PaginationSpec(kind=PaginationKind.NEXT_LINK)}
    )
    result = editor.validate_definition(
        editor.parse_html_for_validation(CATALOG.html), missing_selector
    )
    assert any("селектор кнопки не задан" in problem for problem in result.problems)

    bad_selector = base.model_copy(
        update={
            "pagination": PaginationSpec(kind=PaginationKind.NEXT_LINK, selector=".no-such-next")
        }
    )
    result = editor.validate_definition(
        editor.parse_html_for_validation(CATALOG.html), bad_selector
    )
    assert any("ничего не находит" in problem for problem in result.problems)


def test_validate_api_mode_requires_url() -> None:
    definition = ScenarioDefinition(
        url="https://a.com",
        plan=ExtractionPlan(mode="api"),
        fields=[FieldSpec(key="t", title="Т", selector="h1")],
    )
    result = editor.validate_definition(editor.parse_html_for_validation(CATALOG.html), definition)
    assert any("адрес запроса не указан" in problem for problem in result.problems)


def test_validate_non_unique_selector_is_allowed_but_reported() -> None:
    """Селектор, находящий несколько узлов, не ошибка: так и выглядит список."""
    definition = ScenarioDefinition(
        url="https://a.com",
        plan=ExtractionPlan(mode="list", container_selector=".product-list"),
        fields=[FieldSpec(key="t", title="Название", selector=".product-card__title")],
    )
    result = editor.validate_definition(
        editor.parse_html_for_validation(CATALOG.html), definition, items_expected=12
    )
    assert result.ok is True
    field = result.fields[0]
    assert field.matches == 12
    assert field.coverage == 1.0


# --- Живой редактор ----------------------------------------------------------


async def test_get_state_builds_baseline_and_draft(settings: Settings, monkeypatch) -> None:
    snapshot_id = await analyzed_snapshot(settings, monkeypatch)

    async with session_scope() as db:
        state = await editor.get_state(db, settings, snapshot_id)

    assert state.snapshot_id == snapshot_id
    assert state.baseline.fields
    assert state.changed is False
    assert state.validation.fields
    assert state.items_in_dom >= 1


async def test_draft_lifecycle(settings: Settings, monkeypatch) -> None:
    snapshot_id = await analyzed_snapshot(settings, monkeypatch)

    async with session_scope() as db:
        state = await editor.get_state(db, settings, snapshot_id)
        draft = state.draft.model_copy(update={"title": "Мой сценарий", "description": "Проверка"})
        saved = await editor.save_draft(db, settings, snapshot_id, draft)

    assert saved.draft.title == "Мой сценарий"
    assert saved.changed is True

    # Черновик читается из базы при следующем обращении.
    async with session_scope() as db:
        again = await editor.get_state(db, settings, snapshot_id)
    assert again.draft.title == "Мой сценарий"

    async with session_scope() as db:
        reset = await editor.reset_draft(db, settings, snapshot_id)
    assert reset.changed is False
    assert reset.draft.title == reset.baseline.title


async def test_add_update_remove_and_order_fields(settings: Settings, monkeypatch) -> None:
    snapshot_id = await analyzed_snapshot(settings, monkeypatch)

    async with session_scope() as db:
        state = await editor.get_state(db, settings, snapshot_id)
        extra = FieldSpec(key="sku", title="Артикул", selector=".product-card", required=True)
        added = await editor.mutate_fields(db, settings, snapshot_id, action="add", field=extra)
    assert any(field.key == "sku" for field in added.draft.fields)

    async with session_scope() as db:
        with pytest.raises(ValidationError):
            await editor.mutate_fields(db, settings, snapshot_id, action="add", field=extra)

    async with session_scope() as db:
        state = await editor.get_state(db, settings, snapshot_id)
        current = next(field for field in state.draft.fields if field.key == "sku")
        changed = current.model_copy(update={"title": "Артикул поставщика", "required": False})
        updated = await editor.mutate_fields(
            db, settings, snapshot_id, action="update", field=changed
        )
    assert (
        next(field for field in updated.draft.fields if field.key == "sku").title
        == "Артикул поставщика"
    )

    async with session_scope() as db:
        order = [field.key for field in reversed(updated.draft.fields)]
        reordered = await editor.mutate_fields(
            db, settings, snapshot_id, action="order", order=order
        )
    assert [field.key for field in reordered.draft.fields] == order

    async with session_scope() as db:
        removed = await editor.mutate_fields(db, settings, snapshot_id, action="remove", key="sku")
    assert all(field.key != "sku" for field in removed.draft.fields)


async def test_mutate_unknown_field_and_action(settings: Settings, monkeypatch) -> None:
    snapshot_id = await analyzed_snapshot(settings, monkeypatch)

    async with session_scope() as db:
        with pytest.raises(NotFoundError):
            await editor.mutate_fields(
                db, settings, snapshot_id, action="remove", key="no-such-field"
            )
    async with session_scope() as db:
        with pytest.raises(ValidationError):
            await editor.mutate_fields(db, settings, snapshot_id, action="explode")


async def test_state_for_missing_snapshot(settings: Settings) -> None:
    async with session_scope() as db:
        with pytest.raises(NotFoundError):
            await editor.get_state(db, settings, "нет-такого")


async def test_inspector_payload_has_nodes_and_screenshot_link(
    settings: Settings, monkeypatch
) -> None:
    snapshot_id = await analyzed_snapshot(settings, monkeypatch)

    async with session_scope() as db:
        payload = await editor.build_inspector_payload(db, settings, snapshot_id)

    assert payload.snapshot_id == snapshot_id
    assert payload.nodes
    assert payload.total == len(payload.nodes)
    assert payload.page["width"] > 0
    # Скриншот снапшота доступен как артефакт.
    assert payload.screenshot_url is None or payload.screenshot_url.endswith("screenshot-full.png")
    # Узлы карты отмечены в инспекторе.
    marked = [node for node in payload.nodes if node["matched_by"]]
    assert marked


# --- Сохранение сценария -----------------------------------------------------


async def test_save_scenario_creates_versions(settings: Settings, monkeypatch) -> None:
    snapshot_id = await analyzed_snapshot(settings, monkeypatch)

    async with session_scope() as db:
        state = await editor.get_state(db, settings, snapshot_id)
        snapshot = await db.get(crawl.Snapshot, snapshot_id)
        first_scenario, first_version = await scenario_service.save_scenario(
            db,
            state.draft,
            name="Каталог товаров",
            site_id=snapshot.site_id,
            change_note="первая версия",
        )
        scenario_id = first_scenario.id

    assert first_version.version == 1
    assert first_scenario.current_version == 1

    # Второе сохранение с тем же именем добавляет версию, а не новый сценарий.
    async with session_scope() as db:
        state = await editor.get_state(db, settings, snapshot_id)
        updated = state.draft.model_copy(update={"title": "Каталог v2"})
        scenario, version = await scenario_service.save_scenario(
            db,
            updated,
            name="Каталог товаров",
            site_id=snapshot.site_id,
            change_note="правка селектора цены",
        )

    assert scenario.id == scenario_id
    assert version.version == 2

    async with session_scope() as db:
        versions = await scenario_service.list_versions(db, scenario_id)
        total = await scenario_service.count_scenarios(db)

    assert [item.version for item in versions] == [2, 1]
    assert total == 1
    # История версий позволяет откатиться: определение первой версии читается.
    restored = scenario_service.definition_from_version(versions[1])
    assert restored.title == state.baseline.title


async def test_save_scenario_to_other_site_is_rejected(settings: Settings, monkeypatch) -> None:
    first = await analyzed_snapshot(settings, monkeypatch, url="https://a.example.com/")
    second = await analyzed_snapshot(settings, monkeypatch, url="https://b.example.com/")

    async with session_scope() as db:
        state = await editor.get_state(db, settings, first)
        snapshot = await db.get(crawl.Snapshot, first)
        scenario, _version = await scenario_service.save_scenario(
            db, state.draft, name="Сценарий", site_id=snapshot.site_id
        )
        other = await db.get(crawl.Snapshot, second)
        with pytest.raises(ValidationError):
            await scenario_service.save_scenario(
                db,
                state.draft,
                name="Сценарий",
                site_id=other.site_id,
                scenario_id=scenario.id,
            )


async def test_delete_scenario_removes_versions(settings: Settings, monkeypatch) -> None:
    snapshot_id = await analyzed_snapshot(settings, monkeypatch)

    async with session_scope() as db:
        state = await editor.get_state(db, settings, snapshot_id)
        snapshot = await db.get(crawl.Snapshot, snapshot_id)
        scenario, _version = await scenario_service.save_scenario(
            db, state.draft, name="Временный", site_id=snapshot.site_id
        )
        scenario_id = scenario.id

    async with session_scope() as db:
        await scenario_service.delete_scenario(db, scenario_id)
    async with session_scope() as db:
        with pytest.raises(NotFoundError):
            await scenario_service.get_scenario(db, scenario_id)
        versions = await scenario_service.list_versions(db, scenario_id)
    assert versions == []


# --- Вспомогательные объекты -------------------------------------------------


def _fake_record(analysis):
    """Подставляет результат анализа в объект с полем ``elements``."""

    class _Record:
        elements = [element.as_dict() for element in analysis.elements]
        edit_draft = None
        id = "test-map"

    return _Record()


def _fake_snapshot(_html: str, url: str):
    """Минимальный снапшот для проверки построения сценария."""

    # Параметр привязываем к локальному имени: в теле класса имя `url`
    # перекрывается объявлением поля, и обращение к параметру падает.
    page_url = url

    class _Snapshot:
        id = "test-snapshot"
        final_url = page_url
        url = page_url
        title = "Тестовая страница"

    return _Snapshot()


def test_scenario_for_html_helper_available() -> None:
    """Хелпер упрощает проверку сценария на произвольной разметке."""
    definition = scenario_for_html(CATALOG.html, url="https://shop.example.com/catalog")
    assert definition.fields
    assert definition.plan.mode == "list"
