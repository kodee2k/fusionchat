"""Web chat interface for fusionChat using FastAPI."""
from __future__ import annotations

import html
import secrets
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from jinja2 import BaseLoader, Environment, select_autoescape

from fusionchat.assets import empero_css, empero_logo_svg
from fusionchat.config import Config
from fusionchat.fusion import ChatMessage, FusionOrchestrator
from fusionchat.logging import SessionLogger

SESSION_COOKIE = "fc_session"
MAX_SESSIONS = 256
SESSION_TTL_SECONDS = 3600

# Bounded, LRU-ordered session store. Evicted/expired sessions are closed so their
# httpx clients are released — a long-running server must not leak sockets per visit.
SESSIONS: "OrderedDict[str, WebSession]" = OrderedDict()


class WebSession:
    def __init__(self, config: Config) -> None:
        self.session_id = uuid.uuid4().hex[:12]
        self.config = config
        self.logger = SessionLogger(config.log_dir, log_prompts=config.log_prompts)
        self.logger.log_config(config)
        self.orchestrator = FusionOrchestrator(config)
        self.messages: list[ChatMessage] = []
        self.history: list[dict[str, str]] = []
        self.turn = 0
        self.last_access = time.monotonic()

    def touch(self) -> None:
        self.last_access = time.monotonic()

    def reset(self) -> None:
        self.messages = []
        self.history = []

    def add_bubble(self, role: str, html_body: str, meta: str) -> None:
        self.history.append({"role": role, "html": html_body, "meta": meta})


async def _close_session(sess: WebSession) -> None:
    try:
        await sess.orchestrator.close()
    except Exception:  # noqa: BLE001 - best-effort cleanup
        pass


async def _evict() -> None:
    now = time.monotonic()
    expired = [sid for sid, s in list(SESSIONS.items()) if now - s.last_access > SESSION_TTL_SECONDS]
    for sid in expired:
        sess = SESSIONS.pop(sid, None)
        if sess is not None:
            await _close_session(sess)
    while len(SESSIONS) > MAX_SESSIONS:
        _, sess = SESSIONS.popitem(last=False)
        await _close_session(sess)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    for sess in list(SESSIONS.values()):
        await _close_session(sess)
    SESSIONS.clear()


