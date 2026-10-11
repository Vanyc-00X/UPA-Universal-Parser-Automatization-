"""Пресеты провайдеров ИИ и локальные переопределения (ключ API из UI)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from app.core.config import REPO_ROOT, Settings
from app.core.logging import get_logger

log = get_logger(__name__)

LlmProviderName = Literal[
    "none",
    "ollama",
    "llamacpp",
    "openai",
    "openrouter",
    "grok",
    "openai_compatible",
]

PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "none": {
        "label": "Disabled",
        "description": "Heuristics only — no model calls",
        "transport": "none",
        "needs_key": False,
        "local": True,
    },
    "ollama": {
        "label": "Ollama",
        "description": "Local Ollama HTTP API",
        "transport": "ollama",
        "needs_key": False,
        "local": True,
        "default_base_url": "http://127.0.0.1:11434",
        "default_model": "qwen2.5:7b",
    },
    "llamacpp": {
        "label": "llama.cpp",
        "description": "llama.cpp OpenAI-compatible server (/v1)",
        "transport": "openai",
        "needs_key": False,
        "local": True,
        "default_base_url": "http://127.0.0.1:8080/v1",
        "default_model": "local",
    },
    "openai": {
        "label": "OpenAI",
        "description": "Official OpenAI Chat Completions API",
        "transport": "openai",
        "needs_key": True,
        "local": False,
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
    },
    "openrouter": {
        "label": "OpenRouter",
        "description": "OpenRouter — many models behind one key",
        "transport": "openai",
        "needs_key": True,
        "local": False,
        "default_base_url": "https://openrouter.ai/api/v1",
        "default_model": "openai/gpt-4o-mini",
        "extra_headers": {
            "HTTP-Referer": "https://github.com/Vanyc-00X/UPA-Universal-Parser-Automatization-",
            "X-Title": "UPA",
        },
    },
    "grok": {
        "label": "xAI Grok",
        "description": "xAI Grok API (OpenAI-compatible)",
        "transport": "openai",
        "needs_key": True,
        "local": False,
        "default_base_url": "https://api.x.ai/v1",
        "default_model": "grok-2-latest",
    },
    "openai_compatible": {
        "label": "Custom OpenAI-compatible",
        "description": "Any /v1/chat/completions endpoint (Azure, Together, Groq, …)",
        "transport": "openai",
        "needs_key": True,
        "local": False,
        "default_base_url": "",
        "default_model": "",
    },
}

OVERRIDE_KEYS = (
    "llm_provider",
    "ollama_base_url",
    "ollama_model",
    "llamacpp_base_url",
    "llamacpp_model",
    "llm_cloud_fallback",
    "llm_cloud_base_url",
    "llm_cloud_api_key",
    "llm_cloud_model",
    "llm_timeout_s",
)


def overrides_path(settings: Settings | None = None) -> Path:
    if settings is not None:
        return settings.data_dir / "llm_settings.json"
    return REPO_ROOT / "data" / "llm_settings.json"


def load_overrides(settings: Settings | None = None) -> dict[str, Any]:
    path = overrides_path(settings)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("llm_runtime.bad_overrides", path=str(path), error=str(exc))
        return {}
    if not isinstance(payload, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for key in OVERRIDE_KEYS:
        if key not in payload:
            continue
        cleaned[key] = payload[key]
    provider = cleaned.get("llm_provider")
    if provider is not None and provider not in PROVIDER_PRESETS:
        cleaned.pop("llm_provider", None)
    return cleaned


def save_overrides(settings: Settings, updates: dict[str, Any]) -> dict[str, Any]:
    """Сохраняет переопределения. Пустой api_key не затирает уже сохранённый."""
    current = load_overrides(settings)
    for key in OVERRIDE_KEYS:
        if key not in updates:
            continue
        value = updates[key]
        if key == "llm_cloud_api_key" and value in ("", None):
            # Пустая строка в форме = «не менять», явная очистка — через clear_api_key.
            continue
        if key == "llm_provider" and value not in PROVIDER_PRESETS:
            continue
        current[key] = value
    if updates.get("clear_api_key"):
        current["llm_cloud_api_key"] = ""
    path = overrides_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current


def with_llm_overrides(settings: Settings) -> Settings:
    """Возвращает Settings с наложением data/llm_settings.json."""
    overrides = load_overrides(settings)
    if not overrides:
        return settings
    try:
        return settings.model_copy(update=overrides)
    except Exception as exc:  # noqa: BLE001
        log.warning("llm_runtime.apply_failed", error=str(exc))
        return settings


def resolve_openai_target(settings: Settings) -> dict[str, Any]:
    """Адрес / ключ / модель для OpenAI-совместимого транспорта."""
    provider = settings.llm_provider
    preset = PROVIDER_PRESETS.get(provider, {})
    if provider == "llamacpp":
        base = settings.llamacpp_base_url or preset.get("default_base_url", "")
        model = settings.llamacpp_model or preset.get("default_model", "local")
        key = settings.llm_cloud_api_key or "llamacpp"
    elif provider in {"openai", "openrouter", "grok"}:
        base = settings.llm_cloud_base_url or preset.get("default_base_url", "")
        model = settings.llm_cloud_model or preset.get("default_model", "")
        key = settings.llm_cloud_api_key
    else:  # openai_compatible or fallback cloud
        base = settings.llm_cloud_base_url or preset.get("default_base_url", "")
        model = settings.llm_cloud_model or preset.get("default_model", "")
        key = settings.llm_cloud_api_key
    headers = dict(preset.get("extra_headers") or {})
    return {
        "provider": provider,
        "base_url": base.rstrip("/"),
        "api_key": key,
        "model": model,
        "headers": headers,
        "needs_key": bool(preset.get("needs_key")),
        "local": bool(preset.get("local")),
    }


def public_config(settings: Settings) -> dict[str, Any]:
    """Конфиг для UI: ключ маскируется."""
    effective = with_llm_overrides(settings)
    key = effective.llm_cloud_api_key or ""
    masked = ""
    if key:
        masked = ("*" * max(0, len(key) - 4)) + key[-4:]
    return {
        "provider": effective.llm_provider,
        "ollama_base_url": effective.ollama_base_url,
        "ollama_model": effective.ollama_model,
        "llamacpp_base_url": effective.llamacpp_base_url,
        "llamacpp_model": effective.llamacpp_model,
        "llm_cloud_fallback": effective.llm_cloud_fallback,
        "llm_cloud_base_url": effective.llm_cloud_base_url,
        "llm_cloud_model": effective.llm_cloud_model,
        "llm_cloud_api_key_set": bool(key),
        "llm_cloud_api_key_masked": masked,
        "llm_timeout_s": effective.llm_timeout_s,
        "presets": [
            {
                "id": key_id,
                "label": meta["label"],
                "description": meta["description"],
                "needs_key": meta["needs_key"],
                "local": meta["local"],
                "default_base_url": meta.get("default_base_url"),
                "default_model": meta.get("default_model"),
            }
            for key_id, meta in PROVIDER_PRESETS.items()
        ],
    }
