"""Промпты для локальной модели.

Промпты лежат отдельными файлами и версионируются: при смене текста меняется
``PROMPT_VERSION``, и это видно в записи карты элементов. Формулировки короткие
и по делу — локальные модели на 7B теряют качество на длинных инструкциях.
"""

from __future__ import annotations

import json
from typing import Any

PROMPT_VERSION = "2024-11-01.1"

SYSTEM_PROMPT = """Ты аналитик веб-страниц. По структурной выжимке HTML определи, \
за что отвечает каждый пронумерованный элемент, и какую роль он играет.

Правила:
- Отвечай ТОЛЬКО JSON, без пояснений и без markdown.
- Используй только те номера элементов, которые есть во входных данных.
- Роль выбирай из списка: search_input, text_input, email_input, phone_input, \
password_input, number_input, date_input, file_input, checkbox, radio, select, \
textarea, submit, button, link, pagination_next, pagination_prev, pagination, \
load_more, filter, sort, list_container, list_item, item_title, item_link, \
item_price, item_image, item_description, table, table_row, heading, navigation, \
header, footer, cookie_banner, modal, unknown.
- Описание пиши по-русски, коротко и по делу, без технического жаргона.
- Если не уверен в роли, верни unknown: выдумывать хуже, чем признать неуверенность.

Формат ответа:
{"summary": "краткое описание страницы в 1-2 предложениях", \
"items": [{"index": 1, "role": "search_input", "description": "поиск по каталогу", \
"confidence": 0.9}]}"""

USER_TEMPLATE = """Заголовок страницы: {title}
Язык: {lang}
Ссылка: {url}

Найденные списки (повторяющиеся блоки):
{repeats}

Элементы для разбора (номер — тег — подсказка — текстовый фрагмент):
{elements}

Ответь JSON по заданному формату."""


def build_user_prompt(
    *,
    title: str | None,
    lang: str | None,
    url: str,
    repeats: list[dict[str, Any]],
    elements: list[dict[str, Any]],
) -> str:
    """Собирает пользовательскую часть промпта."""
    if repeats:
        repeats_text = "\n".join(
            f"  - {item['count']} элементов, похожесть {item['similarity']:.0%}, "
            f"пример: {(item.get('sample_text') or '')[:80]}"
            for item in repeats[:4]
        )
    else:
        repeats_text = "  не найдено"

    elements_text = "\n".join(
        f"  {item['index']}. <{item.get('tag', '?')}> {item.get('hint', '')} | "
        f"{(item.get('text') or '')[:70]}"
        for item in elements
    )

    return USER_TEMPLATE.format(
        title=title or "(без заголовка)",
        lang=lang or "не определён",
        url=url,
        repeats=repeats_text,
        elements=elements_text or "  нет элементов",
    )


# Схема ответа: используется и в промпте, и при валидации.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "role": {"type": "string"},
                    "description": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["index", "role"],
            },
        },
    },
    "required": ["items"],
}


def response_schema_json() -> str:
    """Схема ответа строкой — для передачи в поле format."""
    return json.dumps(RESPONSE_SCHEMA, ensure_ascii=False)
