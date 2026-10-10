"""Pydantic-схемы API (контракт между фронтендом и бэкендом)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ComponentHealth(BaseModel):
    """Состояние одной подсистемы."""

    name: str
    status: Literal["ok", "degraded", "down", "skipped"]
    detail: str | None = None


class HealthResponse(BaseModel):
    """Ответ ``GET /health``."""

    status: Literal["ok", "degraded"]
    app: str
    version: str
    env: str
    uptime_s: float
    components: list[ComponentHealth] = Field(default_factory=list)


class SystemInfoResponse(BaseModel):
    """Ответ ``GET /api/v1/system/info`` — сведения о сборке и возможностях."""

    app: str
    version: str
    env: str
    debug: bool
    stage: str
    stage_title: str
    implemented: list[str]
    planned: list[str]
    python_version: str
    database_url: str
    database_path: str | None
    data_dir: str
    browser: dict[str, Any]
    llm: dict[str, Any]


class FeatureStatus(BaseModel):
    """Готовность функции — используется на дашборде."""

    key: str
    title: str
    stage: str
    status: Literal["planned", "in_progress", "done"]
    description: str | None = None


class FeaturesResponse(BaseModel):
    """Ответ ``GET /api/v1/system/features``."""

    current_stage: str
    items: list[FeatureStatus]


class LLMStatusResponse(BaseModel):
    """Ответ ``GET /api/v1/system/llm``."""

    provider: str
    available: bool
    model: str | None = None
    models: list[str] = Field(default_factory=list)
    cloud_fallback_enabled: bool = False
    detail: str | None = None


class ErrorBody(BaseModel):
    """Тело ошибки."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Единый формат ошибки API."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": {
                    "code": "site_unreachable",
                    "message": "Не удалось открыть сайт",
                    "details": {"url": "https://example.com"},
                }
            }
        }
    )

    error: ErrorBody


class StageInfo(BaseModel):
    """Сведения об этапе разработки (для отображения прогресса в UI)."""

    key: str
    title: str
    status: Literal["done", "in_progress", "planned"]
    items: list[str] = Field(default_factory=list)


class RoadmapResponse(BaseModel):
    """Ответ ``GET /api/v1/system/roadmap`` — этапы из PLAN.md."""

    stages: list[StageInfo]
    current_stage: str
    updated_at: datetime
