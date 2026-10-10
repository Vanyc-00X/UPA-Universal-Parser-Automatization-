"""Файловые артефакты снапшота.

Всё тяжёлое (HTML, скриншоты, сетевые тела) лежит на диске в
``data/artifacts/<snapshot_id>/``, а в БД хранятся только пути и метаданные.
Такой расклад позволяет хранить тысячи снапшотов, не раздувая SQLite.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.crawler.browser import RawSnapshot

log = get_logger(__name__)

# Имена файлов внутри каталога снапшота.
PAGE_HTML = "page.html"
TRIMMED_HTML = "dom-trimmed.html"
NETWORK_JSON = "network.json"
DATA_SOURCES_JSON = "data-sources.json"
STORAGE_STATE_JSON = "storage-state.json"
SCREENSHOT_PNG = "screenshot.png"
SCREENSHOT_FULL_PNG = "screenshot-full.png"
SUMMARY_JSON = "summary.json"


@dataclass
class StoredArtifacts:
    """Сохранённые файлы: относительные пути и размеры."""

    rel_dir: str
    files: dict[str, str]
    sizes: dict[str, int]

    @property
    def disk_bytes(self) -> int:
        return sum(self.sizes.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "rel_dir": self.rel_dir,
            "files": self.files,
            "sizes": self.sizes,
            "disk_bytes": self.disk_bytes,
        }


def snapshot_dir(settings: Settings, snapshot_id: str) -> Path:
    """Каталог артефактов конкретного снапшота."""
    return settings.artifacts_dir / snapshot_id


def save_snapshot(
    settings: Settings,
    snapshot_id: str,
    snapshot: RawSnapshot,
) -> StoredArtifacts:
    """Сохраняет все артефакты снапшота на диск.

    Файлы пишутся атомарно (через временный каталог), чтобы прерванный процесс не
    оставил «полу-снапшот», который потом будет молча переиспользован из кэша.
    """
    target = snapshot_dir(settings, snapshot_id)
    staging = target.with_name(f"{snapshot_id}.tmp")
    if staging.exists():
        _remove_tree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {}
    sizes: dict[str, int] = {}

    def write(name: str, data: bytes | str) -> None:
        path = staging / name
        payload = data.encode("utf-8") if isinstance(data, str) else data
        path.write_bytes(payload)
        files[name] = f"{snapshot_id}/{name}"
        sizes[name] = len(payload)

    write(PAGE_HTML, snapshot.html)
    write(TRIMMED_HTML, snapshot.trimmed.html)

    network_payload = {
        "count": len(snapshot.network),
        "requests": [entry.as_dict() for entry in snapshot.network],
    }
    write(NETWORK_JSON, json.dumps(network_payload, ensure_ascii=False, indent=1))

    data_sources = {
        "count": len(snapshot.data_sources),
        "sources": [entry.as_dict() for entry in snapshot.data_sources],
    }
    write(DATA_SOURCES_JSON, json.dumps(data_sources, ensure_ascii=False, indent=1))

    if snapshot.storage_state:
        write(STORAGE_STATE_JSON, json.dumps(snapshot.storage_state, ensure_ascii=False, indent=1))

    if snapshot.screenshot:
        write(SCREENSHOT_PNG, snapshot.screenshot)
    if snapshot.screenshot_full:
        write(SCREENSHOT_FULL_PNG, snapshot.screenshot_full)

    write(SUMMARY_JSON, json.dumps(snapshot.summary(), ensure_ascii=False, indent=1))

    if target.exists():
        _remove_tree(target)
    staging.replace(target)

    log.info(
        "crawler.artifacts_saved",
        snapshot_id=snapshot_id,
        files=len(files),
        bytes=sum(sizes.values()),
    )
    return StoredArtifacts(rel_dir=snapshot_id, files=files, sizes=sizes)


def load_text(settings: Settings, snapshot_id: str, name: str) -> str | None:
    """Читает текстовый артефакт снапшота."""
    path = snapshot_dir(settings, snapshot_id) / name
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def load_json(settings: Settings, snapshot_id: str, name: str) -> Any | None:
    """Читает JSON-артефакт снапшота."""
    raw = load_text(settings, snapshot_id, name)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def load_bytes(settings: Settings, snapshot_id: str, name: str) -> bytes | None:
    """Читает бинарный артефакт (скриншот)."""
    path = snapshot_dir(settings, snapshot_id) / name
    if not path.is_file():
        return None
    return path.read_bytes()


def delete_snapshot_artifacts(settings: Settings, snapshot_id: str) -> bool:
    """Удаляет каталог артефактов снапшота."""
    target = snapshot_dir(settings, snapshot_id)
    if not target.exists():
        return False
    _remove_tree(target)
    return True


def _remove_tree(path: Path) -> None:
    """Удаляет каталог со всем содержимым."""
    import shutil

    shutil.rmtree(path, ignore_errors=True)
