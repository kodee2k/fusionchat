"""Tests for the OpenAI-compatible --api server."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

import fusionchat.api as api
from _helpers import make_config
from fusionchat.fusion import FusionPrep, FusionResult, PanelResponse
from fusionchat.models import APIError


async def run_ok(messages):
    return FusionResult(
        responses=[PanelResponse("m1", "r1")],
        synthesis="hello world",
        master_context_used=128_000,
        per_fusion_max_tokens=1000,
        used_fallback=False,
    )


async def run_fail(messages):
    raise APIError("boom")


class _FakeMaster:
    def __init__(self, cfg):
        self.cfg = cfg

    async def stream_chat(self, messages, max_tokens=None, temperature=None):
        for piece in ["hel", "lo ", "world"]:
            yield piece


def make_app(monkeypatch, tmp_path, run_impl=run_ok, **cfgkw):
    config = make_config(tmp_path, **cfgkw)

    class FakeOrch:
        def __init__(self, c):
            self.config = c
            self.master_client = _FakeMaster(c.master)

        async def run(self, messages):
            return await run_impl(messages)

        async def prepare(self, messages):
            return FusionPrep(
                panel=[PanelResponse("m1", "r1")],
                prompt_text="synthesize this",
                synth_max=100,
                master_context=128_000,
                per_fusion_budget=1000,
                used_fallback=False,
            )

        async def close(self):
            pass

    monkeypatch.setattr(api, "FusionOrchestrator", FakeOrch)
    return config, api.create_api_app(config)


def test_health(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path)
    assert TestClient(app).get("/health").json()["status"] == "ok"


def test_list_models(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path)
    data = TestClient(app).get("/v1/models").json()
    assert data["object"] == "list"
    assert data["data"][0]["id"] == "fusion"


def test_chat_completion_nonstream(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path)
    r = TestClient(app).post(
        "/v1/chat/completions",
        json={"model": "fusion", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["object"] == "chat.completion"
    assert d["model"] == "fusion"
    assert d["choices"][0]["message"]["content"] == "hello world"
    assert d["choices"][0]["finish_reason"] == "stop"
    assert d["usage"]["total_tokens"] > 0


def test_chat_completion_multimodal_content(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path)
    r = TestClient(app).post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": [{"type": "text", "text": "hi there"}]}]},
    )
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "hello world"


def test_chat_completion_stream(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path)
    r = TestClient(app).post(
        "/v1/chat/completions",
        json={"stream": True, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200
    body = r.text
    assert body.strip().endswith("data: [DONE]")
    content = ""
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        chunk = json.loads(line[6:])
        assert chunk["object"] == "chat.completion.chunk"
        content += chunk["choices"][0]["delta"].get("content", "")
    assert content == "hello world"


def test_bad_request_empty_messages(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path)
    r = TestClient(app).post("/v1/chat/completions", json={"messages": []})
    assert r.status_code == 400
    assert "error" in r.json()


def test_error_returns_openai_error_shape(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_impl=run_fail)
    r = TestClient(app).post(
        "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert r.status_code == 502
    assert r.json()["error"]["type"] == "fusion_error"


def test_auth_required_when_password_set(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, web_password="sek")
    client = TestClient(app)
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer sek"}).status_code == 200
    assert client.post(
        "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    ).status_code == 401
    ok = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sek"},
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert ok.status_code == 200
    assert client.get("/health").status_code == 200  # health stays open
