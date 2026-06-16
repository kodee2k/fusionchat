"""Tests for the FastAPI web interface and markdown renderer."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

import fusionchat.web as web
from _helpers import make_config
from fusionchat.fusion import FusionResult


async def run_ok(messages):
    return FusionResult(
        responses=[("m1", "r1"), ("m2", "r2")],
        synthesis="**hi**\n- x\n- y",
        master_context_used=128_000,
        per_fusion_max_tokens=1000,
        used_fallback=False,
    )


async def run_fail(messages):
    raise RuntimeError("kaboom <tag>")


def make_app(monkeypatch, tmp_path, run_impl, **cfgkw):
    config = make_config(tmp_path, **cfgkw)

    class Fake:
        def __init__(self, c):
            self.config = c

        async def run(self, messages):
            return await run_impl(messages)

        async def close(self):
            pass

    monkeypatch.setattr(web, "FusionOrchestrator", Fake)
    return config, web.create_app(config)


def test_index_sets_cookie(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "fusionChat" in r.text
    assert client.cookies.get("fc_session")
    assert len(web.SESSIONS) == 1


def test_health_open(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["fusion_models"] == 2


def test_chat_flow_and_history(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    client.get("/")
    sid = client.cookies.get("fc_session")
    r = client.post(f"/chat/{sid}", data={"message": "hello"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "<b>hi</b>" in data["html"]
    assert "context 128000" in data["meta"]
    # history is rendered server-side on reload (no per-load leak / no hidden context)
    page = client.get("/").text
    assert "<b>hi</b>" in page


def test_session_reuse_no_leak(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    client.get("/")
    client.get("/")
    client.get("/")
    assert len(web.SESSIONS) == 1


def test_unknown_session_404(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    r = client.post("/chat/deadbeef", data={"message": "hi"})
    assert r.status_code == 404


def test_error_path_returns_unescaped_html(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_fail)
    client = TestClient(app)
    client.get("/")
    sid = client.cookies.get("fc_session")
    data = client.post(f"/chat/{sid}", data={"message": "hi"}).json()
    assert data["ok"] is False
    assert data["html"].startswith("<div class='error'>")
    assert "&lt;div" not in data["html"]
    # the exception text itself is still escaped
    assert "kaboom &lt;tag&gt;" in data["html"]


def test_reset_clears_history(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    client.get("/")
    sid = client.cookies.get("fc_session")
    client.post(f"/chat/{sid}", data={"message": "hi"})
    assert web.SESSIONS[sid].history
    client.post(f"/reset/{sid}")
    assert web.SESSIONS[sid].history == []
    assert "Start the conversation" in client.get("/").text


def test_auth_required_when_password_set(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok, web_password="pw")
    client = TestClient(app)
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("u", "wrong")).status_code == 401
    assert client.get("/", auth=("u", "pw")).status_code == 200
    # health endpoint stays open for monitoring
    assert client.get("/health").status_code == 200


def test_eviction_closes_oldest(monkeypatch, tmp_path):
    config, _ = make_app(monkeypatch, tmp_path, run_ok)
    monkeypatch.setattr(web, "MAX_SESSIONS", 2)
    sessions = [web.WebSession(config) for _ in range(3)]
    for s in sessions:
        web.SESSIONS[s.session_id] = s
    asyncio.run(web._evict())
    assert len(web.SESSIONS) == 2
    assert sessions[0].session_id not in web.SESSIONS


def test_ttl_eviction(monkeypatch, tmp_path):
    config, _ = make_app(monkeypatch, tmp_path, run_ok)
    monkeypatch.setattr(web, "SESSION_TTL_SECONDS", 1)
    s = web.WebSession(config)
    web.SESSIONS[s.session_id] = s
    s.last_access -= 10  # pretend it is old
    asyncio.run(web._evict())
    assert s.session_id not in web.SESSIONS


# --- markdown renderer ---

def test_markdown_lists():
    out = web._markdown_to_html("- a\n- b")
    assert out.count("<li>") == 2
    assert "<ul>" in out and "</ul>" in out


def test_markdown_code_block():
    out = web._markdown_to_html("```python\nprint(1)\n```")
    assert "<pre>" in out and 'language-python' in out and "print(1)" in out


def test_markdown_escapes_html():
    out = web._markdown_to_html("<script>alert(1)</script>")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_markdown_inline():
    out = web._markdown_to_html("this is **bold** and `code`")
    assert "<b>bold</b>" in out
    assert "<code>code</code>" in out
