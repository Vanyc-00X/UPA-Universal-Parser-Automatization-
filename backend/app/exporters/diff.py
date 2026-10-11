"""Сравнение двух запусков: что появилось, исчезло и изменилось."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunDiff:
    """Итог сравнения текущего запуска с предыдущим."""

    current_run_id: str
    previous_run_id: str
    added: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    changed: list[dict[str, Any]] = field(default_factory=list)
    unchanged: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "current_run_id": self.current_run_id,
            "previous_run_id": self.previous_run_id,
            "added": len(self.added),
            "removed": len(self.removed),
            "changed": len(self.changed),
            "unchanged": self.unchanged,
        }

    def as_dict(self) -> dict[str, Any]:
        payload = self.summary()
        payload["added_items"] = self.added[:200]
        payload["removed_items"] = self.removed[:200]
        payload["changed_items"] = self.changed[:200]
        return payload


def compare_runs(
    *,
    current_run_id: str,
    previous_run_id: str,
    current_items: list[Any],
    previous_items: list[Any],
) -> RunDiff:
    """Сравнивает записи по ключу дедупликации, затем по содержимому полей."""
    current_map = {_item_key(item): _payload(item) for item in current_items}
    previous_map = {_item_key(item): _payload(item) for item in previous_items}

    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    unchanged = 0

    for key, payload in current_map.items():
        if key not in previous_map:
            added.append(payload)
            continue
        before = previous_map[key]
        if before["data"] != payload["data"]:
            changed.append(
                {
                    "key": key,
                    "before": before["data"],
                    "after": payload["data"],
                }
            )
        else:
            unchanged += 1

    for key, payload in previous_map.items():
        if key not in current_map:
            removed.append(payload)

    return RunDiff(
        current_run_id=current_run_id,
        previous_run_id=previous_run_id,
        added=added,
        removed=removed,
        changed=changed,
        unchanged=unchanged,
    )


def _item_key(item: Any) -> str:
    dedup = getattr(item, "dedup_key", None)
    if dedup:
        return str(dedup)
    data = getattr(item, "data", None) or {}
    for key in ("url", "sku", "title"):
        value = data.get(key)
        if value not in (None, ""):
            return f"{key}:{value}"
    return f"pos:{getattr(item, 'position', 0)}"


def _payload(item: Any) -> dict[str, Any]:
    return {
        "position": getattr(item, "position", 0),
        "dedup_key": getattr(item, "dedup_key", None),
        "data": dict(getattr(item, "data", None) or {}),
    }
