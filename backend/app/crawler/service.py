"""Прикладной слой снапшотов: валидация URL, съёмка страницы, кэш.

Здесь связываются браузерный движок, обрезка DOM и хранилище. Этим модулем
пользуются API и (в дальнейшем) планировщик.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import session_scope
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.crawler import browser as browser_module
from app.crawler import store
from app.crawler.browser import RawSnapshot, hash_html
from app.storage.models import RunStatus, Site, Snapshot, SnapshotStatus, new_id

log = get_logger(__name__)

# Схемы, которые имеет смысл открывать в браузере.
ALLOWED_SCHEMES = {"http", "https"}

# Хосты, которые по умолчанию запрещены: локальная сеть и служебные адреса.
# Это защита от SSRF, когда приложение стоит на машине с внутренними сервисами.
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"}


@dataclass
class CaptureOutcome:
    """Результат съёмки: запись снапшота и сохранённые артефакты."""

    snapshot: Snapshot
    raw: RawSnapshot
    reused: bool = False


def normalize_url(raw: str) -> str:
    """Приводит введённый адрес к каноническому виду.

    Пользователь часто вставляет «example.com/catalog» без схемы, с лишним
    пробелом или с хвостовым «/». Приводим всё к одному виду, чтобы один и тот же
    сайт не создавал разные записи.
    """
    if not raw or not raw.strip():
        raise ValidationError("Укажите адрес сайта", details={"field": "url"})

    candidate = raw.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise ValidationError(
            "Поддерживаются только адреса http и https",
            details={"scheme": scheme, "url": raw},
        )
    if not parsed.netloc:
        raise ValidationError("В адресе не найден домен", details={"url": raw})

    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def origin_of(url: str) -> str:
    """Схема и домен без пути — используется как ключ сайта."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def check_host_allowed(url: str, *, allow_local: bool = False) -> None:
    """Запрещает локальные и служебные адреса, если это не разрешено явно."""
    if allow_local:
        return
    host = (urlparse(url).hostname or "").lower()
    if host in BLOCKED_HOSTS or host.startswith("192.168.") or host.startswith("10."):
        raise ValidationError(
            "Адрес указывает на локальную сеть. Разрешите это явно, если так и задумано",
            details={"host": host},
        )


async def get_or_create_site(session: AsyncSession, url: str) -> Site:
    """Находит сайт по origin или создаёт новую запись."""
    normalized = normalize_url(url)
    origin = origin_of(normalized)

    result = await session.execute(select(Site).where(Site.origin == origin))
    site = result.scalar_one_or_none()
    if site is not None:
        return site

    site = Site(url=normalized, origin=origin, last_visited_at=datetime.now(timezone.utc))
    session.add(site)
    await session.flush()
    log.info("crawler.site_created", site_id=site.id, origin=origin)
    return site


