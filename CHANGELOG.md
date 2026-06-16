# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
