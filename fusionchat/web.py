"""Web chat interface for fusionChat using FastAPI.

Conversations are app-global (a personal/local multi-chat tool): one shared,
stateless orchestrator serves every chat, and each chat keeps its own message
history, rendered bubbles, and JSONL session log.
"""
from __future__ import annotations

import html
import json
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from jinja2 import BaseLoader, Environment, select_autoescape

from fusionchat.assets import empero_css, empero_logo_svg
from fusionchat.config import Config
from fusionchat.fusion import ChatMessage, FusionOrchestrator, FusionResult
from fusionchat.logging import SessionLogger

MAX_CONVERSATIONS = 200

# App-global conversation store (insertion order = creation order). Bounded by
# MAX_CONVERSATIONS via least-recently-accessed eviction.
CONVERSATIONS: "dict[str, Conversation]" = {}


def _title_from(message: str) -> str:
    text = " ".join(message.strip().split())
    if not text:
        return "New chat"
    return text[:40] + "…" if len(text) > 40 else text


class Conversation:
    def __init__(self, config: Config) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.config = config
        self._logger: SessionLogger | None = None
        self.title = "New chat"
        self.messages: list[ChatMessage] = []
        self.history: list[dict[str, str]] = []
        self.turn = 0
        self.updated_at = time.time()

    @property
    def logger(self) -> SessionLogger:
        # Created lazily so empty / restored-but-untouched chats don't spawn log files.
        if self._logger is None:
            self._logger = SessionLogger(self.config.log_dir, log_prompts=self.config.log_prompts)
            self._logger.log_config(self.config)
        return self._logger

    def touch(self) -> None:
        self.updated_at = time.time()

    def add_bubble(self, role: str, html_body: str, meta: str) -> None:
        self.history.append({"role": role, "html": html_body, "meta": meta})

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "turn": self.turn,
            "updated_at": self.updated_at,
            "messages": [{"role": m.role, "content": m.content} for m in self.messages],
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, config: Config, data: dict) -> "Conversation":
        conv = cls(config)
        conv.id = str(data["id"])
        conv.title = data.get("title") or "New chat"
        conv.turn = int(data.get("turn", 0))
        conv.updated_at = float(data.get("updated_at", time.time()))
        conv.messages = [
            ChatMessage(role=m["role"], content=m["content"]) for m in data.get("messages", [])
        ]
        conv.history = list(data.get("history", []))
        return conv


def _conv_dir(config: Config) -> Path:
    return Path(config.log_dir).expanduser().parent / "conversations"


