"""Проверка собранных записей и отчёт о полноте данных.

Отчёт отвечает на вопрос, ради которого всё делается: «данные собраны целиком
или с дырами». Без него сорок записей с пустыми ценами выглядят как успех.

Проверяются три вещи:

* **обязательные поля** — если их нет, запись помечается недействительной;
* **полнота** — доля заполненных значений по каждому полю и по обязательным;
* **правдоподобие** — цена не отрицательная, ссылка ведёт на тот же сайт, дата не
  из будущего.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from app.editor.schema import ScenarioDefinition
from app.engine.extractor import ExtractedRecord, ExtractionResult

# Полнота по обязательным полям, ниже которой сценарий считается проблемным.
DEFAULT_MIN_COVERAGE = 0.95


@dataclass
class RecordIssue:
    """Замечание к одной записи."""

    position: int
    key: str
    problem: str
    severity: str = "error"

    def as_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "key": self.key,
            "problem": self.problem,
            "severity": self.severity,
        }


@dataclass
class RunReport:
    """Итог проверки собранных данных."""

    records: int = 0
    valid_records: int = 0
    invalid_records: int = 0
    required_coverage: float = 0.0
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    issues: list[RecordIssue] = field(default_factory=list)
    suspicious: int = 0
    min_coverage: float = DEFAULT_MIN_COVERAGE

    @property
    def passed(self) -> bool:
        """Считается ли сбор успешным."""
        return (
            self.records > 0
            and self.invalid_records == 0
            and self.required_coverage >= self.min_coverage
        )

    @property
    def completeness(self) -> float:
        """Средняя полнота по всем полям."""
        if not self.fields:
            return 0.0
        return round(sum(item["coverage"] for item in self.fields.values()) / len(self.fields), 3)

    def problems_by_field(self) -> dict[str, list[str]]:
        """Замечания, сгруппированные по полям."""
        grouped: dict[str, list[str]] = {}
        for issue in self.issues:
            grouped.setdefault(issue.key, []).append(issue.problem)
        return {key: sorted(set(values)) for key, values in grouped.items()}

    def summary(self) -> dict[str, Any]:
        return {
            "records": self.records,
            "valid_records": self.valid_records,
            "invalid_records": self.invalid_records,
            "required_coverage": self.required_coverage,
            "completeness": self.completeness,
            "suspicious": self.suspicious,
            "min_coverage": self.min_coverage,
            "passed": self.passed,
            "issues_total": len(self.issues),
        }

    def as_dict(self) -> dict[str, Any]:
        payload = self.summary()
        payload["fields"] = self.fields
        payload["issues"] = [issue.as_dict() for issue in self.issues[:200]]
        payload["problems_by_field"] = self.problems_by_field()
        return payload


def _host_of(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlsplit(url).netloc or "").lower().removeprefix("www.") or None
    except ValueError:
        return None


def check_record(
    record: ExtractedRecord,
    definition: ScenarioDefinition,
    *,
    base_url: str | None = None,
) -> list[RecordIssue]:
    """Проверяет одну запись на правдоподобие значений.

    Эти проверки ловят ошибки выбора селектора: «ценой» часто оказывается
    артикул, а «ссылкой» — адрес чужого сайта из рекламного блока.
    """
    issues: list[RecordIssue] = []
    site_host = _host_of(base_url or definition.url)

    for spec in definition.fields:
        value = record.values.get(spec.key)

        if spec.required and value in (None, ""):
            issue = record.problems.get(spec.key) or "обязательное поле не заполнено"
            issues.append(RecordIssue(record.position, spec.key, issue))
            continue
        if value in (None, ""):
            continue

        kind = _kind_of(spec)

        if kind == "price" and isinstance(value, (int, float)) and value < 0:
            issues.append(
                RecordIssue(record.position, spec.key, f"отрицательная цена: {value}", "warning")
            )

        if kind in {"url", "image"} and isinstance(value, str):
            host = _host_of(value)
            if host is None:
                issues.append(
                    RecordIssue(record.position, spec.key, "ссылка без домена", "warning")
                )
            elif site_host and host != site_host:
                issues.append(
                    RecordIssue(
                        record.position,
                        spec.key,
                        f"ссылка ведёт на другой сайт: {host}",
                        "warning",
                    )
                )

        if kind == "date" and isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                issues.append(
                    RecordIssue(record.position, spec.key, "дата не разобрана", "warning")
                )
            else:
                moment = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
                if moment > datetime.now(timezone.utc):
                    issues.append(
                        RecordIssue(record.position, spec.key, "дата в будущем", "warning")
                    )

        if kind == "text" and isinstance(value, str):
            if len(value) > 300:
                issues.append(
                    RecordIssue(
                        record.position,
                        spec.key,
                        f"значение слишком длинное: {len(value)} символов",
                        "warning",
                    )
                )
            if normalize_looks_like_boilerplate(value):
                issues.append(
                    RecordIssue(
                        record.position, spec.key, "значение похоже на служебный текст", "warning"
                    )
                )

    return issues


def _kind_of(spec: Any) -> str:
    """Тип значения поля — та же логика, что в извлечении."""
    from app.editor.schema import SelectStrategy
    from app.engine import normalize as normalize_mod

    if spec.strategy is SelectStrategy.IMAGE:
        return "image"
    if spec.strategy is SelectStrategy.ATTRIBUTE:
        attribute = (spec.attribute or "").lower()
        if attribute in {"href", "action", "data-url"}:
            return "url"
        if attribute in {"src", "data-src"}:
            return "image"
    if spec.strategy is SelectStrategy.COUNT:
        return "int"
    return normalize_mod.guess_type(spec.key, spec.title)


BOILERPLATE_MARKERS = (
    "подробнее",
    "читать далее",
    "купить",
    "в корзину",
    "реклама",
    "показать ещё",
    "загрузить ещё",
    "показать все",
)


def normalize_looks_like_boilerplate(value: str) -> bool:
    """Похоже ли значение на кнопку или служебную подпись, а не на данные."""
    lowered = value.strip().lower()
    if not lowered:
        return False
    if lowered in BOILERPLATE_MARKERS:
        return True
    return len(lowered) <= 20 and any(marker in lowered for marker in BOILERPLATE_MARKERS)


def build_report(
    result: ExtractionResult,
    definition: ScenarioDefinition,
    *,
    base_url: str | None = None,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
    check_values: bool = True,
) -> RunReport:
    """Собирает отчёт о полноте и качестве собранных данных."""
    report = RunReport(records=result.count, min_coverage=min_coverage)
    report.fields = result.field_stats(definition)

    required = [key for key, item in report.fields.items() if item["required"]]
    if required:
        report.required_coverage = round(
            sum(report.fields[key]["coverage"] for key in required) / len(required), 3
        )
    else:
        # Обязательных полей нет — считаем полноту по всем.
        report.required_coverage = report.completeness

    for record in result.records:
        missing_required = [key for key in required if record.values.get(key) in (None, "")]
        if missing_required:
            report.invalid_records += 1
            for key in missing_required:
                problem = record.problems.get(key) or "обязательное поле не заполнено"
                report.issues.append(RecordIssue(record.position, key, problem))
        else:
            report.valid_records += 1

        if check_values:
            for issue in check_record(record, definition, base_url=base_url):
                report.issues.append(issue)
                if issue.severity == "warning":
                    report.suspicious += 1

    return report


def describe_report(report: RunReport) -> str:
    """Человекочитаемый итог запуска — для интерфейса."""
    lines = [
        f"Собрано записей: {report.records}",
        f"Полных: {report.valid_records}, с пропусками: {report.invalid_records}",
        f"Полнота обязательных полей: {report.required_coverage:.0%}",
    ]
    if report.fields:
        lines.append("")
        lines.append("Заполненность по полям:")
        for _key, item in report.fields.items():
            marker = " (обязательное)" if item["required"] else ""
            lines.append(
                f"  • {item['title']}{marker}: {item['filled']} из {item['total']} "
                f"({item['coverage']:.0%})"
            )
            for problem, count in item["problems"].items():
                lines.append(f"      {problem} — {count} раз")

    warnings = [issue for issue in report.issues if issue.severity == "warning"]
    if warnings:
        lines.append("")
        lines.append(f"Требует проверки ({len(warnings)}):")
        grouped: dict[str, set[str]] = {}
        for issue in warnings:
            grouped.setdefault(issue.problem, set()).add(issue.key)
        for problem, keys in list(grouped.items())[:10]:
            lines.append(f"  • {problem} — поля: {', '.join(sorted(keys))}")

    lines.append("")
    lines.append(
        "Итог: " + ("данные собраны полностью" if report.passed else "нужна проверка настроек")
    )
    return "\n".join(lines)
