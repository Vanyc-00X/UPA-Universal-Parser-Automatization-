"""Тесты шлюза к ИИ-модели: разбор ответа, валидация, деградация без модели."""

from __future__ import annotations

from app.analyzer.llm import (
    LLMGateway,
    extract_json,
    validate_response,
)
from app.core.config import Settings


def test_extract_json_plain() -> None:
    payload = extract_json('{"summary": "ok", "items": []}')
    assert payload == {"summary": "ok", "items": []}


def test_extract_json_from_markdown_fence() -> None:
    """Локальные модели любят оборачивать ответ в ```json … ```."""
    text = '```json\n{"items": [{"index": 1, "role": "search_input"}]}\n```'
    payload = extract_json(text)
    assert payload is not None
    assert payload["items"][0]["index"] == 1


def test_extract_json_with_leading_text() -> None:
    text = 'Вот результат анализа:\n{"summary": "страница каталога", "items": []}\nГотово.'
    payload = extract_json(text)
    assert payload is not None
    assert payload["summary"] == "страница каталога"


def test_extract_json_returns_none_for_garbage() -> None:
    assert extract_json("совсем не json") is None
    assert extract_json("") is None
    assert extract_json("{незакрытая скобка") is None
    assert extract_json("[1, 2, 3]") is None


def test_validate_response_accepts_valid_payload() -> None:
    payload = {
        "summary": "Каталог товаров",
        "items": [
            {"index": 1, "role": "search_input", "description": "поиск", "confidence": 0.9},
            {"index": 3, "role": "item_price", "description": "цена", "confidence": 0.8},
        ],
    }
    summary, roles, problems = validate_response(payload, {1, 2, 3})

    assert summary == "Каталог товаров"
    assert set(roles) == {1, 3}
    assert roles[1]["role"] == "search_input"
    assert roles[1]["confidence"] == 0.9
    assert problems == []


def test_validate_response_drops_unknown_indexes_and_roles() -> None:
    """Выдуманные моделью номера и роли не должны попадать в карту."""
    payload = {
        "items": [
            {"index": 99, "role": "search_input"},
            {"index": 1, "role": "выдуманная_роль"},
            {"index": 2, "role": "item_title", "confidence": 5.0},
        ]
    }
    _summary, roles, problems = validate_response(payload, {1, 2})

    assert set(roles) == {2}
    assert roles[2]["confidence"] is None  # 5.0 вне диапазона — отброшено
    assert len(problems) == 2


def test_validate_response_handles_broken_items() -> None:
    payload = {"items": "не список"}
    summary, roles, problems = validate_response(payload, {1})

    assert summary is None
    assert roles == {}
    assert problems


def test_validate_response_ignores_non_dict_items() -> None:
    payload = {"items": ["строка", 42, {"index": 1, "role": "button"}]}
    _summary, roles, _problems = validate_response(payload, {1})
    assert set(roles) == {1}


async def test_gateway_without_llm_returns_detail(settings: Settings) -> None:
    """Провайдер none: обогащение не выполняется и не падает."""
    settings.llm_provider = "none"
    gateway = LLMGateway(settings)

    result = await gateway.enrich(
        title="Тест", lang="ru", url="https://example.com", repeats=[], elements=[]
    )

    assert result.used is False
    assert result.detail == "ИИ отключён в настройках"


async def test_gateway_unreachable_ollama_degrades(settings: Settings) -> None:
    """Недоступная Ollama не должна приводить к исключению."""
    settings.llm_provider = "ollama"
    settings.ollama_base_url = "http://127.0.0.1:1"
    settings.llm_timeout_s = 1
    gateway = LLMGateway(settings)

    status = await gateway.status()
    assert status.available is False
    assert status.detail

    result = await gateway.enrich(
        title="Тест",
        lang="ru",
        url="https://example.com",
        repeats=[],
        elements=[{"index": 1, "tag": "input", "hint": "поиск", "text": ""}],
    )
    assert result.used is False
    assert result.detail


async def test_gateway_status_for_disabled_provider(settings: Settings) -> None:
    settings.llm_provider = "none"
    status = await LLMGateway(settings).status()
    assert status.available is False
    assert status.provider == "none"


async def test_gateway_status_for_incomplete_cloud_config(settings: Settings) -> None:
    settings.llm_provider = "openai_compatible"
    settings.llm_cloud_base_url = ""
    settings.llm_cloud_api_key = ""
    status = await LLMGateway(settings, apply_overrides=False).status()
    assert status.available is False
    detail = (status.detail or "").lower()
    assert "url" in detail or "ключ" in detail or "api" in detail


async def test_gateway_complete_without_provider_returns_error(settings: Settings) -> None:
    settings.llm_provider = "none"
    text, error = await LLMGateway(settings).complete("system", "user")
    assert text is None
    assert error


def test_response_schema_is_valid_json() -> None:
    import json

    from app.analyzer.prompts import response_schema_json

    schema = json.loads(response_schema_json())
    assert schema["type"] == "object"
    assert "items" in schema["properties"]


def test_user_prompt_includes_elements_and_repeats() -> None:
    from app.analyzer.prompts import build_user_prompt

    prompt = build_user_prompt(
        title="Каталог",
        lang="ru",
        url="https://example.com",
        repeats=[{"count": 12, "similarity": 0.9, "sample_text": "Товар 1"}],
        elements=[{"index": 1, "tag": "input", "hint": "поиск", "text": "Поиск"}],
    )
    assert "Каталог" in prompt
    assert "12 элементов" in prompt
    assert "1. <input>" in prompt
