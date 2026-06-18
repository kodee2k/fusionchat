# fusionChat

A minimal, professional multi-model fusion chat from Empero.

## How it works

1. **You** send a message.
2. The **master model** asks up to **3 independent fusion models** the same task.
3. The master receives all fusion responses and **synthesizes** one coherent final answer.
4. Every turn and every session is logged.

If every fusion model fails, the master answers you directly instead of synthesizing
from error messages.

## Install

```bash
pip install .
```

Then run:

```bash
fusionchat
```

First launch creates a default config at `~/.config/fusionchat/fusionchat.yml`. Edit it with your endpoints and keys.

## Config

```yaml
master:
  base_url: https://api.openai.com
  api_key: sk-MASTER-KEY
  model: gpt-4o
  max_tokens: 8192        # cap on synthesis output tokens (set to your model's limit)

fusion_model_1:
  base_url: https://api.openai.com
  api_key: sk-FUSION-1-KEY
  model: gpt-4o-mini

fusion_model_2:
  base_url: https://api.anthropic.com
  api_key: sk-FUSION-2-KEY
  model: claude-3-5-sonnet

fusion_model_3:
  base_url: https://api.groq.com/openai
  api_key: sk-FUSION-3-KEY
  model: llama-3-70b

effort: mid               # low | mid | high
log_dir: ~/.local/share/fusionchat/sessions
log_prompts: true         # false → keep prompts/responses out of logs (metadata only)
# web_password: changeme  # require HTTP Basic auth for the --web interface
```

Each model block accepts its own settings:

| Field | Default | Meaning |
| --- | --- | --- |
| `base_url` | — | OpenAI-compatible API base (required) |
| `api_key` | — | API key (required, never logged) |
| `model` | — | Model name (required) |
| `temperature` | `1.0` | Sampling temperature |
| `max_tokens` | provider | Output-token cap. Recommended — see [Token budget](#token-budget) |
| `max_context_tokens` | auto | Context window; skips `/v1/models` discovery |
| `timeout` | `120` | Per-request timeout in seconds |
| `retries` | `2` | Retries on transient network / 429 / 5xx errors |

## Usage

```bash
fusionchat                        # TUI mode
fusionchat --web                  # web chat on http://127.0.0.1:8000
fusionchat --web -H 0.0.0.0 -p 3000
fusionchat -c /path/to/config.yml --effort high
fusionchat --no-log-prompts       # log metadata only, not prompt/response text
```

In the TUI, press **Ctrl+N** for a new chat, **F1** for config info, **Ctrl+C** to quit.

The web UI has a **conversation sidebar** — create, switch between, and delete multiple
chats, each auto-titled from its first message and **persisted to disk** so they survive
restarts. Every answer shows a collapsible **Fusion panel** (each model's output
expandable, with reasoning when the provider returns it) above the synthesized answer.
A `/health` endpoint reports status without consuming tokens.

## Token budget

`effort_ratio` is 0.35 / 0.5 / 0.65 for low / mid / high, and `master_context` is the
master model's window (auto-discovered or from `max_context_tokens`).

Each fusion model is budgeted

```
floor(master_context * effort_ratio / n_fusion_models)
```

output tokens, so the panel's **combined** output — which the master reads back in to
synthesize — is at most `master_context * effort_ratio`. The context the panel did not
use, `master_context * (1 - effort_ratio)`, is reserved for the conversation history
and the synthesis output, split evenly, so the synthesis is budgeted

```
floor(master_context * (1 - effort_ratio) / 2)
```

This guarantees the master's synthesis call — history + every panel response + its own
output — stays inside its context window (`(1 + effort_ratio) / 2 ≤ 1`).

Because most providers cap **output** tokens far below the context window
(e.g. 8k–16k), every request is additionally clamped to the model's configured
`max_tokens` (default `8192`). Set `max_tokens` per model to your provider's real output
limit to avoid `400` errors and get the longest answers.

## Security

- **API keys are never written to disk.** Session logs record model metadata only.
- The `--web` interface binds to `127.0.0.1` by default. **Before exposing it on
  another host** (`-H 0.0.0.0`), set `web_password` to require HTTP Basic auth —
  otherwise anyone who can reach the host can spend your API keys. fusionChat prints a
  warning if you bind to a non-local host without a password.
- The web session store is bounded (LRU + 1-hour TTL); idle sessions are evicted and
  their connections closed.

## Logs

Every session gets a JSONL file under `~/.local/share/fusionchat/sessions/` (or
`log_dir` from config). Each file records session start, redacted config, every user
turn, all fusion responses, the final synthesis, and any errors. Use `--no-log-prompts`
(or `log_prompts: false`) to keep prompt/response text out of the logs while retaining
character counts and timing metadata.

Web conversations are additionally saved as JSON under
`~/.local/share/fusionchat/conversations/` (the parent of `log_dir`) so the chat list is
restored on restart. Conversations are app-global — when the web UI is exposed beyond
localhost, set `web_password`.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest            # run the test suite
ruff check .      # lint
```

CI runs ruff and the test suite on Python 3.10–3.13 (see `.github/workflows/ci.yml`).

## Branding

UI styling follows Empero: near-black background (`#0b0c0f`), dark surfaces
(`#111216`), white text, and purple accent (`#a855f7`).

## License

[MIT](LICENSE) © Empero