async def capture(
    session: AsyncSession,
    settings: Settings,
    url: str,
    *,
    site: Site | None = None,
    use_cache: bool = False,
    allow_local: bool = False,
) -> CaptureOutcome:
    """Снимает снапшот страницы и сохраняет его.

    При ``use_cache=True`` и совпадении хэша DOM с последним снапшотом артефакты
    не перезаписываются: результат отдаётся из кэша. Это делает повторный анализ
    быстрым и не создаёт лишнюю нагрузку на сайт.
    """
    normalized = normalize_url(url)
    check_host_allowed(normalized, allow_local=allow_local)
    site = site or await get_or_create_site(session, normalized)

    record = Snapshot(
        site_id=site.id,
        url=normalized,
        status=SnapshotStatus.RUNNING,
    )
    session.add(record)
    await session.flush()
    # Фиксируем запись до съёмки: иначе сбой страницы откатит и её, а статус сбоя
    # нужно сохранить в отдельной транзакции (см. _record_failure).
    await session.commit()

    try:
        raw = await browser_module.capture_page(settings, normalized)
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        # Отдельная транзакция: вызывающий код наверняка откатит свою, и тогда
        # запись о сбое исчезла бы. А знать о сбое нужно — иначе снапшот навсегда
        # останется в статусе «снимается».
        await _record_failure(record.id, error_text)
        log.warning("crawler.capture_failed", url=normalized, error=error_text)
        raise

    if use_cache:
        cached = await _find_cached(session, site.id, raw.dom_hash, exclude_id=record.id)
        if cached is not None:
            record.status = SnapshotStatus.READY
            record.final_url = raw.final_url
            record.http_status = raw.http_status
            record.title = raw.title
            record.lang = raw.lang
            record.dom_hash = raw.dom_hash
            record.html_bytes = raw.html_bytes
            record.trimmed_bytes = len(raw.trimmed.html.encode("utf-8"))
            record.est_tokens = raw.trimmed.stats.estimated_tokens
            record.collapsed_blocks = raw.trimmed.stats.collapsed_duplicates
            record.duration_ms = raw.duration_ms
            record.meta = {
                **raw.extra,
                **raw.summary(),
                "cache_hit": True,
                "cached_snapshot_id": cached.id,
            }
            # Артефакты переиспользуются один в один: набор файлов должен совпадать,
            # иначе UI покажет ссылки на несуществующие файлы.
            record.artifacts = dict(cached.artifacts or {})
            site.last_visited_at = datetime.now(timezone.utc)
            await session.flush()
            log.info(
                "crawler.cache_hit",
                snapshot_id=record.id,
                cached_snapshot_id=cached.id,
                dom_hash=raw.dom_hash,
            )
            return CaptureOutcome(snapshot=record, raw=raw, reused=True)

    stored = store.save_snapshot(settings, record.id, raw)
    record.status = SnapshotStatus.READY
    record.final_url = raw.final_url
    record.http_status = raw.http_status
    record.title = raw.title
    record.lang = raw.lang
    record.dom_hash = raw.dom_hash
    record.html_bytes = raw.html_bytes
    record.trimmed_bytes = len(raw.trimmed.html.encode("utf-8"))
    record.est_tokens = raw.trimmed.stats.estimated_tokens
    record.collapsed_blocks = raw.trimmed.stats.collapsed_duplicates
    record.duration_ms = raw.duration_ms
    record.artifacts = stored.files
    record.meta = {
        **raw.extra,
        **raw.summary(),
        "sizes": stored.sizes,
        "cache_hit": False,
        "captured_at": raw.extra.get("captured_at"),
    }
    site.last_visited_at = datetime.now(timezone.utc)
    if raw.title and not site.title:
        site.title = raw.title
    await session.flush()

    log.info(
        "crawler.captured",
        snapshot_id=record.id,
        url=normalized,
        dom_hash=raw.dom_hash,
        tokens=record.est_tokens,
    )
    return CaptureOutcome(snapshot=record, raw=raw)


async def _record_failure(snapshot_id: str, error_text: str) -> None:
    """Отмечает снапшот как неудавшийся в отдельной транзакции.

    Основная транзакция вызывающего кода будет откачена вместе с исключением,
    поэтому статус сбоя нужно сохранить независимо от неё.
    """
    try:
        async with session_scope() as failure_session:
            record = await failure_session.get(Snapshot, snapshot_id)
            if record is not None:
                record.status = SnapshotStatus.FAILED
                record.error = error_text
    except Exception as exc:  # noqa: BLE001 — запись о сбое не должна скрывать сбой
        log.error("crawler.failure_record_failed", snapshot_id=snapshot_id, error=str(exc))