def _save(config: Config, conv: Conversation) -> None:
    """Persist a conversation to disk (best-effort)."""
    try:
        directory = _conv_dir(config)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{conv.id}.json").write_text(
            json.dumps(conv.to_dict(), ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def _delete_file(config: Config, conv_id: str) -> None:
    try:
        (_conv_dir(config) / f"{conv_id}.json").unlink(missing_ok=True)
    except OSError:
        pass


def load_conversations(config: Config) -> None:
    """Load persisted conversations from disk into the in-memory store (call at startup)."""
    directory = _conv_dir(config)
    if not directory.exists():
        return
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            conv = Conversation.from_dict(config, data)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        CONVERSATIONS[conv.id] = conv
    _evict(config)


def _new_conversation(config: Config) -> Conversation:
    conv = Conversation(config)
    CONVERSATIONS[conv.id] = conv
    _evict(config)
    return conv


def _evict(config: Config | None = None) -> None:
    while len(CONVERSATIONS) > MAX_CONVERSATIONS:
        oldest = min(CONVERSATIONS.values(), key=lambda c: c.updated_at)
        CONVERSATIONS.pop(oldest.id, None)
        if config is not None:
            _delete_file(config, oldest.id)


def _ordered_conversations() -> list[Conversation]:
    """Most-recently-active first."""
    return sorted(CONVERSATIONS.values(), key=lambda c: c.updated_at, reverse=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    orch = getattr(app.state, "orchestrator", None)
    if orch is not None:
        try:
            await orch.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
    CONVERSATIONS.clear()


env = Environment(loader=BaseLoader(), autoescape=select_autoescape(["html"]))
page_template = env.from_string(
    """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>fusionChat — {{ active.title }}</title>
    <style>{{ css|safe }}</style>
  </head>
  <body>
    <aside id="sidebar">
      <div class="sb-head">
        <div class="logo">{{ logo|safe }}</div>
        <div class="name">fusionChat</div>
      </div>
      <button id="new-chat" class="sb-new-btn" type="button">+ New chat</button>
      <nav id="conv-list">
        {% for cv in conversations %}
        <a class="conv {% if cv.id == active.id %}active{% endif %}" href="/?c={{ cv.id }}" data-id="{{ cv.id }}">
          <span class="conv-title">{{ cv.title }}</span>
          <button class="conv-del" type="button" data-id="{{ cv.id }}" title="Delete chat">&times;</button>
        </a>
        {% endfor %}
      </nav>
    </aside>
    <div id="app">
      <header>
        <button id="sb-toggle" class="icon-btn" type="button" title="Toggle sidebar">&#9776;</button>
        <div class="chat-title">{{ active.title }}</div>
        <div class="badge">{{ effort }} · {{ master }} · {{ fusion_count }} fusion</div>
      </header>
      <main id="chat">
        {% if not active.history %}
        <div class="empty">Start the conversation. The master will consult the fusion panel before answering.</div>
        {% endif %}
        {% for bubble in active.history %}
        <div class="message {{ bubble.role }}">
          {% if bubble.meta %}<div class="meta">{{ bubble.meta }}</div>{% endif %}
          {{ bubble.html|safe }}
        </div>
        {% endfor %}
      </main>
      <form id="chat-form" class="input-area" method="post" action="/chat/{{ active.id }}">
        <textarea id="message" name="message" rows="1" placeholder="Type a message…" required></textarea>
        <button id="send" type="submit">Send</button>
      </form>
    </div>
    <script>
      const activeId = "{{ active.id }}";
      const chat = document.getElementById('chat');
      const form = document.getElementById('chat-form');
      const textarea = document.getElementById('message');
      const sendBtn = document.getElementById('send');
      const newBtn = document.getElementById('new-chat');
      const sbToggle = document.getElementById('sb-toggle');

      function escapeHtml(t) {
        const d = document.createElement('div'); d.textContent = t; return d.innerHTML;
      }
      function currentEmpty() { return document.querySelector('.empty'); }
      function appendBubble(role, html, meta) {
        const e = currentEmpty(); if (e) e.remove();
        const div = document.createElement('div');
        div.className = 'message ' + role;
        div.innerHTML = (meta ? ('<div class="meta">' + meta + '</div>') : '') + html;
        chat.appendChild(div); chat.scrollTop = chat.scrollHeight; return div;
      }

      textarea.addEventListener('input', () => {
        textarea.style.height = 'auto'; textarea.style.height = textarea.scrollHeight + 'px';
      });
      textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
      });

      if (sbToggle) sbToggle.addEventListener('click', () => document.body.classList.toggle('sb-collapsed'));

      if (newBtn) newBtn.addEventListener('click', async () => {
        try {
          const r = await fetch('/new', {method: 'POST'});
          const d = await r.json();
          window.location.href = '/?c=' + d.id;
        } catch (e) {}
      });

      document.querySelectorAll('.conv-del').forEach((btn) => {
        btn.addEventListener('click', async (e) => {
          e.preventDefault(); e.stopPropagation();
          const id = btn.dataset.id;
          try { await fetch('/delete/' + id, {method: 'POST'}); } catch (e) {}
          if (id === activeId) { window.location.href = '/'; }
          else { const a = btn.closest('.conv'); if (a) a.remove(); }
        });
      });

      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const text = textarea.value.trim();
        if (!text) return;
        textarea.value = ''; textarea.style.height = 'auto'; sendBtn.disabled = true;
        appendBubble('user', escapeHtml(text), 'You');
        const assistant = appendBubble('assistant', '<div class="spinner"></div> fusion panel is thinking…', 'Assistant');
        try {
          const resp = await fetch('/chat/' + activeId, {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: new URLSearchParams({message: text})
          });
          if (resp.status === 404) { window.location.href = '/'; return; }
          const data = await resp.json();
          assistant.innerHTML = (data.meta ? ('<div class="meta">' + data.meta + '</div>') : '') + data.html;
          if (data.title) {
            const t = document.querySelector('.conv.active .conv-title'); if (t) t.textContent = data.title;
            const ct = document.querySelector('.chat-title'); if (ct) ct.textContent = data.title;
          }
        } catch (err) {
          assistant.innerHTML = '<div class="error">Failed to get response: ' + escapeHtml(String(err)) + '</div>';
        } finally {
          sendBtn.disabled = false; textarea.focus();
        }
        chat.scrollTop = chat.scrollHeight;
      });
    </script>
  </body>
</html>
"""
)


def _make_auth(config: Config):
    security = HTTPBasic(auto_error=False)

    async def auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
        if not config.web_password:
            return
        ok = credentials is not None and secrets.compare_digest(
            credentials.password, config.web_password
        )
        if not ok:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Basic"},
            )

    return auth


def _render_app(config: Config, active: Conversation) -> str:
    return page_template.render(
        css=empero_css(),
        logo=empero_logo_svg(),
        effort=config.effort,
        master=config.master.model,
        fusion_count=len(config.fusion),
        conversations=_ordered_conversations(),
        active=active,
    )


def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="fusionChat", lifespan=lifespan)
    app.state.orchestrator = FusionOrchestrator(config)
    auth = _make_auth(config)

    @app.get("/health")
    async def health():
        return {"status": "ok", "fusion_models": len(config.fusion), "effort": config.effort}

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(auth)])
    async def index(c: str | None = None):
        _evict(config)
        conv = CONVERSATIONS.get(c) if c else None
        if conv is None:
            ordered = _ordered_conversations()
            conv = ordered[0] if ordered else _new_conversation(config)
        conv.touch()
        return HTMLResponse(_render_app(config, conv))

    @app.post("/new", dependencies=[Depends(auth)])
    async def new_chat():
        conv = _new_conversation(config)
        return {"id": conv.id, "title": conv.title}

    @app.post("/delete/{conv_id}", dependencies=[Depends(auth)])
    async def delete_chat(conv_id: str):
        CONVERSATIONS.pop(conv_id, None)
        _delete_file(config, conv_id)
        return {"ok": True}

    @app.post("/chat/{conv_id}", dependencies=[Depends(auth)])
    async def chat_post(conv_id: str, message: str = Form(...)):
        conv = CONVERSATIONS.get(conv_id)
        if not conv:
            return JSONResponse({"ok": False, "error": "Conversation not found"}, status_code=404)

        conv.touch()
        conv.turn += 1
        if conv.title == "New chat":
            conv.title = _title_from(message)
        conv.messages.append(ChatMessage(role="user", content=message))
        conv.add_bubble("user", html.escape(message), "You")

        try:
            result = await app.state.orchestrator.run(conv.messages)
            conv.messages.append(ChatMessage(role="assistant", content=result.synthesis))
            conv.logger.log_turn(conv.turn, message, result)
            panel = ", ".join(p.model for p in result.responses)
            meta = f"context {result.master_context_used} · panel {panel}"
            if result.used_fallback:
                meta += " · panel unavailable — direct answer"
            body = _render_assistant_html(result)
            conv.add_bubble("assistant", body, meta)
            _save(config, conv)
            return {
                "ok": True,
                "title": conv.title,
                "meta": meta,
                "html": body,
                "synthesis": result.synthesis,
                "master_reasoning": result.master_reasoning,
                "responses": [
                    {"model": p.model, "response": p.content, "reasoning": p.reasoning, "ok": p.ok}
                    for p in result.responses
                ],
            }
        except Exception as exc:  # noqa: BLE001 - surface any orchestration error to the client
            conv.logger.log_error(conv.turn, str(exc))
            body = f"<div class='error'>{html.escape(str(exc))}</div>"
            conv.add_bubble("assistant", body, "Error")
            _save(config, conv)
            return JSONResponse({"ok": False, "title": conv.title, "meta": "Error", "html": body})

    return app


