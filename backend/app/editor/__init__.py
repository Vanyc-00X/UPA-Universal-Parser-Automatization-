"""Визуальный редактор: инспектор страницы, проверка селекторов, сценарии.

Модули:
    resolver   — сопоставление CSS-селекторов с разобранным DOM
    inspector  — список узлов страницы с оценкой положения для подсветки
    schema     — строгая схема сценария (поля, план, пагинация)
    scenario   — сохранение сценариев и версий
    service    — черновик сценария, правки и проверка на живом DOM
"""

from app.editor.inspector import (  # noqa: F401
    InspectNode,
    InspectorResult,
    assign_ids,
    build_inspector,
    estimate_boxes,
    node_id_for,
    sibling_context,
)
from app.editor.resolver import (  # noqa: F401
    MatchReport,
    ParsedSelector,
    compare_selectors,
    count_matches,
    first_match,
    iter_matches,
    parse_selector,
    resolve,
)
from app.editor.schema import (  # noqa: F401
    ExtractionPlan,
    FieldSpec,
    FieldValidation,
    PaginationKind,
    PaginationSpec,
    SaveScenarioRequest,
    ScenarioDefinition,
    ScenarioOut,
    ScenarioValidation,
    ScenarioVersionOut,
    SelectStrategy,
)
from app.editor.service import (  # noqa: F401
    EditorState,
    build_baseline,
    build_inspector_payload,
    get_state,
    load_document,
    reset_draft,
    resolve_selector,
    save_draft,
    suggest_key,
    validate_definition,
)

__all__ = [
    "EditorState",
    "ExtractionPlan",
    "FieldSpec",
    "FieldValidation",
    "InspectNode",
    "InspectorResult",
    "MatchReport",
    "PaginationKind",
    "PaginationSpec",
    "ParsedSelector",
    "SaveScenarioRequest",
    "ScenarioDefinition",
    "ScenarioOut",
    "ScenarioValidation",
    "ScenarioVersionOut",
    "SelectStrategy",
    "assign_ids",
    "build_baseline",
    "build_inspector",
    "build_inspector_payload",
    "compare_selectors",
    "count_matches",
    "estimate_boxes",
    "first_match",
    "get_state",
    "iter_matches",
    "load_document",
    "node_id_for",
    "parse_selector",
    "reset_draft",
    "resolve",
    "resolve_selector",
    "save_draft",
    "sibling_context",
    "suggest_key",
    "validate_definition",
]
