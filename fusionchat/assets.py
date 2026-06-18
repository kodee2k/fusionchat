"""Empero brand theme constants and shared CSS/HTML snippets."""
from __future__ import annotations

# Palette extracted from empero.org — dark, minimal, purple accent.
BACKGROUND = "#0b0c0f"
SURFACE = "#111216"
SURFACE_LIGHT = "#181a20"
BORDER = "#252830"
TEXT = "#f0f0f5"
TEXT_MUTED = "#8b8f99"
ACCENT = "#a855f7"  # purple
ACCENT_HOVER = "#c084fc"
DANGER = "#ef4444"
SUCCESS = "#22c55e"


def empero_css() -> str:
    return f"""
:root {{
  --bg: {BACKGROUND};
  --surface: {SURFACE};
  --surface-light: {SURFACE_LIGHT};
  --border: {BORDER};
  --text: {TEXT};
  --muted: {TEXT_MUTED};
  --accent: {ACCENT};
  --accent-hover: {ACCENT_HOVER};
  --danger: {DANGER};
  --radius: 0.6rem;
  --col: 800px;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}}
* {{ box-sizing: border-box; }}
html, body {{ height: 100%; }}
body {{
  margin: 0; font-family: var(--font); background: var(--bg); color: var(--text);
  display: flex; flex-direction: row; height: 100vh; overflow: hidden;
  -webkit-font-smoothing: antialiased;
}}

/* Sidebar — conversation overview */
#sidebar {{
  flex: 0 0 264px; width: 264px; height: 100vh; min-height: 0;
  background: var(--surface); border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
}}
.sb-head {{
  display: flex; align-items: center; gap: 0.6rem; padding: 0.85rem 0.95rem;
  border-bottom: 1px solid var(--border);
}}
.sb-head .logo {{ width: 24px; height: 24px; display: flex; }}
.sb-head .name {{ font-size: 0.98rem; font-weight: 600; letter-spacing: -0.01em; }}
.sb-new-btn {{
  margin: 0.65rem; padding: 0.55rem 0.75rem; background: transparent; color: var(--text);
  border: 1px solid var(--border); border-radius: var(--radius); font-weight: 500; font-size: 0.85rem;
  text-align: left; cursor: pointer; transition: background 0.12s, border-color 0.12s;
}}
.sb-new-btn:hover {{ background: var(--surface-light); border-color: var(--accent); }}
#conv-list {{ flex: 1; overflow-y: auto; padding: 0.25rem 0.4rem 0.75rem; display: flex; flex-direction: column; gap: 0.1rem; }}
.conv {{
  display: flex; align-items: center; gap: 0.4rem; padding: 0.5rem 0.55rem;
  border-radius: 0.45rem; color: var(--muted); text-decoration: none; font-size: 0.85rem;
}}
.conv:hover {{ background: var(--surface-light); color: var(--text); }}
.conv.active {{ background: var(--surface-light); color: var(--text); }}
.conv-title {{ flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.conv-del {{
  flex: 0 0 auto; opacity: 0; background: none; border: none; color: var(--muted);
  cursor: pointer; padding: 0 0.2rem; font-size: 1.05rem; line-height: 1;
}}
.conv:hover .conv-del {{ opacity: 0.8; }}
.conv-del:hover {{ color: var(--danger); background: none; opacity: 1; }}

/* App column */
#app {{ flex: 1; min-width: 0; height: 100vh; display: flex; flex-direction: column; }}
body.sb-collapsed #sidebar {{ display: none; }}

/* Header */
header {{
  display: flex; align-items: center; gap: 0.75rem; padding: 0.7rem 1.25rem;
  border-bottom: 1px solid var(--border); background: var(--surface); flex: 0 0 auto;
}}
.chat-title {{ font-size: 0.95rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.icon-btn {{
  background: transparent; border: 1px solid var(--border); color: var(--muted);
  border-radius: 0.4rem; padding: 0.25rem 0.55rem; cursor: pointer; font-size: 0.9rem; line-height: 1;
}}
.icon-btn:hover {{ background: var(--surface-light); color: var(--text); }}
header .badge {{
  margin-left: auto; font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); border: 1px solid var(--border); padding: 0.22rem 0.6rem; border-radius: 999px;
}}

/* Conversation column */
main {{
  flex: 1; overflow-y: auto; padding: 1.6rem 1rem 2rem;
  display: flex; flex-direction: column; align-items: center; gap: 0.9rem;
  scroll-behavior: smooth;
}}
.message {{
  width: 100%; max-width: var(--col);
  font-size: 0.95rem; line-height: 1.65; color: var(--text);
}}
.message.user {{
  background: var(--surface-light); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 0.7rem 1rem;
}}
.message.assistant {{ padding: 0.1rem 0.1rem; }}
.message .meta {{
  font-size: 0.72rem; color: var(--muted); margin-bottom: 0.55rem; letter-spacing: 0.01em;
}}

/* Markdown blocks (synthesis answer + panel bodies) */
.answer > :first-child, .panel-body > :first-child {{ margin-top: 0; }}
.answer > :last-child, .panel-body > :last-child {{ margin-bottom: 0; }}
.message p {{ margin: 0 0 0.75rem; }}
.message h1 {{ font-size: 1.35rem; font-weight: 700; line-height: 1.25; margin: 1.2rem 0 0.55rem; }}
.message h2 {{ font-size: 1.15rem; font-weight: 700; line-height: 1.3; margin: 1.05rem 0 0.5rem; }}
.message h3 {{ font-size: 1rem; font-weight: 700; margin: 0.9rem 0 0.4rem; color: #e8e8f0; }}
.message ul, .message ol {{ margin: 0.15rem 0 0.8rem; padding-left: 1.4rem; }}
.message li {{ margin: 0.25rem 0; }}
.message strong, .message b {{ color: #ffffff; font-weight: 650; }}
.message em, .message i {{ color: #e7e7ef; }}
.message a {{ color: var(--accent-hover); text-decoration: none; }}
.message a:hover {{ text-decoration: underline; }}
code {{
  background: rgba(255,255,255,0.07); padding: 0.12rem 0.35rem; border-radius: 0.3rem;
  font-family: var(--mono); font-size: 0.86em;
}}
pre {{
  background: rgba(255,255,255,0.04); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 0.85rem 0.95rem; overflow-x: auto; margin: 0.6rem 0; line-height: 1.5;
}}
pre code {{ background: transparent; padding: 0; font-size: 0.85em; }}

/* Collapsible panel / reasoning bubbles */
details.thinking, details.reasoning {{
  border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--surface); margin: 0 0 0.7rem; overflow: hidden;
}}
summary {{
  list-style: none; cursor: pointer; user-select: none;
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.55rem 0.85rem; font-size: 0.82rem; font-weight: 500; color: var(--muted);
  transition: color 0.12s ease;
}}
summary::-webkit-details-marker {{ display: none; }}
summary::before {{
  content: "\\25B8"; color: var(--accent); font-size: 0.72rem;
  transition: transform 0.15s ease; flex: 0 0 auto;
}}
details[open] > summary::before {{ transform: rotate(90deg); }}
summary:hover {{ color: var(--text); }}
details[open].thinking > summary, details[open].reasoning > summary {{ border-bottom: 1px solid var(--border); }}
details.model {{
  margin: 0.45rem 0.6rem; border: 1px solid var(--border);
  border-radius: 0.45rem; background: var(--bg);
}}
details.model > summary {{ font-family: var(--mono); font-size: 0.8rem; color: var(--accent-hover); padding: 0.45rem 0.7rem; }}
details.model details.reasoning {{ margin: 0.4rem 0.6rem; }}
.panel-body {{ padding: 0.5rem 0.9rem 0.7rem; font-size: 0.9rem; line-height: 1.6; color: #c9ccd6; }}
.badge-err {{
  color: var(--danger); border: 1px solid var(--danger); border-radius: 999px;
  padding: 0 0.45rem; font-size: 0.62rem; margin-left: 0.45rem;
  text-transform: uppercase; letter-spacing: 0.05em;
}}

/* Input */
.input-area {{
  border-top: 1px solid var(--border); background: var(--surface);
  padding: 0.85rem 1.25rem; display: flex; gap: 0.75rem; align-items: flex-end;
  flex: 0 0 auto;
}}
textarea {{
  flex: 1; background: var(--bg); color: var(--text); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 0.7rem 1rem; font-family: inherit; font-size: 0.95rem;
  resize: none; outline: none; min-height: 46px; max-height: 200px; line-height: 1.5;
}}
textarea:focus {{ border-color: var(--accent); }}
button {{
  background: var(--accent); color: #fff; border: none; border-radius: var(--radius);
  padding: 0.7rem 1.2rem; font-weight: 600; cursor: pointer; transition: background 0.15s;
}}
button:hover {{ background: var(--accent-hover); }}
button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
button.ghost {{
  background: transparent; color: var(--muted); border: 1px solid var(--border);
  padding: 0.35rem 0.75rem; font-size: 0.75rem; font-weight: 500;
}}
button.ghost:hover {{ background: var(--surface-light); color: var(--text); }}

.empty {{ color: var(--muted); text-align: center; margin: auto; font-size: 0.95rem; max-width: 460px; }}
.spinner {{
  width: 15px; height: 15px; border: 2px solid var(--border);
  border-top-color: var(--accent); border-radius: 50%;
  animation: spin 0.8s linear infinite; display: inline-block; vertical-align: middle;
}}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
.error {{ color: var(--danger); font-size: 0.88rem; padding: 0.5rem 0.75rem; border: 1px solid var(--danger); border-radius: var(--radius); background: rgba(239,68,68,0.08); }}
""".strip()


def empero_logo_svg() -> str:
    """Simple inline 'E' mark matching the provided logo: purple strokes in a square frame."""
    return f'''<svg viewBox="0 0 200 200" width="28" height="28" xmlns="http://www.w3.org/2000/svg">
  <rect x="25" y="25" width="150" height="150" rx="12" fill="none" stroke="{ACCENT}" stroke-width="18"/>
  <line x1="55" y1="70" x2="145" y2="70" stroke="{ACCENT}" stroke-width="18" stroke-linecap="round"/>
  <line x1="55" y1="100" x2="110" y2="100" stroke="{ACCENT}" stroke-width="18" stroke-linecap="round"/>
  <line x1="55" y1="130" x2="145" y2="130" stroke="{ACCENT}" stroke-width="18" stroke-linecap="round"/>
</svg>'''