def _render_assistant_html(result: FusionResult) -> str:
    """Assemble a synthesized answer plus collapsible panel + reasoning sections.

    Layout: a collapsed "Fusion panel" group (one expandable bubble per model,
    each with its reasoning nested if the provider returned any), then a collapsed
    "Master reasoning" bubble if available, then the synthesized answer.
    """
    parts: list[str] = []

    if result.responses:
        n = len(result.responses)
        label = f"Fusion panel · {n} model" + ("s" if n != 1 else "")
        items: list[str] = []
        for p in result.responses:
            badge = "" if p.ok else " <span class='badge-err'>error</span>"
            reasoning = ""
            if p.reasoning:
                reasoning = (
                    "<details class='reasoning'><summary>Reasoning</summary>"
                    f"<div class='panel-body'>{_markdown_to_html(p.reasoning)}</div></details>"
                )
            items.append(
                f"<details class='model'><summary>{html.escape(p.model)}{badge}</summary>"
                f"{reasoning}<div class='panel-body'>{_markdown_to_html(p.content)}</div></details>"
            )
        parts.append(
            f"<details class='thinking'><summary>{html.escape(label)}</summary>"
            f"{''.join(items)}</details>"
        )

    if result.master_reasoning:
        parts.append(
            "<details class='reasoning master'><summary>Master reasoning</summary>"
            f"<div class='panel-body'>{_markdown_to_html(result.master_reasoning)}</div></details>"
        )

    parts.append(f"<div class='answer'>{_markdown_to_html(result.synthesis)}</div>")
    return "".join(parts)


