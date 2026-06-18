"""Tests for the OpenAI-compatible ModelClient (mocked transport)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

import fusionchat.models as models
from _helpers import chat_response, mock_client, model_cfg
from fusionchat.models import DEFAULT_CONTEXT_WINDOW, APIError, ChatMessage


def test_chat_success():
    async def go():
        async with mock_client(model_cfg(), lambda req: chat_response("hello")) as mc:
            assert await mc.chat([ChatMessage("user", "hi")]) == "hello"
    asyncio.run(go())


def test_chat_sends_max_tokens_and_temperature():
    seen = {}

    def handler(req):
        import json
        seen.update(json.loads(req.content))
        return chat_response("x")

    async def go():
        async with mock_client(model_cfg(), handler) as mc:
            await mc.chat([ChatMessage("user", "hi")], max_tokens=42, temperature=0.3)
    asyncio.run(go())
    assert seen["max_tokens"] == 42
    assert seen["temperature"] == 0.3
    assert seen["model"] == "m"


def test_chat_full_extracts_reasoning():
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": "ans", "reasoning_content": "because"}}]})

    async def go():
        async with mock_client(model_cfg(), handler) as mc:
            r = await mc.chat_full([ChatMessage("user", "hi")])
            assert r.content == "ans"
            assert r.reasoning == "because"
    asyncio.run(go())


def test_chat_full_no_reasoning_is_none():
    async def go():
        async with mock_client(model_cfg(), lambda req: chat_response("ans")) as mc:
            r = await mc.chat_full([ChatMessage("user", "hi")])
            assert r.reasoning is None
    asyncio.run(go())


def test_chat_error_status_raises():
    async def go():
        async with mock_client(model_cfg(retries=0), lambda req: httpx.Response(400, text="bad")) as mc:
            with pytest.raises(APIError, match="400"):
                await mc.chat([ChatMessage("user", "hi")])
    asyncio.run(go())


def test_chat_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(models, "_BACKOFF_BASE_SECONDS", 0)
    monkeypatch.setattr(models, "_BACKOFF_MAX_SECONDS", 0)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="slow down")
        return chat_response("recovered")

    async def go():
        async with mock_client(model_cfg(retries=2), handler) as mc:
            assert await mc.chat([ChatMessage("user", "hi")]) == "recovered"
    asyncio.run(go())
    assert calls["n"] == 2


def test_chat_retry_exhaustion(monkeypatch):
    monkeypatch.setattr(models, "_BACKOFF_BASE_SECONDS", 0)
    monkeypatch.setattr(models, "_BACKOFF_MAX_SECONDS", 0)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(503, text="down")

    async def go():
        async with mock_client(model_cfg(retries=2), handler) as mc:
            with pytest.raises(APIError, match="503"):
                await mc.chat([ChatMessage("user", "hi")])
    asyncio.run(go())
    assert calls["n"] == 3  # initial + 2 retries


def test_chat_retries_on_request_error(monkeypatch):
    monkeypatch.setattr(models, "_BACKOFF_BASE_SECONDS", 0)
    monkeypatch.setattr(models, "_BACKOFF_MAX_SECONDS", 0)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection refused", request=req)
        return chat_response("ok")

    async def go():
        async with mock_client(model_cfg(retries=1), handler) as mc:
            assert await mc.chat([ChatMessage("user", "hi")]) == "ok"
    asyncio.run(go())
    assert calls["n"] == 2


def test_chat_request_error_no_retry_raises(monkeypatch):
    def handler(req):
        raise httpx.ConnectError("nope", request=req)

    async def go():
        async with mock_client(model_cfg(retries=0), handler) as mc:
            with pytest.raises(APIError, match="Request failed"):
                await mc.chat([ChatMessage("user", "hi")])
    asyncio.run(go())


def test_chat_unexpected_shape_raises():
    async def go():
        async with mock_client(model_cfg(retries=0), lambda req: httpx.Response(200, json={"weird": 1})) as mc:
            with pytest.raises(APIError, match="Unexpected response shape"):
                await mc.chat([ChatMessage("user", "hi")])
    asyncio.run(go())


def test_context_window_from_models_endpoint():
    def handler(req):
        assert req.url.path.endswith("/v1/models")
        return httpx.Response(200, json={"data": [{"id": "m", "context_window": 200000}]})

    async def go():
        async with mock_client(model_cfg(), handler) as mc:
            assert await mc.context_window() == 200000
    asyncio.run(go())


def test_context_window_fallback_on_404():
    async def go():
        async with mock_client(model_cfg(), lambda req: httpx.Response(404)) as mc:
            assert await mc.context_window() == DEFAULT_CONTEXT_WINDOW
    asyncio.run(go())


def test_context_window_uses_configured_override():
    called = {"hit": False}

    def handler(req):
        called["hit"] = True
        return httpx.Response(200, json={})

    async def go():
        async with mock_client(model_cfg(max_context_tokens=64000), handler) as mc:
            assert await mc.context_window() == 64000
    asyncio.run(go())
    assert called["hit"] is False  # no network call when override is set
