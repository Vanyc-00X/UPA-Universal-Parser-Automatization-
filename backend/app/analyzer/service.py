"""Сборка карты элементов: детерминированный анализ плюс уточнение моделью.

Порядок работы принципиален:

1. **Детерминированный анализ** разбирает HTML и находит всё, что можно найти без
   ИИ: списки, поля, кнопки, пагинацию. Работает всегда.
2. **Уточнение моделью** (если она доступна) перепроверяет роли и формулирует
   человекочитаемое резюме. Если модель молчит — результат остаётся полноценным,
   просто без литературных формулировок.

Такой порядок означает, что недоступная Ollama ухудшает качество, но никогда не
ломает функцию.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer import detector
from app.analyzer.detector import PageAnalysis, build_report
from app.analyzer.llm import LLMEnrichment, LLMGateway
from app.analyzer.roles import Role, label_for
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.crawler import service as crawl_service
from app.crawler import store
from app.storage.models import ElementMap, Snapshot, new_id, utcnow

log = get_logger(__name__)

# Сколько элементов отправляем модели. Больше — медленнее и без пользы: модель
# начинает терять номера.
LLM_ELEMENT_LIMIT = 60
# Минимальная уверенность роли от модели, чтобы принять её вместо эвристики.
LLM_ACCEPT_CONFIDENCE = 0.5


@dataclass
class AnalysisOutcome:
    """Результат анализа снапшота."""

    element_map: ElementMap
    analysis: PageAnalysis
    llm: LLMEnrichment
    report: str
    reused: bool = False

    def summary(self) -> dict[str, Any]:
        return {
            "element_map_id": self.element_map.id,
            "elements": len(self.element_map.elements or []),
            "repeats": len(self.analysis.repeats),
            "llm": self.llm.as_dict(),
            "reused": self.reused,
        }


def _valid_role(value: str) -> Role:
    """Преобразует строку в роль, возвращая UNKNOWN для неизвестных значений."""
    try:
        return Role(value)
    except ValueError:
        return Role.UNKNOWN


def _llm_payload(analysis: PageAnalysis, limit: int = LLM_ELEMENT_LIMIT) -> list[dict[str, Any]]:
    """Готовит элементы к отправке модели.

    Номера начинаются с единицы: модели удобнее, а нам — сопоставлять ответ.
    """
    payload: list[dict[str, Any]] = []
    for index, element in enumerate(analysis.elements[:limit], start=1):
        hint_parts = [element.label]
        if element.attrs.get("name"):
            hint_parts.append(f"name={element.attrs['name']}")
        if element.attrs.get("type"):
            hint_parts.append(f"type={element.attrs['type']}")
        if element.attrs.get("placeholder"):
            hint_parts.append(f"placeholder={element.attrs['placeholder']}")
        if element.count > 1:
            hint_parts.append(f"повторов: {element.count}")
        payload.append(
            {
                "index": index,
                "tag": element.tag,
                "hint": " ".join(hint_parts),
                "text": element.sample or "",
            }
        )
    return payload


def apply_llm_enrichment(analysis: PageAnalysis, enrichment: LLMEnrichment) -> int:
    """Накладывает ответ модели на карту элементов.

    Возвращает число изменённых элементов. Роль меняется только если модель
    уверена: занижать собственную эвристику из-за робкого ответа не нужно.
    """
    changed = 0
    for index, described in enrichment.roles.items():
        position = index - 1
        if not 0 <= position < len(analysis.elements):
            continue
        element = analysis.elements[position]
        role = _valid_role(described.get("role") or "")
        if role is Role.UNKNOWN:
            continue
        confidence = described.get("confidence")
        if confidence is not None and confidence < LLM_ACCEPT_CONFIDENCE and role != element.role:
            continue

        if role != element.role:
            changed += 1
            element.role = role
            element.label = label_for(role)
        if described.get("description"):
            element.description = described["description"]
        if confidence is not None:
            element.confidence = round(float(confidence), 3)
        else:
            # Модель подтвердила роль — уверенность немного растёт.
            element.confidence = round(min(0.99, element.confidence + 0.05), 3)
        element.source = "llm" if element.source != "heuristic" else "heuristic+llm"
    return changed


async def analyze_snapshot(
    session: AsyncSession,
    settings: Settings,
    snapshot_id: str,
    *,
    use_llm: bool = True,
    force: bool = False,
) -> AnalysisOutcome:
    """Анализирует снапшот и сохраняет карту элементов.

    При ``force=False`` уже построенная карта возвращается как есть: повторный
    анализ той же страницы не должен занимать модель.
    """
    snapshot = await crawl_service.get_snapshot(session, snapshot_id)

    if not force:
        existing = await get_element_map(session, snapshot_id)
        if existing is not None:
            analysis = detector.analyze_html(
                store.load_text(settings, snapshot_id, store.TRIMMED_HTML) or ""
            )
            return AnalysisOutcome(
                element_map=existing,
                analysis=analysis,
                llm=LLMEnrichment(used=False, detail="карта уже построена"),
                report=existing.summary or build_report(analysis),
                reused=True,
            )

    html = store.load_text(settings, snapshot_id, store.TRIMMED_HTML)
    if html is None:
        html = store.load_text(settings, snapshot_id, store.PAGE_HTML)
    if html is None:
        raise NotFoundError(
            "Артефакты снапшота не найдены — снимите снапшот заново",
            details={"snapshot_id": snapshot_id},
        )

    analysis = detector.analyze_html(html)
    # Заголовок и язык надёжнее брать из самого снапшота: их записал браузер с
    # живой страницы. В обрезанном DOM тега <title> уже нет — обрезка работает
    # только с телом документа.
    if not analysis.title and snapshot.title:
        analysis.title = snapshot.title
    if not analysis.lang and snapshot.lang:
        analysis.lang = snapshot.lang

    enrichment = LLMEnrichment()
    if use_llm and settings.llm_provider != "none" and analysis.elements:
        gateway = LLMGateway(settings)
        enrichment = await gateway.enrich(
            title=analysis.title,
            lang=analysis.lang,
            url=snapshot.final_url or snapshot.url,
            repeats=[group.as_dict() for group in analysis.repeats],
            elements=_llm_payload(analysis),
        )
        if enrichment.used:
            changed = apply_llm_enrichment(analysis, enrichment)
            log.info(
                "analyzer.llm_enriched",
                snapshot_id=snapshot_id,
                described=len(enrichment.roles),
                changed=changed,
                latency_ms=enrichment.latency_ms,
            )

    report = build_report(analysis)
    if enrichment.used and enrichment.summary:
        report = f"{enrichment.summary}\n\n{report}"

    record = await _save_element_map(session, snapshot, analysis, enrichment, report)
    return AnalysisOutcome(element_map=record, analysis=analysis, llm=enrichment, report=report)


async def _save_element_map(
    session: AsyncSession,
    snapshot: Snapshot,
    analysis: PageAnalysis,
    enrichment: LLMEnrichment,
    report: str,
) -> ElementMap:
    """Сохраняет карту элементов, обновляя существующую запись при повторном анализе."""
    existing = await get_element_map(session, snapshot.id)
    confidences = [element.confidence for element in analysis.elements]
    mean_confidence = round(sum(confidences) / len(confidences), 3) if confidences else None

    if existing is None:
        existing = ElementMap(
            id=new_id(),
            snapshot_id=snapshot.id,
            version=1,
            elements=[],
        )
        session.add(existing)
    else:
        existing.version = (existing.version or 1) + 1

    existing.elements = [element.as_dict() for element in analysis.elements]
    existing.summary = report
    existing.llm_provider = enrichment.provider if enrichment.used else None
    existing.llm_model = enrichment.model if enrichment.used else None
    existing.prompt_version = enrichment.prompt_version
    existing.confidence = mean_confidence
    # Правки пользователя при повторном анализе сбрасываются: это осознанно —
    # новая вёрстка означает новый анализ.
    existing.edited_by_user = False
    existing.updated_at = utcnow()

    await session.flush()
    log.info(
        "analyzer.element_map_saved",
        snapshot_id=snapshot.id,
        element_map_id=existing.id,
        elements=len(existing.elements),
        version=existing.version,
        llm_used=enrichment.used,
    )
    return existing


async def get_element_map(session: AsyncSession, snapshot_id: str) -> ElementMap | None:
    """Карта элементов снапшота, если она уже построена."""
    result = await session.execute(select(ElementMap).where(ElementMap.snapshot_id == snapshot_id))
    return result.scalar_one_or_none()


async def require_element_map(session: AsyncSession, snapshot_id: str) -> ElementMap:
    """Карта элементов или понятная ошибка 404."""
    record = await get_element_map(session, snapshot_id)
    if record is None:
        raise NotFoundError(
            "Карта элементов ещё не построена для этого снапшота",
            details={"snapshot_id": snapshot_id},
        )
    return record


async def list_element_maps(
    session: AsyncSession, *, limit: int = 50, offset: int = 0
) -> list[ElementMap]:
    """Список карт элементов, свежие сверху."""
    result = await session.execute(
        select(ElementMap).order_by(ElementMap.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


async def update_element(
    session: AsyncSession,
    snapshot_id: str,
    element_index: int,
    *,
    role: str | None = None,
    label: str | None = None,
    description: str | None = None,
) -> ElementMap:
    """Правит один элемент карты — основа визуального редактора (Этап 3)."""
    record = await require_element_map(session, snapshot_id)
    elements: list[dict[str, Any]] = list(record.elements or [])
    if not 0 <= element_index < len(elements):
        raise NotFoundError(
            "Элемент с таким номером не найден",
            details={"index": element_index, "elements": len(elements)},
        )

    element = dict(elements[element_index])
    if role is not None:
        resolved = _valid_role(role)
        if resolved is Role.UNKNOWN and role != Role.UNKNOWN.value:
            from app.core.errors import ValidationError

            raise ValidationError("Неизвестная роль элемента", details={"role": role})
        element["role"] = resolved.value
        element["label"] = label or label_for(resolved)
    if label is not None:
        element["label"] = label
    if description is not None:
        element["description"] = description
    element["source"] = "user"
    element["confidence"] = 1.0

    elements[element_index] = element
    record.elements = elements
    record.edited_by_user = True
    record.updated_at = utcnow()
    await session.flush()
    log.info("analyzer.element_edited", snapshot_id=snapshot_id, index=element_index)
    return record


def element_map_to_dict(record: ElementMap, *, report: str | None = None) -> dict[str, Any]:
    """Представление карты для API."""
    elements = list(record.elements or [])
    by_role: dict[str, int] = {}
    for element in elements:
        role = str(element.get("role", "unknown"))
        by_role[role] = by_role.get(role, 0) + 1

    return {
        "id": record.id,
        "snapshot_id": record.snapshot_id,
        "version": record.version,
        "elements": elements,
        "by_role": by_role,
        "summary": report if report is not None else record.summary,
        "confidence": record.confidence,
        "llm_provider": record.llm_provider,
        "llm_model": record.llm_model,
        "prompt_version": record.prompt_version,
        "edited_by_user": record.edited_by_user,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def analyze_now(html: str) -> tuple[PageAnalysis, str]:
    """Быстрый анализ без базы данных — используется в тестах и диагностике."""
    analysis = detector.analyze_html(html)
    return analysis, build_report(analysis)


def empty_analysis() -> PageAnalysis:
    """Пустой анализ — для снапшотов, где нечего разбирать."""
    return PageAnalysis(
        title=None,
        lang=None,
        meta={},
        counts={},
        elements=[],
        repeats=[],
        warnings=["страница пуста"],
    )


def analyzed_at() -> datetime:
    """Метка времени анализа."""
    return datetime.now(timezone.utc)
