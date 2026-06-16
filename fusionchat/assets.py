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
  --radius: 0.5rem;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; font-family: var(--font); background: var(--bg); color: var(--text);
  display: flex; flex-direction: column; height: 100vh;
}}
header {{
  display: flex; align-items: center; gap: 0.75rem; padding: 0.9rem 1.25rem;
  border-bottom: 1px solid var(--border); background: var(--surface);
}}
header .logo {{ width: 28px; height: 28px; }}
header h1 {{ margin: 0; font-size: 1.1rem; font-weight: 600; letter-spacing: -0.01em; }}
header .badge {{
  margin-left: auto; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); border: 1px solid var(--border); padding: 0.2rem 0.5rem; border-radius: 999px;
}}
main {{ flex: 1; overflow-y: auto; padding: 1.25rem; display: flex; flex-direction: column; gap: 1rem; }}
.message {{
  max-width: 85%; padding: 0.9rem 1.1rem; border-radius: var(--radius);
  line-height: 1.55; font-size: 0.95rem; white-space: pre-wrap;
}}
.message.user {{ align-self: flex-end; background: var(--surface-light); border: 1px solid var(--border); }}
.message.assistant {{ align-self: flex-start; background: var(--surface); border: 1px solid var(--border); }}
.message .meta {{ font-size: 0.7rem; color: var(--muted); margin-bottom: 0.35rem; }}
.input-area {{
  border-top: 1px solid var(--border); background: var(--surface);
  padding: 0.85rem 1.25rem; display: flex; gap: 0.75rem; align-items: flex-end;
}}
textarea {{
  flex: 1; background: var(--bg); color: var(--text); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 0.75rem 1rem; font-family: inherit; font-size: 0.95rem;
  resize: none; outline: none; min-height: 48px; max-height: 200px; line-height: 1.5;
}}
textarea:focus {{ border-color: var(--accent); }}
button {{
  background: var(--accent); color: #fff; border: none; border-radius: var(--radius);
  padding: 0.75rem 1.2rem; font-weight: 500; cursor: pointer; transition: background 0.15s;
}}
button:hover {{ background: var(--accent-hover); }}
button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
button.ghost {{
  background: transparent; color: var(--muted); border: 1px solid var(--border);
  padding: 0.35rem 0.75rem; font-size: 0.75rem; font-weight: 500;
}}
button.ghost:hover {{ background: var(--surface-light); color: var(--text); }}
header button.ghost {{ margin-left: 0.5rem; }}
.empty {{ color: var(--muted); text-align: center; margin: auto; font-size: 0.95rem; }}
.spinner {{
  width: 16px; height: 16px; border: 2px solid var(--border);
  border-top-color: var(--accent); border-radius: 50%;
  animation: spin 0.8s linear infinite; display: inline-block; vertical-align: middle;
}}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
.error {{ color: var(--danger); font-size: 0.85rem; padding: 0.5rem 1rem; }}
code {{
  background: rgba(255,255,255,0.06); padding: 0.15rem 0.35rem; border-radius: 0.3rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.88em;
}}
pre {{
  background: rgba(255,255,255,0.04); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 0.8rem; overflow-x: auto; margin: 0.6rem 0;
}}
pre code {{ background: transparent; padding: 0; }}
""".strip()


def empero_logo_svg() -> str:
    """Simple inline 'E' mark matching the provided logo: purple strokes in a square frame."""
    return f'''<svg viewBox="0 0 200 200" width="28" height="28" xmlns="http://www.w3.org/2000/svg">
  <rect x="25" y="25" width="150" height="150" rx="12" fill="none" stroke="{ACCENT}" stroke-width="18"/>
  <line x1="55" y1="70" x2="145" y2="70" stroke="{ACCENT}" stroke-width="18" stroke-linecap="round"/>
  <line x1="55" y1="100" x2="110" y2="100" stroke="{ACCENT}" stroke-width="18" stroke-linecap="round"/>
  <line x1="55" y1="130" x2="145" y2="130" stroke="{ACCENT}" stroke-width="18" stroke-linecap="round"/>
</svg>'''
