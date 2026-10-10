"""Тесты прикладного слоя анализа: карта элементов, сохранение, уточнение моделью."""

from __future__ import annotations

import pytest

from app.analyzer import service as analyze
from app.analyzer.llm import LLMEnrichment
from app.analyzer.roles import Role
from app.core.config import Settings
from app.core.db import session_scope
from app.core.errors import NotFoundError, ValidationError
from app.crawler import service as crawl
from tests.fakes import patch_capture


async def make_snapshot(
    settings: Settings, monkeypatch, *, url: str = "https://shop.example.com/catalog"
):
    """Снимает снапшот с поддельным браузером — основа для анализа."""
    patch_capture(monkeypatch, settings)
    async with session_scope() as db:
        outcome = await crawl.capture(db, settings, url)
        return outcome.snapshot.id


async def test_analyze_builds_element_map(settings: Settings, monkeypatch) -> None:
    settings.llm_provider = "none"
    snapshot_id = await make_snapshot(settings, monkeypatch)

    async with session_scope() as db:
        outcome = await analyze.analyze_snapshot(db, settings, snapshot_id, use_llm=False)

    record = outcome.element_map
    assert record.snapshot_id == snapshot_id
    assert record.version == 1
    assert record.elements
    assert record.confidence and 0 < record.confidence <= 1
    assert "Найден список" in (record.summary or "")
    assert outcome.llm.used is False

    roles = {element["role"] for element in record.elements}
    assert "list_container" in roles
    assert "search_input" in roles
    assert "item_price" in roles


async def test_analyze_without_model_keeps_full_result(settings: Settings, monkeypatch) -> None:
    """Отсутствие модели не должно ухудшать структуру карты."""
    # Ollama указана, но недоступна на этом порту — штатная ситуация.
    settings.llm_provider = "ollama"
    settings.ollama_base_url = "http://127.0.0.1:1"
    settings.llm_timeout_s = 1
    snapshot_id = await make_snapshot(settings, monkeypatch)

    async with session_scope() as db:
        outcome = await analyze.analyze_snapshot(db, settings, snapshot_id, use_llm=True)

    assert outcome.element_map.elements
    assert outcome.llm.used is False
    assert outcome.llm.detail
    # Отчёт всё равно полноценный: резюме модели в нём просто отсутствует.
    assert "Найден список" in (outcome.element_map.summary or "")
    assert outcome.element_map.llm_provider is None


async def test_analyze_reuses_existing_map(settings: Settings, monkeypatch) -> None:
    settings.llm_provider = "none"
    snapshot_id = await make_snapshot(settings, monkeypatch)

    async with session_scope() as db:
        first = await analyze.analyze_snapshot(db, settings, snapshot_id, use_llm=False)
    async with session_scope() as db:
        second = await analyze.analyze_snapshot(db, settings, snapshot_id, use_llm=False)

    assert second.reused is True
    assert second.element_map.id == first.element_map.id
    assert second.element_map.version == 1


async def test_analyze_force_rebuilds_and_bumps_version(settings: Settings, monkeypatch) -> None:
    settings.llm_provider = "none"
    snapshot_id = await make_snapshot(settings, monkeypatch)

    async with session_scope() as db:
        first = await analyze.analyze_snapshot(db, settings, snapshot_id, use_llm=False)
    async with session_scope() as db:
        second = await analyze.analyze_snapshot(
            db, settings, snapshot_id, use_llm=False, force=True
        )

    assert second.reused is False
    assert second.element_map.id == first.element_map.id
    assert second.element_map.version == 2


async def test_analyze_missing_snapshot(settings: Settings) -> None:
    async with session_scope() as db:
        with pytest.raises(NotFoundError):
            await analyze.analyze_snapshot(db, settings, "нет-такого", use_llm=False)


async def test_analyze_missing_artifacts(settings: Settings, monkeypatch) -> None:
    """Если артефакты снапшота удалены, анализ должен сказать об этом понятно."""
    from app.crawler import store

    settings.llm_provider = "none"
    snapshot_id = await make_snapshot(settings, monkeypatch)
    store.delete_snapshot_artifacts(settings, snapshot_id)

    async with session_scope() as db:
        with pytest.raises(NotFoundError) as error:
            await analyze.analyze_snapshot(db, settings, snapshot_id, use_llm=False)
    assert "заново" in str(error.value)


async def test_llm_enrichment_is_applied(settings: Settings, monkeypatch) -> None:
    """Ответ модели должен уточнять роли и обогащать отчёт."""
    settings.llm_provider = "ollama"
    snapshot_id = await make_snapshot(settings, monkeypatch)

    async def fake_enrich(self, **_kwargs) -> LLMEnrichment:
        return LLMEnrichment(
            used=True,
            provider="ollama",
            model="test-model",
            summary="Это каталог электроинструмента с поиском и пагинацией.",
            roles={
                1: {
                    "role": "list_container",
                    "description": "сетка карточек товара",
                    "confidence": 0.95,
                },
                2: {"role": "search_input", "description": "поиск по каталогу", "confidence": 0.9},
            },
            latency_ms=1234,
        )

    monkeypatch.setattr("app.analyzer.llm.LLMGateway.enrich", fake_enrich)

    async with session_scope() as db:
        outcome = await analyze.analyze_snapshot(db, settings, snapshot_id, use_llm=True)

    assert outcome.llm.used is True
    assert outcome.element_map.llm_provider == "ollama"
    assert outcome.element_map.llm_model == "test-model"
    assert outcome.element_map.prompt_version
    # Резюме модели стоит в начале отчёта.
    assert (outcome.element_map.summary or "").startswith("Это каталог")
    described = outcome.element_map.elements[1]
    assert described["description"] == "поиск по каталогу"
    assert described["source"] in {"llm", "heuristic+llm"}