def _markdown_to_html(text: str) -> str:
    """Lightweight, XSS-safe Markdown-to-HTML for the web output.

    Every line of model output is HTML-escaped before any inline transform, so raw
    HTML in a model response is rendered as text, never executed. Blank lines are
    block separators (handled by CSS margins) rather than literal <br> tags.
    """
    lines = text.split("\n")
    out: list[str] = []
    in_code = False
    code_lang = ""
    code_buffer: list[str] = []
    list_tag: str | None = None  # None | "ul" | "ol"

    def open_list(tag: str) -> None:
        nonlocal list_tag
        if list_tag != tag:
            close_list()
            out.append(f"<{tag}>")
            list_tag = tag

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    def flush_code() -> None:
        nonlocal in_code, code_buffer, code_lang
        if in_code:
            body = html.escape("\n".join(code_buffer))
            lang = html.escape(code_lang)
            out.append(f'<pre><code class="language-{lang}">{body}</code></pre>')
            in_code = False
            code_buffer = []
            code_lang = ""

    for raw in lines:
        line = raw
        if line.startswith("```"):
            if in_code:
                flush_code()
            else:
                close_list()
                in_code = True
                code_lang = line[3:].strip()
            continue
        if in_code:
            code_buffer.append(raw)
            continue
        stripped = line.lstrip()
        if not stripped:
            # Blank line: a block separator. Keep an open list intact across it.
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            open_list("ul")
            out.append(f"<li>{_inline_md(html.escape(stripped[2:]))}</li>")
            continue
        ordered = _ordered_item(stripped)
        if ordered is not None:
            open_list("ol")
            out.append(f"<li>{_inline_md(html.escape(ordered))}</li>")
            continue
        close_list()
        if line.startswith("# "):
            out.append(f"<h1>{_inline_md(html.escape(line[2:]))}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{_inline_md(html.escape(line[3:]))}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{_inline_md(html.escape(line[4:]))}</h3>")
        else:
            out.append(f"<p>{_inline_md(html.escape(line))}</p>")
    close_list()
    flush_code()
    return "\n".join(out)


def _ordered_item(stripped: str) -> str | None:
    """Return the content of a '1. '-style ordered-list line, or None."""
    i = 0
    while i < len(stripped) and stripped[i].isdigit():
        i += 1
    if i and stripped[i:i + 2] == ". ":
        return stripped[i + 2:]
    return None


def _inline_md(text: str) -> str:
    # Bold before italic so ** is consumed first.
    text = _replace_pairs(text, "**", "<b>", "</b>")
    text = _replace_pairs(text, "*", "<i>", "</i>")
    text = _replace_pairs(text, "`", "<code>", "</code>")
    return text


def _replace_pairs(text: str, marker: str, open_tag: str, close_tag: str) -> str:
    parts = text.split(marker)
    if len(parts) < 3:
        return text
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            result.append(f"{open_tag}{part}{close_tag}")
        else:
            result.append(part)
    return "".join(result)


def run_web(config: Config, host: str, port: int) -> None:
    import uvicorn

    load_conversations(config)
    app = create_app(config)
    uvicorn.run(app, host=host, port=port)
