"""Извлечение значений из страницы по описанию сценария.

Модуль отвечает на один вопрос: «что лежит в поле X этой страницы». Работает по
разобранному DOM, поэтому не требует браузера и одинаково ведёт себя в тестах и
в работе.

Две стратегии поиска полей:

* **внутри карточки списка** — поля ищутся среди потомков конкретной записи. Это
  основной случай: у всех карточек одинаковые классы, и искать «по всей странице»
  означало бы перемешать значения разных записей;
* **по всей странице** — для одиночных страниц и служебных полей.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from app.analyzer.domlite import Document, Node
from app.editor import resolver
from app.editor.schema import ExtractionPlan, FieldSpec, ScenarioDefinition, SelectStrategy
from app.engine import normalize as normalize_mod

# Сколько символов брать из текста по умолчанию: защита от целых абзацев.
TEXT_LIMIT = 400


@dataclass
class FieldValue:
    """Значение одного поля одной записи."""

    key: str
    title: str
    value: Any
    raw: str | None = None
    problem: str | None = None
    selector: str = ""
    matches: int = 0

    @property
    def ok(self) -> bool:
        return self.value not in (None, "")

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "value": self.value,
            "raw": self.raw,
            "problem": self.problem,
            "selector": self.selector,
            "matches": self.matches,
        }


@dataclass
class ExtractedRecord:
    """Одна собранная запись."""

    values: dict[str, Any] = field(default_factory=dict)
    raws: dict[str, str | None] = field(default_factory=dict)
    problems: dict[str, str] = field(default_factory=dict)
    # Какой селектор реально сработал: нужно self-healing (Этап 6).
    selectors_used: dict[str, str] = field(default_factory=dict)
    used_fallback: dict[str, bool] = field(default_factory=dict)
    position: int = 0
    source_url: str | None = None
    node_path: str | None = None

    @property
    def filled(self) -> int:
        return sum(1 for value in self.values.values() if value not in (None, ""))

    @property
    def empty_keys(self) -> list[str]:
        return [key for key, value in self.values.items() if value in (None, "")]

    def as_dict(self) -> dict[str, Any]:
        return {
            "values": self.values,
            "raws": self.raws,
            "problems": self.problems,
            "selectors_used": self.selectors_used,
            "used_fallback": self.used_fallback,
            "position": self.position,
            "source_url": self.source_url,
        }


@dataclass
class ExtractionResult:
    """Результат разбора одной страницы."""

    records: list[ExtractedRecord] = field(default_factory=list)
    mode: str = "list"
    container_selector: str | None = None
    container_matches: int = 0
    item_matches: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.records)

    def field_stats(self, definition: ScenarioDefinition) -> dict[str, dict[str, Any]]:
        """Статистика заполненности по каждому полю."""
        stats: dict[str, dict[str, Any]] = {}
        for spec in definition.fields:
            filled = sum(
                1 for record in self.records if record.values.get(spec.key) not in (None, "")
            )
            problems: dict[str, int] = {}
            for record in self.records:
                problem = record.problems.get(spec.key)
                if problem:
                    problems[problem] = problems.get(problem, 0) + 1
            stats[spec.key] = {
                "title": spec.title,
                "required": spec.required,
                "filled": filled,
                "total": self.count,
                "coverage": round(filled / self.count, 3) if self.count else 0.0,
                "problems": problems,
            }
        return stats

    def as_dict(self, definition: ScenarioDefinition | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mode": self.mode,
            "records": self.count,
            "container_selector": self.container_selector,
            "container_matches": self.container_matches,
            "item_matches": self.item_matches,
            "warnings": self.warnings,
            "errors": self.errors,
        }
        if definition is not None:
            payload["fields"] = self.field_stats(definition)
        return payload


def _text_from(node: Node, strategy: SelectStrategy, attribute: str | None) -> str | None:
    """Читает значение из узла согласно стратегии поля."""
    if strategy is SelectStrategy.ATTRIBUTE:
        return node.get(attribute or "") or None
    if strategy is SelectStrategy.IMAGE:
        # Ленивые картинки часто лежат в data-src, а src — заглушка.
        return node.get("src") or node.get("data-src") or node.get("data-original") or None
    if strategy is SelectStrategy.OWN_TEXT:
        return node.own_text or None
    if strategy is SelectStrategy.HTML:
        return node.all_text(limit=TEXT_LIMIT) or None
    if strategy is SelectStrategy.COUNT:
        return str(len(node.children))
    return node.all_text(limit=TEXT_LIMIT) or None


def _find_nodes(scope: Node, selector: str) -> list[Node]:
    """Ищет узлы по селектору внутри области видимости.

    ``scope`` включается в поиск: карточка сама может быть искомым элементом.
    """
    report = resolver.resolve(scope, selector)
    if not report.valid or not report.nodes:
        return []
    return report.nodes


def extract_from_scope(
    scope: Node,
    definition: ScenarioDefinition,
    *,
    base_url: str | None,
) -> ExtractedRecord:
    """Извлекает все поля сценария внутри одной области (карточки или страницы)."""
    record = ExtractedRecord(source_url=base_url, node_path=scope.css_path())

    for spec in definition.fields:
        nodes = _find_nodes(scope, spec.selector)
        used_selector = spec.selector
        via_fallback = False

        # Запасной селектор нужен, когда основной перестал работать: так сценарий
        # продолжает собирать данные, пока пользователь не поправит его.
        if not nodes:
            for fallback in spec.fallback_selectors:
                nodes = _find_nodes(scope, fallback)
                if nodes:
                    used_selector = fallback
                    via_fallback = True
                    break

        if not nodes:
            record.values[spec.key] = None
            record.raws[spec.key] = None
            record.problems[spec.key] = "селектор не находит элементов"
            record.used_fallback[spec.key] = False
            continue

        raw = _text_from(nodes[0], spec.strategy, spec.attribute)
        kind = _kind_for(spec)
        normalized = normalize_mod.normalize(raw, kind=kind, base_url=base_url)

        record.values[spec.key] = normalized.value
        record.raws[spec.key] = normalized.raw
        record.selectors_used[spec.key] = used_selector
        record.used_fallback[spec.key] = via_fallback
        if via_fallback:
            record.problems[spec.key] = "основной селектор не сработал, использован запасной"
        if normalized.problem and spec.required:
            record.problems[spec.key] = normalized.problem

    return record


def _kind_for(spec: FieldSpec) -> str:
    """Определяет тип значения поля.

    Стратегия важнее названия: если поле берётся из атрибута href, это ссылка,
    как бы поле ни называлось.
    """
    if spec.strategy is SelectStrategy.IMAGE:
        return "image"
    if spec.strategy is SelectStrategy.ATTRIBUTE:
        attribute = (spec.attribute or "").lower()
        if attribute in {"href", "src", "action", "data-url"}:
            return "url" if attribute != "src" else "image"
        if "price" in attribute or "cost" in attribute:
            return "price"
        return "text"
    if spec.strategy is SelectStrategy.COUNT:
        return "int"
    return normalize_mod.guess_type(spec.key, spec.title)


def _item_nodes(document: Document, plan: ExtractionPlan) -> tuple[list[Node], int, str | None]:
    """Определяет узлы записей на странице.

    Возвращает сами узлы, число совпадений контейнера и предупреждение, если
    структура оказалась не такой, как ожидалось.
    """
    warning: str | None = None

    if plan.item_selector:
        report = resolver.resolve(document.root, plan.item_selector)
        return report.nodes, report.count, warning

    if not plan.container_selector:
        # Без контейнера записью считается вся страница.
        return [document.root], 1, None

    container = resolver.resolve(document.root, plan.container_selector)
    if not container.valid:
        return [], 0, f"селектор контейнера не поддерживается: {container.error}"
    if not container.nodes:
        return [], 0, "контейнер списка не найден на странице"

    items: list[Node] = []
    for node in container.nodes:
        # Записями считаем детей контейнера, а не его самого: так карточки
        # сохраняют собственные границы, и поля не перемешиваются.
        children = [child for child in node.children if child.tag not in {"script", "style"}]
        items.extend(children if children else [node])

    if len(container.nodes) == 1 and not items:
        warning = "в контейнере не оказалось дочерних элементов"
    return items, container.count, warning


def extract_page(
    document: Document,
    definition: ScenarioDefinition,
    *,
    base_url: str | None = None,
    limit: int | None = None,
) -> ExtractionResult:
    """Разбирает одну страницу по описанию сценария.

    Возвращает записи и статистику: она показывает, какие поля не заполнились и
    почему — без этого отчёт о полноте данных был бы бесполезен.
    """
    url = base_url or definition.url
    result = ExtractionResult(mode=definition.plan.mode)

    if not definition.fields:
        result.errors.append("в сценарии нет полей")
        return result

    if definition.plan.mode == "single":
        record = extract_from_scope(document.root, definition, base_url=url)
        record.position = 0
        result.records.append(record)
        result.container_matches = 1
        result.item_matches = 1
        return result

    if definition.plan.mode == "llm":
        result.errors.append("режим разбора моделью появится на следующем этапе")
        return result

    if definition.plan.mode == "api":
        result.errors.append("режим JSON-запроса обрабатывается отдельно от разбора страницы")
        return result

    items, container_matches, warning = _item_nodes(document, definition.plan)
    if warning:
        result.warnings.append(warning)
    result.container_selector = definition.plan.container_selector
    result.container_matches = container_matches

    if not items:
        result.errors.append("не найдено ни одной записи: проверьте контейнер списка")
        return result

    result.item_matches = len(items)
    for position, node in enumerate(items):
        if limit is not None and position >= limit:
            result.warnings.append(f"обработка ограничена {limit} записями")
            break
        record = extract_from_scope(node, definition, base_url=url)
        record.position = position
        result.records.append(record)

    # Если в записях не заполнилось ничего, вероятно, выбраны не те узлы.
    if result.records and all(record.filled == 0 for record in result.records):
        result.errors.append(
            "в найденных записях не заполнилось ни одно поле: "
            "вероятно, контейнер списка выбран неверно"
        )

    return result


def iter_values(result: ExtractionResult, key: str) -> Iterator[Any]:
    """Перебор значений одного поля по всем записям — для проверок и отчётов."""
    for record in result.records:
        yield record.values.get(key)


def field_problems(result: ExtractionResult) -> dict[str, int]:
    """Сколько раз каждая проблема встретилась по всем полям."""
    counts: dict[str, int] = {}
    for record in result.records:
        for problem in record.problems.values():
            counts[problem] = counts.get(problem, 0) + 1
    return counts


def summarize(result: ExtractionResult, definition: ScenarioDefinition) -> dict[str, Any]:
    """Краткая сводка разбора: сколько записей и как заполнены поля."""
    stats = result.field_stats(definition)
    required = [key for key, item in stats.items() if item["required"]]
    required_coverage = (
        round(sum(stats[key]["coverage"] for key in required) / len(required), 3)
        if required
        else 1.0
    )
    return {
        "records": result.count,
        "fields": len(definition.fields),
        "required_fields": len(required),
        "required_coverage": required_coverage,
        "fields_stats": stats,
        "problems": field_problems(result),
        "warnings": result.warnings,
        "errors": result.errors,
    }


def looks_like_price(text: str | None) -> bool:
    """Похоже ли значение на цену — используется в подсказках редактора."""
    if not text:
        return False
    return bool(re.search(r"\d", text)) and bool(normalize_mod.CURRENCY_RE.search(text))
