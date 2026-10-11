"""Движок извлечения: разбор страниц по сценарию и запись результатов.

Модули:
    normalize  — приведение значений к типам (цены, ссылки, даты, числа)
    extractor  — чтение полей из DOM по описанию сценария
    paginate   — план обхода страниц и поиск «следующей»
    validate   — проверка записей и отчёт о полноте данных
    service    — запуск сценария, сохранение запусков и записей
"""

from app.engine.extractor import (  # noqa: F401
    ExtractedRecord,
    ExtractionResult,
    FieldValue,
    extract_from_scope,
    extract_page,
    summarize,
)
from app.engine.normalize import (  # noqa: F401
    NormalizedValue,
    absolute_url,
    clean_text,
    dedup_key,
    detect_kind,
    guess_type,
    image_url,
    navigation_key,
    parse_date,
    parse_datetime,
    parse_float,
    parse_int,
    parse_number,
    parse_price,
    url_key,
)
from app.engine.normalize import (
    normalize as normalize_value,
)
from app.engine.paginate import (  # noqa: F401
    PageVisit,
    PaginationPlan,
    build_plan,
    find_next_url,
    next_page_step,
)
from app.engine.service import (  # noqa: F401
    PageResult,
    RunOutcome,
    list_run_items,
    list_runs,
    preview_definition,
    run_definition,
    run_scenario,
)
from app.engine.validate import (  # noqa: F401
    RecordIssue,
    RunReport,
    build_report,
    describe_report,
)

__all__ = [
    "ExtractedRecord",
    "ExtractionResult",
    "FieldValue",
    "NormalizedValue",
    "PageResult",
    "PageVisit",
    "PaginationPlan",
    "RecordIssue",
    "RunOutcome",
    "RunReport",
    "absolute_url",
    "build_plan",
    "build_report",
    "clean_text",
    "dedup_key",
    "describe_report",
    "detect_kind",
    "extract_from_scope",
    "extract_page",
    "find_next_url",
    "guess_type",
    "image_url",
    "list_run_items",
    "list_runs",
    "navigation_key",
    "next_page_step",
    "normalize_value",
    "parse_date",
    "parse_datetime",
    "parse_float",
    "parse_int",
    "parse_number",
    "parse_price",
    "preview_definition",
    "run_definition",
    "run_scenario",
    "summarize",
    "url_key",
]
