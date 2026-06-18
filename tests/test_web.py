"""Tests for the FastAPI web interface, conversation overview, and markdown renderer."""
from __future__ import annotations

from fastapi.testclient import TestClient

import fusionchat.web as web
from _helpers import make_config
from fusionchat.fusion import FusionResult, PanelResponse


async def run_ok(messages):
    return FusionResult(
        responses=[
            PanelResponse(model="m1", content="r1", reasoning="m1 thinking"),
            PanelResponse(model="m2", content="r2"),
        ],
        synthesis="**hi**\n- x\n- y",
        master_context_used=128_000,
        per_fusion_max_tokens=1000,
        used_fallback=False,
        master_reasoning="master thinking",
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


def only_conv_id():
    return next(iter(web.CONVERSATIONS))


def test_index_creates_conversation(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "fusionChat" in r.text
    assert "New chat" in r.text  # sidebar button + default title
    assert len(web.CONVERSATIONS) == 1


def test_index_reuses_recent(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    client.get("/")
    client.get("/")
    client.get("/")
    assert len(web.CONVERSATIONS) == 1  # no per-load leak


def test_health_open(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["fusion_models"] == 2


def test_new_chat_creates_separate_conversation(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    client.get("/")
    r = client.post("/new")
    new_id = r.json()["id"]
    assert new_id in web.CONVERSATIONS
    assert len(web.CONVERSATIONS) == 2


def test_chat_flow_sets_title_and_renders(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    client.get("/")
    cid = only_conv_id()
    r = client.post(f"/chat/{cid}", data={"message": "hello world"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["title"] == "hello world"
    assert "<b>hi</b>" in data["html"]
    assert "Fusion panel" in data["html"]
    assert "Master reasoning" in data["html"]
    assert data["responses"][0]["reasoning"] == "m1 thinking"
    assert web.CONVERSATIONS[cid].title == "hello world"
    # reload renders the history and the sidebar title
    page = client.get(f"/?c={cid}").text
    assert "<b>hi</b>" in page
    assert "hello world" in page


def test_switch_between_conversations(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    client.get("/")
    id1 = only_conv_id()
    id2 = client.post("/new").json()["id"]
    page = client.get(f"/?c={id2}").text
    # both chats appear in the sidebar; the requested one is active
    assert f'href="/?c={id1}"' in page
    assert f'class="conv active" href="/?c={id2}"' in page


def test_delete_conversation(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    client.get("/")
    id1 = only_conv_id()
    id2 = client.post("/new").json()["id"]
    client.post(f"/delete/{id1}")
    assert id1 not in web.CONVERSATIONS
    assert id2 in web.CONVERSATIONS


def test_unknown_conversation_404(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    r = client.post("/chat/deadbeef", data={"message": "hi"})
    assert r.status_code == 404


def test_error_path_returns_unescaped_html(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_fail)
    client = TestClient(app)
    client.get("/")
    cid = only_conv_id()
    data = client.post(f"/chat/{cid}", data={"message": "hi"}).json()
    assert data["ok"] is False
    assert data["html"].startswith("<div class='error'>")
    assert "&lt;div" not in data["html"]
    assert "kaboom &lt;tag&gt;" in data["html"]


def test_auth_required_when_password_set(monkeypatch, tmp_path):
    _, app = make_app(monkeypatch, tmp_path, run_ok, web_password="pw")
    client = TestClient(app)
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("u", "wrong")).status_code == 401
    assert client.get("/", auth=("u", "pw")).status_code == 200
    assert client.get("/health").status_code == 200  # health stays open


def test_persistence_round_trip(monkeypatch, tmp_path):
    config, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    client.get("/")
    cid = only_conv_id()
    client.post(f"/chat/{cid}", data={"message": "remember me"})
    # Simulate a restart: drop in-memory state, reload from disk.
    web.CONVERSATIONS.clear()
    web.load_conversations(config)
    assert cid in web.CONVERSATIONS
    restored = web.CONVERSATIONS[cid]
    assert restored.title == "remember me"
    assert len(restored.messages) == 2  # user + assistant
    assert any("<b>hi</b>" in b["html"] for b in restored.history if b["role"] == "assistant")


def test_empty_chats_not_persisted(monkeypatch, tmp_path):
    config, app = make_app(monkeypatch, tmp_path, run_ok)
    client = TestClient(app)
    client.get("/")  # creates an empty conversation, never messaged
    web.CONVERSATIONS.clear()
    web.load_conversations(config)
    assert len(web.CONVERSATIONS) == 0  # empty chats aren't saved


def test_eviction_caps_conversations(monkeypatch, tmp_path):
    config, _ = make_app(monkeypatch, tmp_path, run_ok)
    monkeypatch.setattr(web, "MAX_CONVERSATIONS", 2)
    for _ in range(3):
        web._new_conversation(config)
    assert len(web.CONVERSATIONS) <= 2


# --- markdown renderer ---

def test_markdown_lists():
    out = web._markdown_to_html("- a\n- b")
    assert out.count("<li>") == 2
    assert "<ul>" in out and "</ul>" in out


def test_markdown_ordered_list():
    out = web._markdown_to_html("1. first\n2. second")
    assert out.count("<li>") == 2
    assert "<ol>" in out and "</ol>" in out


def test_markdown_blank_lines_no_br():
    out = web._markdown_to_html("para one\n\npara two")
    assert "<br>" not in out
    assert out.count("<p>") == 2


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
