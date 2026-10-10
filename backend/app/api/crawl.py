"""Эндпоинты Этапа 1: сайты, снапшоты, сетевые запросы, артефакты."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crawl_schemas import (
    NetworkRequestOut,
    SiteListResponse,
    SiteOut,
    SnapshotCaptureRequest,
    SnapshotDeleteResponse,
    SnapshotDetailOut,
    SnapshotDomResponse,
    SnapshotListResponse,
    SnapshotNetworkResponse,
    SnapshotSummaryOut,
)
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import NotFoundError
from app.crawler import service as crawl
from app.crawler import store
from app.storage.models import Site, Snapshot

router = APIRouter(tags=["crawl"])


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _artifact_urls(snapshot_id: str, artifacts: dict[str, str]) -> dict[str, str]:
    """Ссылки на скачивание артефактов, ключ — имя файла.

    Ключ совпадает с именем артефакта, потому что эндпоинт скачивания принимает
    именно имя файла из белого списка.
    """
    return {name: f"/api/v1/snapshots/{snapshot_id}/artifacts/{name}" for name in artifacts}


def _summary(snapshot: Snapshot) -> SnapshotSummaryOut:
    """Преобразует запись снапшота в краткое представление."""
    meta: dict[str, Any] = snapshot.meta or {}
    network_count = int(meta.get("network_requests", 0) or 0)
    data_sources = int(meta.get("data_sources", 0) or 0)

    return SnapshotSummaryOut(
        id=snapshot.id,
        site_id=snapshot.site_id,
        url=snapshot.url,
        final_url=snapshot.final_url,
        status=snapshot.status.value if hasattr(snapshot.status, "value") else str(snapshot.status),
        http_status=snapshot.http_status,
        title=snapshot.title,
        lang=snapshot.lang,
        dom_hash=snapshot.dom_hash,
        html_bytes=snapshot.html_bytes,
        trimmed_bytes=snapshot.trimmed_bytes,
        est_tokens=snapshot.est_tokens,
        duration_ms=snapshot.duration_ms,
        error=snapshot.error,
        created_at=snapshot.created_at,
        data_sources_count=data_sources,
        network_count=network_count,
        compression_ratio=meta.get("compression_ratio"),
        cache_hit=bool(meta.get("cache_hit")),
    )


@router.post(
    "/snapshots",
    response_model=SnapshotDetailOut,
    summary="Снять снапшот страницы",
    description=(
        "Открывает URL в Chromium, дожидается сети и JS, закрывает баннеры о cookie "
        "и сохраняет DOM, скриншоты, сетевые запросы и storage state."
    ),
)
async def create_snapshot(
    payload: SnapshotCaptureRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SnapshotDetailOut:
    settings = _settings(request)
    outcome = await crawl.capture(
        db,
        settings,
        payload.url,
        use_cache=payload.use_cache,
        allow_local=payload.allow_local,
    )
    return await _detail(settings, outcome.snapshot, reused=outcome.reused)


@router.get(
    "/snapshots",
    response_model=SnapshotListResponse,
    summary="Список снапшотов",
)
async def list_snapshots(
    db: AsyncSession = Depends(get_db),
    site_id: str | None = Query(None, description="Фильтр по сайту"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> SnapshotListResponse:
    items = await crawl.list_snapshots(db, site_id=site_id, limit=limit, offset=offset)
    statement = select(func.count()).select_from(Snapshot)
    if site_id:
        statement = statement.where(Snapshot.site_id == site_id)
    total = int((await db.execute(statement)).scalar_one())
    return SnapshotListResponse(items=[_summary(item) for item in items], total=total)


@router.get(
    "/snapshots/{snapshot_id}",
    response_model=SnapshotDetailOut,
    summary="Сведения о снапшоте",
)
async def get_snapshot(
    snapshot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SnapshotDetailOut:
    snapshot = await crawl.get_snapshot(db, snapshot_id)
    return await _detail(_settings(request), snapshot)


@router.get(
    "/snapshots/{snapshot_id}/dom",
    response_model=SnapshotDomResponse,
    summary="HTML снапшота",
    description="variant=trimmed (по умолчанию) — то, что уходит в модель; full — исходный DOM.",
)
async def get_snapshot_dom(
    snapshot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    variant: str = Query("trimmed", pattern="^(trimmed|full)$"),
) -> SnapshotDomResponse:
    settings = _settings(request)
    # Существование снапшота проверяем до чтения файла, но сама запись не нужна.
    await crawl.get_snapshot(db, snapshot_id)
    name = store.TRIMMED_HTML if variant == "trimmed" else store.PAGE_HTML
    html = store.load_text(settings, snapshot_id, name)
    if html is None:
        raise NotFoundError(
            "Артефакт снапшота не найден на диске",
            details={"snapshot_id": snapshot_id, "artifact": name},
        )
    from app.crawler.dom import estimate_tokens

    return SnapshotDomResponse(
        snapshot_id=snapshot_id,
        variant=variant,  # type: ignore[arg-type]
        bytes=len(html.encode("utf-8")),
        est_tokens=estimate_tokens(html),
        html=html,
    )


@router.get(
    "/snapshots/{snapshot_id}/network",
    response_model=SnapshotNetworkResponse,
    summary="Сетевые запросы снапшота",
)
async def get_snapshot_network(
    snapshot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    data_sources_only: bool = Query(False, description="Только ответы с данными (JSON/XHR)"),
) -> SnapshotNetworkResponse:
    settings = _settings(request)
    await crawl.get_snapshot(db, snapshot_id)
    name = store.DATA_SOURCES_JSON if data_sources_only else store.NETWORK_JSON
    payload = store.load_json(settings, snapshot_id, name)
    if payload is None:
        # Откат к общему файлу, если отдельный список источников не сохранён.
        payload = store.load_json(settings, snapshot_id, store.NETWORK_JSON) or {"requests": []}

    requests = payload.get("requests") or payload.get("sources") or []
    if data_sources_only and payload.get("sources") is None:
        # Откат к общему network.json — фильтруем самостоятельно. В data-sources.json
        # источники уже отфильтрованы на этапе сохранения снапшота.
        requests = [
            item
            for item in requests
            if item.get("resource_type") in {"xhr", "fetch"}
            and item.get("status") == 200
            and "json" in (item.get("mime") or "")
        ]
    items = [
        NetworkRequestOut(
            url=item.get("url", ""),
            method=item.get("method", "GET"),
            resource_type=item.get("resource_type", ""),
            status=item.get("status"),
            mime=item.get("mime"),
            size_bytes=item.get("size_bytes"),
            body_truncated=bool(item.get("body_truncated")),
            is_data_source=item.get("resource_type") in {"xhr", "fetch"}
            and item.get("status") == 200
            and "json" in (item.get("mime") or ""),
            has_body=item.get("body") is not None,
            error=item.get("error"),
        )
        for item in requests
    ]
    return SnapshotNetworkResponse(snapshot_id=snapshot_id, total=len(items), items=items)


@router.get(
    "/snapshots/{snapshot_id}/artifacts/{artifact}",
    summary="Скачать артефакт снапшота",
    response_class=Response,
)
async def download_artifact(
    snapshot_id: str,
    artifact: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    settings = _settings(request)
    await crawl.get_snapshot(db, snapshot_id)

    # Белый список: имя файла не приходит от клиента напрямую.
    allowed = {
        store.PAGE_HTML,
        store.TRIMMED_HTML,
        store.NETWORK_JSON,
        store.DATA_SOURCES_JSON,
        store.STORAGE_STATE_JSON,
        store.SCREENSHOT_PNG,
        store.SCREENSHOT_FULL_PNG,
        store.SUMMARY_JSON,
    }
    if artifact not in allowed:
        raise NotFoundError("Неизвестный артефакт", details={"artifact": artifact})

    data = store.load_bytes(settings, snapshot_id, artifact)
    if data is None:
        raise NotFoundError(
            "Артефакт не найден на диске",
            details={"snapshot_id": snapshot_id, "artifact": artifact},
        )

    mime = "image/png" if artifact.endswith(".png") else "application/json"
    if artifact.endswith(".html"):
        mime = "text/html; charset=utf-8"
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'inline; filename="{snapshot_id}-{artifact}"'},
    )


@router.delete(
    "/snapshots/{snapshot_id}",
    response_model=SnapshotDeleteResponse,
    summary="Удалить снапшот и его артефакты",
)
async def delete_snapshot(
    snapshot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SnapshotDeleteResponse:
    await crawl.delete_snapshot(db, _settings(request), snapshot_id)
    return SnapshotDeleteResponse(snapshot_id=snapshot_id, deleted=True)


@router.get(
    "/sites",
    response_model=SiteListResponse,
    summary="Список сайтов",
)
async def list_sites(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> SiteListResponse:
    sites = await crawl.list_sites(db, limit=limit, offset=offset)
    counts = dict(
        (await db.execute(select(Snapshot.site_id, func.count()).group_by(Snapshot.site_id))).all()
    )
    total = int((await db.execute(select(func.count()).select_from(Site))).scalar_one())
    return SiteListResponse(
        items=[
            SiteOut(
                id=site.id,
                url=site.url,
                origin=site.origin,
                title=site.title,
                label=site.label,
                notes=site.notes,
                last_visited_at=site.last_visited_at,
                created_at=site.created_at,
                snapshots_count=int(counts.get(site.id, 0)),
            )
            for site in sites
        ],
        total=total,
    )


@router.get(
    "/sites/{site_id}",
    response_model=SiteOut,
    summary="Сведения о сайте",
)
async def get_site(site_id: str, db: AsyncSession = Depends(get_db)) -> SiteOut:
    site = await db.get(Site, site_id)
    if site is None:
        raise NotFoundError("Сайт не найден", details={"site_id": site_id})
    count = int(
        (
            await db.execute(
                select(func.count()).select_from(Snapshot).where(Snapshot.site_id == site_id)
            )
        ).scalar_one()
    )
    return SiteOut(
        id=site.id,
        url=site.url,
        origin=site.origin,
        title=site.title,
        label=site.label,
        notes=site.notes,
        last_visited_at=site.last_visited_at,
        created_at=site.created_at,
        snapshots_count=count,
    )


async def _detail(
    settings: Settings,
    snapshot: Snapshot,
    *,
    reused: bool = False,
) -> SnapshotDetailOut:
    """Собирает детальное представление снапшота, читая статистику с диска."""
    base = _summary(snapshot)
    summary = store.load_json(settings, snapshot.id, store.SUMMARY_JSON) or {}
    meta: dict[str, Any] = dict(snapshot.meta or {})
    artifacts = dict(snapshot.artifacts or {})

    data = base.model_dump()
    data.update(
        {
            "trim": summary or meta.get("trim", {}),
            "meta": meta,
            "artifacts": artifacts,
            "artifact_urls": _artifact_urls(snapshot.id, artifacts),
            "console_errors": list(meta.get("console_errors", [])),
            "failed_requests": list(meta.get("failed_requests", [])),
            "cookie_banner_closed": bool(meta.get("cookie_banner_closed", False)),
            "viewport": dict(meta.get("viewport", {})),
            "cache_hit": bool(meta.get("cache_hit")) or reused,
        }
    )
    return SnapshotDetailOut(**data)
