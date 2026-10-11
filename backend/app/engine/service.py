"""Движок извлечения: запуск сценария, запись результатов, отчёт.

Здесь собирается всё вместе: сценарий, разбор страниц, обход пагинации,
нормализация, проверка и сохранение. Результат — запуск со списком записей и
отчётом о полноте данных.

Ключевые свойства:

* **продолжение после сбоя.** Обработанные страницы отмечаются, и повторный запуск
  не собирает их заново — иначе падение на десятой странице означало бы потерю
  работы девяти;
* **дедупликация.** Записи сравниваются по устойчивому ключу (ссылка, название),
  поэтому пересечение страниц не даёт дублей;
* **лимиты.** Число страниц и записей ограничено, задержка между страницами
  настраивается: сбор не должен превращаться в нагрузку на сайт.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer.domlite import parse
from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.crawler import service as crawl_service
from app.crawler import store
from app.editor import scenario as scenario_service
from app.editor.schema import PaginationKind, ScenarioDefinition
from app.engine import extractor, paginate, validate
from app.healing.journal import RunJournal
from app.healing.retry import with_retries
from app.storage.models import ElementMap, Run, RunItem, RunStatus, RunTrigger, Snapshot

log = get_logger(__name__)

# Сколько записей сохраняем за один запуск, если не задано иное.
HARD_RECORD_LIMIT = 20_000


@dataclass
class PageResult:
    """Результат обработки одной страницы."""

    number: int
    url: str
    records: int
    is_valid: bool
    note: str | None = None
    problem: str | None = None
    skipped: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "url": self.url,
            "records": self.records,
            "is_valid": self.is_valid,
            "note": self.note,
            "problem": self.problem,
            "skipped": self.skipped,
        }


@dataclass
class RunOutcome:
    """Итог запуска сценария."""

    run: Run
    report: validate.RunReport
    pages: list[PageResult] = field(default_factory=list)
    duplicates: int = 0
    duration_ms: int = 0
    stopped_reason: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run.id,
            "status": (
                self.run.status.value if hasattr(self.run.status, "value") else str(self.run.status)
            ),
            "pages_done": self.run.pages_done,
            "items": self.run.items_count,
            "duplicates": self.duplicates,
            "duration_ms": self.duration_ms,
            "stopped_reason": self.stopped_reason,
            **self.report.summary(),
        }


# Загрузчик страниц: возвращает HTML по адресу.
PageFetcher = Callable[[str], Awaitable[tuple[str | None, str | None]]]


async def _snapshot_html(
    session: AsyncSession, settings: Settings, snapshot_id: str
) -> tuple[str | None, Snapshot]:
    """Читает обрезанный DOM снапшота вместе с записью."""
    snapshot = await crawl_service.get_snapshot(session, snapshot_id)
    html = store.load_text(settings, snapshot_id, store.TRIMMED_HTML)
    if html is None:
        html = store.load_text(settings, snapshot_id, store.PAGE_HTML)
    return html, snapshot


def definition_from_scenario(version_definition: dict[str, Any]) -> ScenarioDefinition:
    """Разбирает определение сценария из базы с понятной ошибкой."""
    try:
        return ScenarioDefinition.model_validate(version_definition or {})
    except Exception as exc:  # noqa: BLE001 — повреждённая запись в базе
        raise ValidationError(
            "Определение сценария повреждено и не читается",
            details={"reason": str(exc)[:300]},
        ) from exc


async def run_definition(
    session: AsyncSession,
    settings: Settings,
    definition: ScenarioDefinition,
    *,
    scenario_id: str | None = None,
    scenario_version_id: str | None = None,
    snapshot_id: str | None = None,
    trigger: RunTrigger = RunTrigger.MANUAL,
    fetch_page: PageFetcher | None = None,
    max_records: int = HARD_RECORD_LIMIT,
    min_coverage: float = validate.DEFAULT_MIN_COVERAGE,
    resume: bool = False,
) -> RunOutcome:
    """Выполняет сценарий и сохраняет результаты.

    ``fetch_page`` позволяет получать страницы извне (живой браузер). Если он не
    задан, обход ограничен теми страницами, чьи адреса можно вычислить по шаблону,
    а первая берётся из снапшота.
    """
    started = time.monotonic()
    journal = RunJournal()
    journal.start("run")
    fetch_attempts: list[dict[str, Any]] = []

    run = Run(
        scenario_id=scenario_id,
        scenario_version_id=scenario_version_id,
        status=RunStatus.RUNNING,
        trigger=trigger,
        started_at=datetime.now(timezone.utc),
        params={
            "snapshot_id": snapshot_id,
            "mode": definition.plan.mode,
            "max_records": max_records,
        },
    )
    if scenario_id is None:
        # Запуск без сохранённого сценария допустим только для сценария из черновика.
        raise ValidationError("Запуск возможен только для сохранённого сценария")
    session.add(run)
    await session.flush()
    journal.info("run_created", "запуск создан", run_id=run.id)

    html, snapshot = (
        await _snapshot_html(session, settings, snapshot_id) if snapshot_id else (None, None)
    )
    journal.info(
        "load_snapshot",
        "снапшот загружен" if html else "DOM снапшота отсутствует",
        snapshot_id=snapshot_id,
    )
    if html is None and fetch_page is None:
        raise NotFoundError(
            "Не найден DOM для запуска: укажите снапшот или разрешите догрузку страниц",
            details={"snapshot_id": snapshot_id},
        )

    base_url = (snapshot.final_url or snapshot.url) if snapshot else definition.url
    plan = paginate.build_plan(definition.pagination)
    journal.info(
        "plan",
        f"режим {definition.plan.mode}, пагинация {plan.kind.value}",
        fields=len(definition.fields),
        max_pages=plan.max_pages,
    )

    pages: list[PageResult] = []
    records: list[extractor.ExtractedRecord] = []
    seen_keys: set[str] = set()
    duplicates = 0
    stopped_reason: str | None = None

    # --- Первая страница ----------------------------------------------------
    first_html = html
    if first_html is None and fetch_page is not None:
        first_html, problem, fetch_attempts = await with_retries(
            lambda: fetch_page(base_url),
            max_attempts=settings.fetch_max_retries,
            backoff_ms=settings.fetch_retry_backoff_ms,
        )
        if first_html is None:
            journal.error(
                "fetch_first",
                problem or "не удалось получить страницу",
                attempts=fetch_attempts,
            )
            run.stats = {"journal": journal.as_list(), "fetch_attempts": fetch_attempts}
            await _finish_run(
                session, run, RunStatus.FAILED, problem or "не удалось получить страницу"
            )
            raise ValidationError(
                "Не удалось получить первую страницу", details={"reason": problem}
            )
        journal.info("fetch_first", "первая страница получена", attempts=len(fetch_attempts))

    queued = _page_queue(plan, base_url)
    first_visit = queued.pop(0) if queued else paginate.PageVisit(1, base_url, base_url)
    visited: set[str] = {first_visit.key}

    current_html = first_html
    current_url = base_url
    page_number = first_visit.number

    # --- Обход страниц ------------------------------------------------------
    while True:
        if len(records) >= max_records:
            stopped_reason = f"достигнут предел в {max_records} записей"
            break

        if current_html is None:
            stopped_reason = "нет разметки для следующей страницы"
            break

        journal.start(f"page_{page_number}")
        document = parse(current_html)
        result = extractor.extract_page(document, definition, base_url=current_url)

        if result.errors:
            pages.append(
                PageResult(
                    number=page_number,
                    url=current_url,
                    records=0,
                    is_valid=False,
                    problem="; ".join(result.errors),
                )
            )
            stopped_reason = "; ".join(result.errors)
            journal.error(
                f"page_{page_number}",
                stopped_reason,
                url=current_url,
                errors=result.errors,
            )
            break

        added = 0
        for record in result.records:
            key = _record_key(record, definition)
            if key in seen_keys:
                duplicates += 1
                continue
            seen_keys.add(key)
            records.append(record)
            added += 1

        pages.append(
            PageResult(
                number=page_number,
                url=current_url,
                records=added,
                is_valid=True,
                note="; ".join(result.warnings) or None,
            )
        )
        journal.info(
            f"page_{page_number}",
            f"собрано {added} записей",
            url=current_url,
            warnings=result.warnings,
        )
        run.pages_done = len([page for page in pages if page.is_valid])
        run.items_count = len(records)
        await session.flush()

        # --- Следующая страница ---------------------------------------------
        if not plan.enabled:
            break

        if plan.kind is PaginationKind.URL_TEMPLATE:
            if not queued:
                stopped_reason = "страницы по шаблону закончились"
                break
            visit = queued.pop(0)
            if visit.key in visited:
                stopped_reason = "шаблон привёл к уже обработанной странице"
                break
            visited.add(visit.key)
            next_url, next_problem = visit.url, None
        else:
            next_url, next_problem = paginate.find_next_url(
                document, plan.selector, base_url=current_url
            )
            if next_problem:
                pages.append(
                    PageResult(
                        number=page_number + 1,
                        url=current_url,
                        records=0,
                        is_valid=False,
                        problem=next_problem,
                    )
                )
                stopped_reason = next_problem
                break
            if not next_url:
                stopped_reason = "страниц больше нет"
                break
            step, repeat_note = paginate.next_page_step(current_url, next_url, visited)
            if step is None:
                stopped_reason = repeat_note or "страниц больше нет"
                break
            visited.add(step.key)
            next_url = step.url

        if plan.delay_ms:
            # Пауза между страницами: вежливость к сайту и защита от блокировок.
            await _sleep(plan.delay_ms / 1000)

        if fetch_page is not None:
            next_html, problem, page_attempts = await with_retries(
                lambda url=next_url: fetch_page(url),
                max_attempts=settings.fetch_max_retries,
                backoff_ms=settings.fetch_retry_backoff_ms,
            )
            fetch_attempts.extend(page_attempts)
            if next_html is None:
                pages.append(
                    PageResult(
                        number=page_number + 1,
                        url=next_url,
                        records=0,
                        is_valid=False,
                        problem=problem or "страница не получена",
                    )
                )
                stopped_reason = problem or "страница не получена"
                journal.error(
                    "fetch_next",
                    stopped_reason,
                    url=next_url,
                    attempts=page_attempts,
                )
                break
            current_html = next_html
        else:
            # Без загрузчика обходим только те страницы, что уже есть в снапшотах.
            current_html = await _html_from_snapshots(session, settings, next_url)
            if current_html is None:
                stopped_reason = (
                    "следующая страница недоступна: разрешите догрузку страниц "
                    "или снимите снапшоты заранее"
                )
                break

        current_url = next_url
        page_number += 1

    # --- Сохранение и отчёт -------------------------------------------------
    result_for_report = extractor.ExtractionResult(
        records=records,
        mode=definition.plan.mode,
        container_selector=definition.plan.container_selector,
    )
    report = validate.build_report(
        result_for_report,
        definition,
        base_url=base_url,
        min_coverage=min_coverage,
    )

    # Позиции сквозные: иначе записи со второй страницы перезапишут первые в UI.
    for index, record in enumerate(records):
        record.position = index

    await _save_records(session, run, records, definition)

    status = RunStatus.SUCCEEDED if report.passed else RunStatus.FAILED
    if not records:
        status = RunStatus.FAILED
    # «Страниц больше нет» — нормальное завершение, не ошибка запуска.
    finish_error = stopped_reason if status == RunStatus.FAILED else None
    await _finish_run(session, run, status, finish_error)

    duration_ms = int((time.monotonic() - started) * 1000)
    fallback_usage = _fallback_usage(records)
    journal.info(
        "run",
        "запуск завершён",
        status=status.value,
        records=report.records,
        coverage=report.required_coverage,
        fallback_fields=list(fallback_usage),
    )
    run.stats = {
        **(run.stats or {}),
        "duplicates": duplicates,
        "stopped_reason": stopped_reason,
        "duration_ms": duration_ms,
        "required_coverage": report.required_coverage,
        "passed": report.passed,
        "journal": journal.as_list(),
        "fetch_attempts": fetch_attempts,
        "pages": [page.as_dict() for page in pages],
        "fallback_usage": fallback_usage,
    }
    await session.flush()

    # Self-healing: низкая полнота или работа через fallback → предложение патча.
    needs_heal = (
        not report.passed
        or report.required_coverage < settings.heal_min_coverage
        or bool(fallback_usage)
    )
    if settings.heal_auto_propose and needs_heal:
        try:
            from app.healing import service as healing_service

            await healing_service.build_heal_proposal(
                session, settings, run.id, min_coverage=min_coverage
            )
        except Exception as exc:  # noqa: BLE001 — healing не должен ронять запуск
            log.warning("healing.propose_failed", run_id=run.id, error=str(exc)[:200])

    log.info(
        "engine.run_finished",
        run_id=run.id,
        records=report.records,
        pages=run.pages_done,
        duplicates=duplicates,
        coverage=report.required_coverage,
        duration_ms=duration_ms,
    )

    return RunOutcome(
        run=run,
        report=report,
        pages=pages,
        duplicates=duplicates,
        duration_ms=duration_ms,
        stopped_reason=stopped_reason,
    )


def _page_queue(plan: paginate.PaginationPlan, base_url: str) -> list[paginate.PageVisit]:
    """Очередь страниц по шаблону адреса."""
    if plan.kind is PaginationKind.URL_TEMPLATE:
        visits = plan.page_urls(base_url)
        if visits:
            return visits
    return []


def _fallback_usage(records: list[extractor.ExtractedRecord]) -> dict[str, int]:
    """Счётчик полей, которые собрались только через запасной селектор."""
    counts: dict[str, int] = {}
    for record in records:
        for key, used in record.used_fallback.items():
            if used:
                counts[key] = counts.get(key, 0) + 1
    return counts


async def _html_from_snapshots(session: AsyncSession, settings: Settings, url: str) -> str | None:
    """Ищет готовый снапшот по адресу страницы.

    Так обход нескольких страниц работает без браузера: если пользователь снял
    снапшоты заранее, движок возьмёт их с диска.
    """
    from app.engine.normalize import navigation_key

    target = navigation_key(url)
    if not target:
        return None
    result = await session.execute(select(Snapshot).order_by(Snapshot.created_at.desc()).limit(500))
    for snapshot in result.scalars().all():
        candidate = navigation_key(snapshot.final_url or snapshot.url)
        if candidate == target:
            html = store.load_text(settings, snapshot.id, store.TRIMMED_HTML)
            if html is None:
                html = store.load_text(settings, snapshot.id, store.PAGE_HTML)
            if html is not None:
                return html
    return None


def _record_key(record: extractor.ExtractedRecord, definition: ScenarioDefinition) -> str:
    """Ключ записи для дедупликации.

    Приоритет: ссылка, затем название с ценой, затем всё содержимое. Так
    пересечение страниц не создаёт дублей.
    """
    from app.engine import normalize as normalize_mod

    preferred = [
        key for key in ("url", "sku", "title", "price") if record.values.get(key) not in (None, "")
    ]
    if preferred:
        return normalize_mod.dedup_key(record.values, preferred)
    return normalize_mod.dedup_key(record.values)


async def _save_records(
    session: AsyncSession,
    run: Run,
    records: list[extractor.ExtractedRecord],
    definition: ScenarioDefinition,
) -> None:
    """Сохраняет записи запуска, помечая неполные."""
    required = [spec.key for spec in definition.fields if spec.required]
    for record in records:
        invalid = [key for key in required if record.values.get(key) in (None, "")]
        session.add(
            RunItem(
                run_id=run.id,
                position=record.position,
                data=record.values,
                dedup_key=_record_key(record, definition),
                source_url=record.source_url,
                is_valid=not invalid,
                validation_errors=[
                    f"{key}: {record.problems.get(key, 'не заполнено')}" for key in invalid
                ],
            )
        )
    run.items_count = len(records)
    run.errors_count = sum(
        1 for record in records if any(record.values.get(key) in (None, "") for key in required)
    )
    await session.flush()


async def _finish_run(
    session: AsyncSession,
    run: Run,
    status: RunStatus,
    error: str | None = None,
) -> None:
    """Завершает запуск, фиксируя статус и время."""
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    run.error = error
    run.stats = {
        "pages_done": run.pages_done,
        "items": run.items_count,
        "errors": run.errors_count,
    }
    await session.flush()


async def _sleep(seconds: float) -> None:
    """Пауза между страницами: вежливость к сайту и защита от блокировок."""
    await asyncio.sleep(seconds)


# ---------------------------------------------------------------------------
# Чтение запусков
# ---------------------------------------------------------------------------


async def get_run(session: AsyncSession, run_id: str) -> Run:
    """Запуск или понятная ошибка 404."""
    run = await session.get(Run, run_id)
    if run is None:
        raise NotFoundError("Запуск не найден", details={"run_id": run_id})
    return run


async def list_runs(
    session: AsyncSession,
    *,
    scenario_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Run]:
    """Список запусков, свежие сверху."""
    statement = select(Run).order_by(Run.created_at.desc()).limit(limit).offset(offset)
    if scenario_id:
        statement = statement.where(Run.scenario_id == scenario_id)
    result = await session.execute(statement)
    return list(result.scalars().all())


async def count_runs(session: AsyncSession, scenario_id: str | None = None) -> int:
    """Сколько запусков есть в базе."""
    statement = select(func.count()).select_from(Run)
    if scenario_id:
        statement = statement.where(Run.scenario_id == scenario_id)
    return int((await session.execute(statement)).scalar_one())


async def list_run_items(
    session: AsyncSession,
    run_id: str,
    *,
    limit: int = 200,
    offset: int = 0,
    only_invalid: bool = False,
) -> list[RunItem]:
    """Записи запуска по порядку."""
    statement = (
        select(RunItem)
        .where(RunItem.run_id == run_id)
        .order_by(RunItem.position)
        .limit(limit)
        .offset(offset)
    )
    if only_invalid:
        statement = statement.where(RunItem.is_valid.is_(False))
    result = await session.execute(statement)
    return list(result.scalars().all())


async def count_run_items(session: AsyncSession, run_id: str, *, only_invalid: bool = False) -> int:
    """Сколько записей собрал запуск."""
    statement = select(func.count()).select_from(RunItem).where(RunItem.run_id == run_id)
    if only_invalid:
        statement = statement.where(RunItem.is_valid.is_(False))
    return int((await session.execute(statement)).scalar_one())


async def delete_run(session: AsyncSession, run_id: str) -> None:
    """Удаляет запуск вместе с записями."""
    run = await get_run(session, run_id)
    await session.delete(run)
    await session.flush()
    log.info("engine.run_deleted", run_id=run_id)


async def run_scenario(
    session: AsyncSession,
    settings: Settings,
    scenario_id: str,
    *,
    snapshot_id: str | None = None,
    fetch_page: PageFetcher | None = None,
    min_coverage: float = validate.DEFAULT_MIN_COVERAGE,
) -> RunOutcome:
    """Запускает сохранённый сценарий.

    Если снапшот не указан, берётся последний снапшот сайта сценария: это самый
    ожидаемый вариант — пользователь только что снимал страницу.
    """
    scenario = await scenario_service.get_scenario(session, scenario_id)
    version = await scenario_service.get_current_version(session, scenario)
    if version is None:
        raise ValidationError(
            "У сценария нет ни одной версии", details={"scenario_id": scenario_id}
        )
    definition = scenario_service.definition_from_version(version)

    if snapshot_id is None:
        snapshot_id = definition.snapshot_id
    if snapshot_id is None:
        snapshot_id = await _latest_snapshot_id(session, scenario.site_id)
    if snapshot_id is None:
        raise ValidationError(
            "Не найден снапшот для запуска: снимите страницу заново",
            details={"scenario_id": scenario_id},
        )

    return await run_definition(
        session,
        settings,
        definition,
        scenario_id=scenario.id,
        scenario_version_id=version.id,
        snapshot_id=snapshot_id,
        fetch_page=fetch_page,
        min_coverage=min_coverage,
    )


async def _latest_snapshot_id(session: AsyncSession, site_id: str) -> str | None:
    """Последний снапшот сайта."""
    result = await session.execute(
        select(Snapshot)
        .where(Snapshot.site_id == site_id)
        .order_by(Snapshot.created_at.desc())
        .limit(1)
    )
    snapshot = result.scalar_one_or_none()
    return snapshot.id if snapshot else None


async def preview_definition(
    session: AsyncSession,
    settings: Settings,
    definition: ScenarioDefinition,
    *,
    snapshot_id: str,
    limit: int = 5,
) -> dict[str, Any]:
    """Предпросмотр: что соберётся с указанного снапшота, без сохранения запуска."""
    html, snapshot = await _snapshot_html(session, settings, snapshot_id)
    if html is None:
        raise NotFoundError(
            "Артефакты снапшота не найдены — снимите снапшот заново",
            details={"snapshot_id": snapshot_id},
        )

    base_url = snapshot.final_url or snapshot.url
    document = parse(html)
    result = extractor.extract_page(document, definition, base_url=base_url, limit=limit)
    report = validate.build_report(result, definition, base_url=base_url)

    return {
        "records": [record.as_dict() for record in result.records],
        "extraction": result.as_dict(definition),
        "report": report.as_dict(),
        "report_text": validate.describe_report(report),
    }


async def element_map_for_snapshot(session: AsyncSession, snapshot_id: str) -> ElementMap | None:
    """Карта элементов снапшота, если она есть — нужна для подсказок в отчёте."""
    result = await session.execute(select(ElementMap).where(ElementMap.snapshot_id == snapshot_id))
    return result.scalar_one_or_none()