async def _find_cached(
    session: AsyncSession,
    site_id: str,
    dom_hash: str,
    *,
    exclude_id: str,
) -> Snapshot | None:
    """Ищет готовый снапшот с тем же DOM."""
    result = await session.execute(
        select(Snapshot)
        .where(
            Snapshot.site_id == site_id,
            Snapshot.dom_hash == dom_hash,
            Snapshot.status == SnapshotStatus.READY,
            Snapshot.id != exclude_id,
        )
        .order_by(Snapshot.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_snapshot(session: AsyncSession, snapshot_id: str) -> Snapshot:
    """Возвращает снапшот или понятную ошибку 404."""
    snapshot = await session.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise NotFoundError("Снапшот не найден", details={"snapshot_id": snapshot_id})
    return snapshot


async def list_snapshots(
    session: AsyncSession,
    *,
    site_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Snapshot]:
    """Список снапшотов, свежие сверху."""
    statement = select(Snapshot).order_by(Snapshot.created_at.desc()).limit(limit).offset(offset)
    if site_id:
        statement = statement.where(Snapshot.site_id == site_id)
    result = await session.execute(statement)
    return list(result.scalars().all())


async def list_sites(session: AsyncSession, *, limit: int = 100, offset: int = 0) -> list[Site]:
    """Список сайтов, недавно посещённые сверху."""
    result = await session.execute(
        select(Site)
        .order_by(Site.last_visited_at.desc().nullslast(), Site.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def delete_snapshot(session: AsyncSession, settings: Settings, snapshot_id: str) -> None:
    """Удаляет снапшот вместе с его артефактами."""
    snapshot = await get_snapshot(session, snapshot_id)
    store.delete_snapshot_artifacts(settings, snapshot_id)
    await session.delete(snapshot)
    await session.flush()
    log.info("crawler.snapshot_deleted", snapshot_id=snapshot_id)


def raw_from_artifacts(
    settings: Settings,
    snapshot: Snapshot,
) -> RawSnapshot | None:
    """Собирает :class:`RawSnapshot` обратно из файлов — для анализа из кэша.

    Возвращает ``None``, если артефакты недоступны (удалены вручную или при
    очистке по политике ретенции). Вызывающий код в этом случае должен снять
    снапшот заново.
    """
    html = store.load_text(settings, snapshot.id, store.PAGE_HTML)
    trimmed = store.load_text(settings, snapshot.id, store.TRIMMED_HTML)
    if html is None or trimmed is None:
        return None

    network_payload = store.load_json(settings, snapshot.id, store.NETWORK_JSON) or {}
    entries = [
        browser_module.NetworkEntry(
            url=item.get("url", ""),
            method=item.get("method", "GET"),
            resource_type=item.get("resource_type", ""),
            status=item.get("status"),
            mime=item.get("mime"),
            size_bytes=item.get("size_bytes"),
            body=item.get("body"),
            body_truncated=bool(item.get("body_truncated")),
            error=item.get("error"),
        )
        for item in network_payload.get("requests", [])
    ]

    from app.crawler.dom import trim_html

    trim_result = trim_html(html, max_tokens=settings.dom_max_tokens, base_url=snapshot.final_url)
    return RawSnapshot(
        url=snapshot.url,
        final_url=snapshot.final_url or snapshot.url,
        http_status=snapshot.http_status,
        title=snapshot.title,
        lang=snapshot.lang,
        html=html,
        dom_hash=snapshot.dom_hash or hash_html(html),
        trimmed=trim_result,
        html_bytes=snapshot.html_bytes or len(html.encode("utf-8")),
        screenshot=store.load_bytes(settings, snapshot.id, store.SCREENSHOT_PNG),
        screenshot_full=store.load_bytes(settings, snapshot.id, store.SCREENSHOT_FULL_PNG),
        network=entries,
        storage_state=store.load_json(settings, snapshot.id, store.STORAGE_STATE_JSON),
        console_errors=list((snapshot.meta or {}).get("console_errors", [])),
        blocked_requests=int((snapshot.meta or {}).get("blocked_requests", 0) or 0),
        cookie_banner_closed=bool((snapshot.meta or {}).get("cookie_banner_closed", False)),
        duration_ms=snapshot.duration_ms or 0,
        viewport=dict((snapshot.meta or {}).get("viewport", {})),
        extra=dict(snapshot.meta or {}),
    )


def run_status_for_failure() -> RunStatus:
    """Статус запуска при сбое — используется планировщиком на Этапе 6."""
    return RunStatus.FAILED


def unique_id() -> str:
    """Идентификатор для артефактов, которые создаются до записи в БД."""
    return new_id()
