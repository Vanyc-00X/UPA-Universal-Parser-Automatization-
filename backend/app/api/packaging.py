"""Эндпоинты упаковки: шаблоны, ensure LLM (Этап 8)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.packaging import llm_ensure
from app.packaging import templates as templates_mod

router = APIRouter(tags=["packaging"])


class TemplateSummary(BaseModel):
    id: str
    title: str
    kind: Literal["collection", "form_fill"]
    description: str
    tags: list[str] = Field(default_factory=list)


class TemplateListResponse(BaseModel):
    items: list[TemplateSummary]


class TemplateDetail(TemplateSummary):
    definition: dict[str, Any] | None = None
    workflow: dict[str, Any] | None = None
    sample_csv: str = ""


class EnsureLlmRequest(BaseModel):
    pull: bool = Field(
        False,
        description="Если модели нет — запросить ollama pull (может занять несколько минут)",
    )


class EnsureLlmResponse(BaseModel):
    provider: str
    available: bool
    model: str | None = None
    models: list[str] = Field(default_factory=list)
    cloud_fallback_enabled: bool = False
    detail: str | None = None
    pulled: bool = False
    action: str = "none"


@router.get(
    "/templates",
    response_model=TemplateListResponse,
    summary="Список встроенных шаблонов сценариев",
)
async def list_templates(
    kind: Literal["collection", "form_fill"] | None = Query(None),
) -> TemplateListResponse:
    items = templates_mod.list_templates(kind=kind)
    return TemplateListResponse(items=[TemplateSummary.model_validate(item) for item in items])


@router.get(
    "/templates/{template_id}",
    response_model=TemplateDetail,
    summary="Шаблон сценария с примером данных",
)
async def get_template(template_id: str) -> TemplateDetail:
    item = templates_mod.load_template(template_id)
    return TemplateDetail.model_validate(item)


@router.post(
    "/system/llm/ensure",
    response_model=EnsureLlmResponse,
    summary="Проверить Ollama и при необходимости загрузить модель",
    description=(
        "Без pull=true только диагностика. С pull=true вызывается ollama pull для модели "
        "из настроек. Если Ollama недоступна — понятный отказ, UPA продолжает работать без ИИ."
    ),
)
async def ensure_llm(payload: EnsureLlmRequest, request: Request) -> EnsureLlmResponse:
    settings = request.app.state.settings
    data = await llm_ensure.ensure_ollama_model(settings, pull=payload.pull)
    return EnsureLlmResponse.model_validate(data)