async def test_llm_does_not_override_with_low_confidence(settings: Settings, monkeypatch) -> None:
    """Робкая догадка модели не должна затирать уверенную эвристику."""
    settings.llm_provider = "ollama"
    snapshot_id = await make_snapshot(settings, monkeypatch)

    async def fake_enrich(self, **_kwargs) -> LLMEnrichment:
        return LLMEnrichment(
            used=True,
            provider="ollama",
            model="test-model",
            roles={2: {"role": "unknown_role_x", "confidence": 0.1}},
        )

    monkeypatch.setattr("app.analyzer.llm.LLMGateway.enrich", fake_enrich)

    async with session_scope() as db:
        outcome = await analyze.analyze_snapshot(db, settings, snapshot_id, use_llm=True)

    # Некорректная роль отброшена, роли остались эвристическими.
    roles = {element["role"] for element in outcome.element_map.elements}
    assert "unknown_role_x" not in roles
    assert "search_input" in roles


async def test_apply_enrichment_ignores_out_of_range_indexes() -> None:
    from app.analyzer.detector import PageAnalysis
    from app.analyzer.roles import Element

    analysis = PageAnalysis(
        title="t",
        lang="ru",
        meta={},
        counts={},
        elements=[Element(role=Role.LINK, selector="a", description="")],
    )
    enrichment = LLMEnrichment(
        used=True,
        roles={5: {"role": "item_price", "description": "цена", "confidence": 0.99}},
    )
    changed = analyze.apply_llm_enrichment(analysis, enrichment)

    assert changed == 0
    assert analysis.elements[0].role is Role.LINK


async def test_get_and_require_element_map(settings: Settings, monkeypatch) -> None:
    settings.llm_provider = "none"
    snapshot_id = await make_snapshot(settings, monkeypatch)

    async with session_scope() as db:
        assert await analyze.get_element_map(db, snapshot_id) is None
        with pytest.raises(NotFoundError):
            await analyze.require_element_map(db, snapshot_id)

    async with session_scope() as db:
        await analyze.analyze_snapshot(db, settings, snapshot_id, use_llm=False)

    async with session_scope() as db:
        record = await analyze.require_element_map(db, snapshot_id)
        assert record.snapshot_id == snapshot_id


async def test_update_element_marks_user_edit(settings: Settings, monkeypatch) -> None:
    settings.llm_provider = "none"
    snapshot_id = await make_snapshot(settings, monkeypatch)
    async with session_scope() as db:
        await analyze.analyze_snapshot(db, settings, snapshot_id, use_llm=False)

    async with session_scope() as db:
        record = await analyze.update_element(
            db,
            snapshot_id,
            1,
            role="item_title",
            label="Наименование товара",
            description="Название",
        )

    element = record.elements[1]
    assert element["role"] == "item_title"
    assert element["label"] == "Наименование товара"
    assert element["source"] == "user"
    assert element["confidence"] == 1.0
    assert record.edited_by_user is True


async def test_update_element_validates_input(settings: Settings, monkeypatch) -> None:
    settings.llm_provider = "none"
    snapshot_id = await make_snapshot(settings, monkeypatch)
    async with session_scope() as db:
        await analyze.analyze_snapshot(db, settings, snapshot_id, use_llm=False)

    async with session_scope() as db:
        with pytest.raises(NotFoundError):
            await analyze.update_element(db, snapshot_id, 9999, role="item_title")
    async with session_scope() as db:
        with pytest.raises(ValidationError):
            await analyze.update_element(db, snapshot_id, 1, role="такой-роли-нет")


async def test_reanalysis_resets_user_edits(settings: Settings, monkeypatch) -> None:
    """Повторный анализ по новой вёрстке сбрасывает правки — это осознанно."""
    settings.llm_provider = "none"
    snapshot_id = await make_snapshot(settings, monkeypatch)
    async with session_scope() as db:
        await analyze.analyze_snapshot(db, settings, snapshot_id, use_llm=False)
    async with session_scope() as db:
        await analyze.update_element(db, snapshot_id, 1, role="item_title")

    async with session_scope() as db:
        record = await analyze.analyze_snapshot(
            db, settings, snapshot_id, use_llm=False, force=True
        )

    assert record.element_map.edited_by_user is False


async def test_list_element_maps(settings: Settings, monkeypatch) -> None:
    settings.llm_provider = "none"
    first = await make_snapshot(settings, monkeypatch, url="https://a.example.com/")
    second = await make_snapshot(settings, monkeypatch, url="https://b.example.com/")

    async with session_scope() as db:
        await analyze.analyze_snapshot(db, settings, first, use_llm=False)
    async with session_scope() as db:
        await analyze.analyze_snapshot(db, settings, second, use_llm=False)

    async with session_scope() as db:
        records = await analyze.list_element_maps(db)

    assert len(records) == 2


async def test_element_map_to_dict_counts_roles(settings: Settings, monkeypatch) -> None:
    settings.llm_provider = "none"
    snapshot_id = await make_snapshot(settings, monkeypatch)
    async with session_scope() as db:
        outcome = await analyze.analyze_snapshot(db, settings, snapshot_id, use_llm=False)
        data = analyze.element_map_to_dict(outcome.element_map)

    assert data["by_role"]["list_container"] >= 1
    assert data["snapshot_id"] == snapshot_id
    assert data["elements"]


def test_analyze_now_helper() -> None:
    analysis, report = analyze.analyze_now("<html><body><p>Просто текст</p></body></html>")
    assert analysis.elements is not None
    assert report


def test_empty_analysis_helper() -> None:
    empty = analyze.empty_analysis()
    assert empty.elements == []
    assert empty.warnings
