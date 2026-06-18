# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-06-18

### Added
- `--api` mode: an OpenAI-compatible server exposing the whole fusion pipeline as a
  single model (`fusion`) for use in harnesses and SDKs. Endpoints: `POST
  /v1/chat/completions` (streaming via `"stream": true`), `GET /v1/models`, `GET
  /health`. Optional bearer-token auth via `web_password`; per-request sampling params
  are ignored in favor of the fusion token budget.

### Changed
- Orchestrator refactored to share a `prepare()` step (panel + budget) between the
  non-streaming `run()` and the streaming API path; `run()` behavior is unchanged.

## [0.2.0] - 2026-06-18

### Added
- Web UI conversation overview: a sidebar to create, switch between, and delete multiple
  chats, each auto-titled from its first message.
- Conversations persist to disk (`<data>/conversations/*.json`) and are restored on restart.
- Collapsible per-fusion-model output bubbles in the web UI, with nested reasoning and a
  master-reasoning bubble when a provider returns reasoning (`reasoning_content` / `reasoning`).
- Ordered-list (`1.`) rendering in the web markdown.

### Changed
- Web UI rewritten around an app-global conversation store that shares one stateless
  orchestrator (lighter; removes per-page-load client churn).
- Tightened web markdown spacing (blank lines no longer emit literal `<br>`) and centered
  the conversation column for readability.

## [0.1.0] - 2026-06-16

First public release.

### Added
- Master + up to three fusion models with concurrent panel querying and master synthesis.
- Textual TUI (`fusionchat`) and FastAPI web UI (`fusionchat --web`).
- YAML configuration with per-model `base_url`, `api_key`, `model`, `temperature`,
  `max_context_tokens`, `max_tokens`, and `timeout`.
- Per-session JSONL logging (API keys are never written to disk).
- Effort-based token budgeting (`low` / `mid` / `high`).
- Automatic retry with exponential backoff on transient network and 429/5xx errors.
- Master fallback: if every fusion model fails, the master answers directly instead of
  synthesizing from error strings.
- Web UI: cookie-based session reuse, bounded session store with LRU eviction,
  optional HTTP Basic auth (`web_password`), and a `/health` endpoint.
- `--no-log-prompts` flag to keep prompts and responses out of session logs.
- MIT license, test suite, and GitHub Actions CI on Python 3.10–3.13.
