"""Анализ страницы: детерминированные эвристики плюс локальная модель.

Модули:
    domlite   — лёгкий терпимый HTML-парсер
    roles     — роли элементов и построение устойчивых селекторов
    detector  — поиск списков, полей, пагинации; отчёт о странице
    llm       — шлюз к модели со структурным выводом и деградацией без ИИ
    service   — сборка и сохранение карты элементов
"""

from app.analyzer.detector import (  # noqa: F401
    PageAnalysis,
    RepeatGroup,
    analyze_document,
    analyze_html,
    build_report,
    find_repeat_groups,
)
from app.analyzer.domlite import Document, Node, parse  # noqa: F401
from app.analyzer.roles import (  # noqa: F401
    DATA_ROLES,
    REPEATING_ROLES,
    ROLE_LABELS,
    Element,
    Role,
    SelectorCandidate,
    build_selectors,
    label_for,
)
from app.analyzer.service import (  # noqa: F401
    AnalysisOutcome,
    analyze_snapshot,
    get_element_map,
    list_element_maps,
    require_element_map,
    update_element,
)

__all__ = [
    "DATA_ROLES",
    "REPEATING_ROLES",
    "ROLE_LABELS",
    "AnalysisOutcome",
    "Document",
    "Element",
    "Node",
    "PageAnalysis",
    "RepeatGroup",
    "Role",
    "SelectorCandidate",
    "analyze_document",
    "analyze_html",
    "analyze_snapshot",
    "build_report",
    "build_selectors",
    "find_repeat_groups",
    "get_element_map",
    "label_for",
    "list_element_maps",
    "parse",
    "require_element_map",
    "update_element",
]
