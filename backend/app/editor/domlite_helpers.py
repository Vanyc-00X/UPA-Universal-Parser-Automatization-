"""Вспомогательные функции редактора для работы с разметкой напрямую.

Нужны там, где нет базы и снапшота: в тестах и в диагностических скриптах.
Позволяют проверить сценарий на произвольном HTML — удобно при отладке
селекторов.
"""

from __future__ import annotations

from typing import Any

from app.analyzer import detector
from app.analyzer.domlite import Document, parse
from app.editor import service as editor
from app.editor.schema import ScenarioDefinition


class HtmlRecord:
    """Замена записи карты элементов: только то, что нужно сборке сценария."""

    def __init__(self, elements: list[dict[str, Any]], record_id: str = "html-map") -> None:
        self.elements = elements
        self.edit_draft: dict[str, Any] | None = None
        self.id = record_id


class HtmlSnapshot:
    """Замена снапшота: адрес и заголовок страницы."""

    def __init__(self, url: str, title: str | None = None) -> None:
        self.id = "html-snapshot"
        self.url = url
        self.final_url = url
        self.title = title


def parse_html_for_validation(html: str) -> Document:
    """Разбирает HTML для проверки сценария."""
    return parse(html)


def scenario_for_html(
    html: str,
    *,
    url: str = "https://example.com/",
    title: str | None = None,
    items_expected: int = 0,
) -> ScenarioDefinition:
    """Строит сценарий из разметки без базы данных.

    Используется в тестах и при отладке: разбирает страницу, строит карту
    элементов и превращает её в базовый сценарий.
    """
    analysis = detector.analyze_html(html)
    record = HtmlRecord([element.as_dict() for element in analysis.elements])
    snapshot = HtmlSnapshot(url, title)
    return editor.build_baseline(record, snapshot, items_expected=items_expected)
