"""Встроенные шаблоны сценариев и примеры данных."""

from __future__ import annotations

from typing import Any, Literal

from app.core.errors import NotFoundError

TemplateKind = Literal["collection", "form_fill"]


TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "catalog-list",
        "title": "Каталог товаров",
        "kind": "collection",
        "description": "Список карточек: название, цена, ссылка. Пагинация next_link.",
        "tags": ["каталог", "товары", "список"],
        "workflow": None,
        "definition": {
            "url": "https://shop.example.com/catalog",
            "title": "Каталог товаров",
            "description": "Шаблон списка товаров с пагинацией",
            "plan": {"mode": "list", "item_selector": ".product-card"},
            "pagination": {"kind": "next_link", "selector": "a.pagination__next", "max_pages": 5},
            "fields": [
                {
                    "key": "title",
                    "title": "Название",
                    "selector": ".product-card__title",
                    "required": True,
                },
                {
                    "key": "price",
                    "title": "Цена",
                    "selector": ".product-card__price",
                    "note": "нормализация цены на этапе извлечения",
                },
                {
                    "key": "url",
                    "title": "Ссылка",
                    "selector": "a.product-card__link",
                    "strategy": "attribute",
                    "attribute": "href",
                },
            ],
            "limits": {"template": "catalog-list"},
            "created_from": "template",
        },
        "sample_csv": "title,price,url\nТовар 1,1990,/product/1\nТовар 2,2490,/product/2\n",
    },
    {
        "id": "form-order",
        "title": "Форма заявки",
        "kind": "form_fill",
        "description": "Ввод имени, email и города из CSV с подтверждением отправки.",
        "tags": ["форма", "ввод", "csv"],
        "definition": None,
        "workflow": {
            "url": "https://forms.example.com/order",
            "title": "Форма заявки",
            "description": "Шаблон заполнения заявки по строкам CSV",
            "steps": [
                {"type": "goto", "url": "https://forms.example.com/order"},
                {"type": "fill", "selector": "#field-name", "value": "{{name}}"},
                {"type": "fill", "selector": "#field-email", "value": "{{email}}"},
                {"type": "select", "selector": "#field-city", "value": "{{city}}"},
                {"type": "check", "selector": "#field-agree"},
                {
                    "type": "click",
                    "selector": "#btn-submit",
                    "confirm_required": True,
                    "note": "отправка формы",
                },
            ],
            "max_rows": 100,
            "require_confirm_submit": True,
        },
        "sample_csv": (
            "name,email,city\n"
            "Иван,ivan@example.com,msk\n"
            "Мария,maria@example.com,spb\n"
        ),
    },
    {
        "id": "single-article",
        "title": "Статья / карточка",
        "kind": "collection",
        "description": "Одна запись: заголовок, текст, дата публикации.",
        "tags": ["статья", "single"],
        "workflow": None,
        "definition": {
            "url": "https://news.example.com/article/1",
            "title": "Статья",
            "plan": {"mode": "single"},
            "pagination": {"kind": "none"},
            "fields": [
                {"key": "title", "title": "Заголовок", "selector": "h1", "required": True},
                {"key": "body", "title": "Текст", "selector": "article .content"},
                {
                    "key": "published_at",
                    "title": "Дата",
                    "selector": "time",
                    "note": "дата публикации",
                },
            ],
            "limits": {"template": "single-article"},
            "created_from": "template",
        },
        "sample_csv": "title,body,published_at\nПример,Текст статьи,2026-01-01\n",
    },
]


def list_templates(*, kind: TemplateKind | None = None) -> list[dict[str, Any]]:
    items = TEMPLATES
    if kind:
        items = [item for item in items if item["kind"] == kind]
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "kind": item["kind"],
            "description": item["description"],
            "tags": item["tags"],
        }
        for item in items
    ]


def load_template(template_id: str) -> dict[str, Any]:
    for item in TEMPLATES:
        if item["id"] == template_id:
            return dict(item)
    raise NotFoundError("Шаблон не найден", details={"template_id": template_id})