env = Environment(loader=BaseLoader(), autoescape=select_autoescape(["html"]))
page_template = env.from_string(
    """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>fusionChat — {{ title }}</title>
    <style>{{ css|safe }}</style>
  </head>
  <body>
    <header>
      <div class="logo">{{ logo|safe }}</div>
      <h1>fusionChat</h1>
      <div class="badge">{{ effort }} · {{ master }} · {{ fusion_count }} fusion</div>
      <button id="new-chat" type="button" class="ghost">New chat</button>
    </header>
    <main id="chat">
      {% if not history %}
      <div class="empty">Start the conversation. The master will consult the fusion panel before answering.</div>
      {% endif %}
      {% for bubble in history %}
      <div class="message {{ bubble.role }}">
        {% if bubble.meta %}<div class="meta">{{ bubble.meta }}</div>{% endif %}
        {{ bubble.html|safe }}
      </div>
      {% endfor %}
    </main>
    <form id="chat-form" class="input-area" method="post" action="/chat/{{ session_id }}">
      <textarea id="message" name="message" rows="1" placeholder="Type a message…" required></textarea>
      <button id="send" type="submit">Send</button>
    </form>
    <script>
      const sessionId = "{{ session_id }}";
      const chat = document.getElementById('chat');
      const form = document.getElementById('chat-form');
      const textarea = document.getElementById('message');
      const sendBtn = document.getElementById('send');
      const newChatBtn = document.getElementById('new-chat');

      function currentEmpty() { return document.querySelector('.empty'); }

      function appendBubble(role, html, meta) {
        const empty = currentEmpty();
        if (empty) empty.remove();
        const div = document.createElement('div');
        div.className = 'message ' + role;
        div.innerHTML = (meta ? ('<div class="meta">' + meta + '</div>') : '') + html;
        chat.appendChild(div);
        chat.scrollTop = chat.scrollHeight;
        return div;
      }

      textarea.addEventListener('input', () => {
        textarea.style.height = 'auto';
        textarea.style.height = textarea.scrollHeight + 'px';
      });
      textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
      });

      newChatBtn.addEventListener('click', async () => {
        try { await fetch('/reset/' + sessionId, {method: 'POST'}); } catch (e) {}
        window.location.reload();
      });

      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const text = textarea.value.trim();
        if (!text) return;
        textarea.value = '';
        textarea.style.height = 'auto';
        sendBtn.disabled = true;
        appendBubble('user', escapeHtml(text), 'You');
        const assistant = appendBubble('assistant', '<div class="spinner"></div> fusion panel is thinking…', 'Assistant');

        try {
          const resp = await fetch('/chat/' + sessionId, {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: new URLSearchParams({message: text})
          });
          if (resp.status === 404) {
            assistant.innerHTML = '<div class="error">Session expired. Reloading…</div>';
            window.location.reload();
            return;
          }
          const data = await resp.json();
          assistant.innerHTML = (data.meta ? ('<div class="meta">' + data.meta + '</div>') : '') + data.html;
        } catch (err) {
          assistant.innerHTML = '<div class="error">Failed to get response: ' + escapeHtml(String(err)) + '</div>';
        } finally {
          sendBtn.disabled = false;
          textarea.focus();
        }
        chat.scrollTop = chat.scrollHeight;
      });

      function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
      }
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


def _render_page(config: Config, sess: WebSession) -> str:
    return page_template.render(
        title="fusionChat",
        css=empero_css(),
        logo=empero_logo_svg(),
        session_id=sess.session_id,
        effort=config.effort,
        master=config.master.model,
        fusion_count=len(config.fusion),
        history=sess.history,
    )


def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="fusionChat", lifespan=lifespan)
    auth = _make_auth(config)

    @app.get("/health")
    async def health():
        return {"status": "ok", "fusion_models": len(config.fusion), "effort": config.effort}

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(auth)])
    async def index(request: Request):
        await _evict()
        sid = request.cookies.get(SESSION_COOKIE)
        sess = SESSIONS.get(sid) if sid else None
        if sess is None:
            sess = WebSession(config)
            SESSIONS[sess.session_id] = sess
        sess.touch()
        SESSIONS.move_to_end(sess.session_id)
        resp = HTMLResponse(_render_page(config, sess))
        resp.set_cookie(
            SESSION_COOKIE,
            sess.session_id,
            httponly=True,
            samesite="strict",
            max_age=SESSION_TTL_SECONDS,
        )
        return resp

    @app.post("/reset/{session_id}", dependencies=[Depends(auth)])
    async def reset(session_id: str):
        sess = SESSIONS.get(session_id)
        if sess:
            sess.reset()
            sess.touch()
        return {"ok": True}

    @app.post("/chat/{session_id}", dependencies=[Depends(auth)])
    async def chat_post(session_id: str, message: str = Form(...)):
        await _evict()
        sess = SESSIONS.get(session_id)
        if not sess:
            return JSONResponse({"ok": False, "error": "Session not found"}, status_code=404)

        sess.touch()
        SESSIONS.move_to_end(session_id)
        sess.turn += 1
        sess.messages.append(ChatMessage(role="user", content=message))
        sess.add_bubble("user", html.escape(message), "You")

        try:
            result = await sess.orchestrator.run(sess.messages)
            sess.messages.append(ChatMessage(role="assistant", content=result.synthesis))
            sess.logger.log_turn(sess.turn, message, result)
            panel = ", ".join(m for m, _ in result.responses)
            meta = f"context {result.master_context_used} · panel {panel}"
            if result.used_fallback:
                meta += " · panel unavailable — direct answer"
            body = _markdown_to_html(result.synthesis)
            sess.add_bubble("assistant", body, meta)
            return {
                "ok": True,
                "meta": meta,
                "html": body,
                "synthesis": result.synthesis,
                "responses": [{"model": m, "response": r} for m, r in result.responses],
            }
        except Exception as exc:  # noqa: BLE001 - surface any orchestration error to the client
            sess.logger.log_error(sess.turn, str(exc))
            body = f"<div class='error'>{html.escape(str(exc))}</div>"
            sess.add_bubble("assistant", body, "Error")
            return JSONResponse({"ok": False, "meta": "Error", "html": body})

    return app


def _markdown_to_html(text: str) -> str:
    """Lightweight, XSS-safe Markdown-to-HTML for the web output.

    Every line of model output is HTML-escaped before any inline transform, so raw
    HTML in a model response is rendered as text, never executed.
    """
    lines = text.split("\n")
    out: list[str] = []
    in_code = False
    code_lang = ""
    code_buffer: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

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
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline_md(html.escape(stripped[2:]))}</li>")
            continue
        close_list()
        if line.startswith("# "):
            out.append(f"<h1>{_inline_md(html.escape(line[2:]))}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{_inline_md(html.escape(line[3:]))}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{_inline_md(html.escape(line[4:]))}</h3>")
        elif line.strip() == "":
            out.append("<br>")
        else:
            out.append(f"<p>{_inline_md(html.escape(line))}</p>")
    close_list()
    flush_code()
    return "\n".join(out)


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

    app = create_app(config)
    uvicorn.run(app, host=host, port=port)
