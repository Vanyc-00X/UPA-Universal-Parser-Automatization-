"""Markdown: таблица данных и ТЗ для внешнего ИИ-агента."""

from __future__ import annotations

from typing import Any

from app.editor.schema import ScenarioDefinition
from app.exporters.table import ExportTable


def render_markdown_table(table: ExportTable, *, limit: int = 200) -> str:
    """Человекочитаемая таблица результатов в Markdown."""
    headers = table.header()
    lines = [
        "# Результаты запуска",
        "",
        f"Записей: **{table.count}**"
        + (f" (показаны первые {limit})" if table.count > limit else ""),
        "",
    ]
    if table.meta.get("scenario_name"):
        lines.append(f"Сценарий: **{table.meta['scenario_name']}**")
        lines.append("")
    if not table.columns:
        lines.append("_Нет колонок для вывода._")
        return "\n".join(lines) + "\n"

    lines.append("| " + " | ".join(_escape(h) for h in headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in table.as_matrix()[:limit]:
        lines.append("| " + " | ".join(_escape(str(cell)) for cell in row) + " |")
    return "\n".join(lines) + "\n"


def build_spec_markdown(
    definition: ScenarioDefinition,
    *,
    scenario_name: str | None = None,
    sample_rows: list[dict[str, Any]] | None = None,
) -> str:
    """ТЗ в Markdown: что и откуда брать — для внешнего ИИ или разработчика."""
    name = scenario_name or definition.title or "Без названия"
    lines = [
        f"# Техническое задание: {name}",
        "",
        "## Цель",
        "",
        definition.description
        or f"Собрать данные со страницы `{definition.url}` по описанному сценарию.",
        "",
        "## Источник",
        "",
        f"- URL: `{definition.url}`",
        f"- Режим: `{definition.plan.mode}`",
    ]
    if definition.plan.container_selector:
        lines.append(f"- Контейнер списка: `{definition.plan.container_selector}`")
    if definition.plan.item_selector:
        lines.append(f"- Селектор записи: `{definition.plan.item_selector}`")
    if definition.plan.api_url:
        lines.append(f"- JSON API: `{definition.plan.api_method} {definition.plan.api_url}`")

    lines += [
        "",
        "## Пагинация",
        "",
        f"- Способ: `{definition.pagination.kind.value}`",
        f"- Максимум страниц: {definition.pagination.max_pages}",
        f"- Задержка между страницами: {definition.pagination.delay_ms} мс",
    ]
    if definition.pagination.selector:
        lines.append(f"- Селектор «далее»: `{definition.pagination.selector}`")
    if definition.pagination.url_template:
        lines.append(f"- Шаблон адреса: `{definition.pagination.url_template}`")

    lines += ["", "## Поля", ""]
    if not definition.fields:
        lines.append("_Поля не заданы._")
    else:
        lines.append("| Ключ | Название | Селектор | Стратегия | Обязательное |")
        lines.append("| --- | --- | --- | --- | --- |")
        for spec in definition.fields:
            required = "да" if spec.required else "нет"
            attr = f"@{spec.attribute}" if spec.attribute else ""
            strategy = f"{spec.strategy.value}{attr}"
            lines.append(
                f"| `{spec.key}` | {_escape(spec.title)} | `{spec.selector}` | "
                f"`{strategy}` | {required} |"
            )
            if spec.fallback_selectors:
                lines.append(f"|  | запасные | `{', '.join(spec.fallback_selectors)}` |  |  |")

    lines += [
        "",
        "## Нормализация",
        "",
        "- Цены: убрать валюту и пробелы разрядов, результат — число.",
        "- Ссылки: относительные → абсолютные от базового URL страницы.",
        "- Даты: привести к ISO-8601 (`YYYY-MM-DD`).",
        "- Пустые и служебные пометки («реклама», «в корзину») считать отсутствием значения.",
        "",
        "## Выходной формат",
        "",
        "Массив объектов JSON. Ключи — машинные имена полей из таблицы выше.",
        "Допустимы форматы CSV, XLSX и JSONL с теми же колонками.",
        "",
        "## Критерии приёмки",
        "",
        "- Заполненность обязательных полей ≥ 95%.",
        "- Дубликаты по ссылке/названию отсутствуют.",
        "- Относительные ссылки раскрыты в абсолютные.",
        "",
    ]

    if sample_rows:
        lines += ["## Пример собранных записей", ""]
        keys = [spec.key for spec in definition.fields] or list(sample_rows[0].keys())
        lines.append("| " + " | ".join(keys) + " |")
        lines.append("| " + " | ".join("---" for _ in keys) + " |")
        for row in sample_rows[:5]:
            lines.append(
                "| " + " | ".join(_escape(str(row.get(key, "") or "")) for key in keys) + " |"
            )
        lines.append("")

    lines += [
        "## Ограничения",
        "",
        "- Не обходить капчу и антибот-защиту.",
        "- Соблюдать `robots.txt` и условия использования сайта.",
        "- Не собирать персональные данные без явной необходимости.",
        "",
    ]
    return "\n".join(lines)


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()
