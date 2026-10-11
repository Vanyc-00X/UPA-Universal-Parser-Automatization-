"""Провайдеры ИИ: llama.cpp, OpenRouter/OpenAI/Grok, overrides UI."""

from __future__ import annotations

import httpx
import pytest

from app.analyzer.llm import LLMGateway
from app.core import llm_runtime
from app.core.config import Settings


@pytest.mark.asyncio
async def test_llamacpp_complete(monkeypatch, settings: Settings) -> None:
    settings.llm_provider = "llamacpp"
    settings.llamacpp_base_url = "http://127.0.0.1:8080/v1"
    settings.llamacpp_model = "qwen"
    captured: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"summary":"ok","items":[]}'}}]}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    text, error = await LLMGateway(settings, apply_overrides=False).complete("sys", "user")
    assert error is None
    assert "summary" in (text or "")
    assert captured["url"].endswith("/chat/completions")
    assert captured["json"]["model"] == "qwen"


@pytest.mark.asyncio
async def test_openrouter_sends_extra_headers(monkeypatch, settings: Settings) -> None:
    settings.llm_provider = "openrouter"
    settings.llm_cloud_api_key = "or-key"
    settings.llm_cloud_model = "openai/gpt-4o-mini"
    captured: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}]}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    await LLMGateway(settings, apply_overrides=False).complete("s", "u", json_mode=False)
    assert "openrouter.ai" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer or-key"
    assert captured["headers"].get("X-Title") == "UPA"


@pytest.mark.asyncio
async def test_openai_status_requires_key(settings: Settings) -> None:
    settings.llm_provider = "openai"
    settings.llm_cloud_api_key = ""
    status = await LLMGateway(settings, apply_overrides=False).status()
    assert status.available is False
    assert "ключ" in (status.detail or "").lower() or "API" in (status.detail or "")


def test_save_and_load_overrides(settings: Settings, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    llm_runtime.save_overrides(
        settings,
        {
            "llm_provider": "grok",
            "llm_cloud_api_key": "secret-key-1234",
            "llm_cloud_model": "grok-2-latest",
        },
    )
    loaded = llm_runtime.load_overrides(settings)
    assert loaded["llm_provider"] == "grok"
    assert loaded["llm_cloud_api_key"] == "secret-key-1234"
    public = llm_runtime.public_config(settings)
    assert public["llm_cloud_api_key_set"] is True
    assert public["llm_cloud_api_key_masked"].endswith("1234")
    assert "secret-key" not in public["llm_cloud_api_key_masked"]


@pytest.mark.asyncio
async def test_cloud_fallback_from_ollama(monkeypatch, settings: Settings) -> None:
    settings.llm_provider = "ollama"
    settings.ollama_base_url = "http://127.0.0.1:1"
    settings.llm_timeout_s = 1
    settings.llm_cloud_fallback = True
    settings.llm_cloud_api_key = "k"
    settings.llm_cloud_base_url = "https://api.openai.com/v1"
    settings.llm_cloud_model = "gpt-4o-mini"
    calls: list[str] = []

    class _FailResp:
        def raise_for_status(self):
            raise httpx.ConnectError("down", request=None)

    class _OkResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"ok":true}'}}]}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append(url)
            if "11434" in url or "127.0.0.1:1" in url:
                raise httpx.ConnectError("down", request=None)
            return _OkResp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    text, error = await LLMGateway(settings, apply_overrides=False).complete("s", "u")
    assert error is None
    assert text
    assert any("openai.com" in url for url in calls)


async def test_api_llm_config_roundtrip(client: httpx.AsyncClient) -> None:
    got = await client.get("/api/v1/system/llm/config")
    assert got.status_code == 200
    assert "presets" in got.json()
    assert any(p["id"] == "openrouter" for p in got.json()["presets"])
    assert any(p["id"] == "llamacpp" for p in got.json()["presets"])

    saved = await client.put(
        "/api/v1/system/llm/config",
        json={
            "provider": "openrouter",
            "llm_cloud_api_key": "test-key-9999",
            "llm_cloud_model": "openai/gpt-4o-mini",
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["provider"] == "openrouter"
    assert body["llm_cloud_api_key_set"] is True
    assert body["llm_cloud_api_key_masked"].endswith("9999")
