"""Configuration loading and validation for fusionChat."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

DEFAULT_LOG_DIR = Path.home() / ".local" / "share" / "fusionchat" / "sessions"
DEFAULT_TIMEOUT = 120.0
DEFAULT_RETRIES = 2
MAX_FUSION_MODELS = 3


def _config_paths() -> list[Path]:
    candidates = []
    if "FUSIONCHAT_CONFIG" in os.environ:
        candidates.append(Path(os.environ["FUSIONCHAT_CONFIG"]).expanduser())
    home = Path.home()
    candidates.extend(
        [
            home / ".config" / "fusionchat" / "fusionchat.yml",
            home / ".config" / "fusionchat" / "config.yml",
            home / ".fusionchat.yml",
        ]
    )
    return candidates


@dataclass(frozen=True)
class ModelConfig:
    base_url: str
    api_key: str
    model: str
    max_context_tokens: int | None = None
    max_tokens: int | None = None
    temperature: float = 1.0
    timeout: float = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES

    def __post_init__(self) -> None:
        if not self.base_url or not self.api_key or not self.model:
            raise ValueError("Every model must have base_url, api_key and model set.")
        if self.max_context_tokens is not None and self.max_context_tokens <= 0:
            raise ValueError("max_context_tokens must be a positive integer.")
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer.")
        if self.timeout <= 0:
            raise ValueError("timeout must be a positive number of seconds.")
        if self.retries < 0:
            raise ValueError("retries must be zero or greater.")


@dataclass(frozen=True)
class Config:
    master: ModelConfig
    fusion: list[ModelConfig]
    effort: Literal["low", "mid", "high"] = "mid"
    log_dir: Path = field(default_factory=lambda: DEFAULT_LOG_DIR)
    log_prompts: bool = True
    web_password: str | None = None

    def __post_init__(self) -> None:
        if len(self.fusion) < 1:
            raise ValueError("At least one fusion model is required.")
        if len(self.fusion) > MAX_FUSION_MODELS:
            raise ValueError(f"At most {MAX_FUSION_MODELS} fusion models are supported.")


def _load_model(data: object, key: str) -> ModelConfig:
    if data is None:
        raise ValueError(f"The '{key}' section is required in the config file.")
    if not isinstance(data, dict):
        raise ValueError(f"{key} must be a mapping of model settings.")
    missing = [f for f in ("base_url", "api_key", "model") if not data.get(f)]
    if missing:
        raise ValueError(f"{key} is missing required field(s): {', '.join(missing)}.")
    return ModelConfig(
        base_url=str(data["base_url"]).rstrip("/"),
        api_key=str(data["api_key"]),
        model=str(data["model"]),
        max_context_tokens=data.get("max_context_tokens"),
        max_tokens=data.get("max_tokens"),
        temperature=float(data.get("temperature", 1.0)),
        timeout=float(data.get("timeout", DEFAULT_TIMEOUT)),
        retries=int(data.get("retries", DEFAULT_RETRIES)),
    )


def load_config(path: Path | None = None) -> Config:
    candidates = [path] if path else _config_paths()
    file: Path | None = None
    for candidate in candidates:
        if candidate and candidate.exists():
            file = candidate
            break
    if file is None:
        searched = "\n  ".join(str(p) for p in candidates)
        raise FileNotFoundError(f"No fusionChat config found. Searched:\n  {searched}")

    with open(file, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError("Config file must be a YAML mapping.")

    master = _load_model(raw.get("master") or raw.get("mastermodel"), "master")

    if raw.get("fusion_model_4"):
        raise ValueError(f"At most {MAX_FUSION_MODELS} fusion models are supported (found fusion_model_4).")
    fusion: list[ModelConfig] = []
    for i in range(1, MAX_FUSION_MODELS + 1):
        fkey = f"fusion_model_{i}"
        if raw.get(fkey):
            fusion.append(_load_model(raw[fkey], fkey))
    if not fusion:
        raise ValueError("At least one fusion model (fusion_model_1) is required.")

    effort = raw.get("effort", "mid")
    if effort not in ("low", "mid", "high"):
        raise ValueError("effort must be one of low, mid, high.")

    log_dir = raw.get("log_dir")
    log_path = Path(log_dir).expanduser() if log_dir else DEFAULT_LOG_DIR

    log_prompts = bool(raw.get("log_prompts", True))
    web_password = raw.get("web_password")
    if web_password is not None:
        web_password = str(web_password)

    return Config(
        master=master,
        fusion=fusion,
        effort=effort,
        log_dir=log_path,
        log_prompts=log_prompts,
        web_password=web_password,
    )


def config_template() -> str:
    return """master:
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

# Optional global settings
effort: mid               # low | mid | high
log_dir: ~/.local/share/fusionchat/sessions
log_prompts: true         # set false to keep prompts/responses out of session logs
# web_password: changeme  # require HTTP Basic auth for the --web interface

# Optional per-model settings (any model block):
#   max_context_tokens: 128000   # skip /v1/models discovery
#   max_tokens: 8192             # cap output tokens (avoids provider 400s)
#   temperature: 1.0
#   timeout: 120                 # request timeout in seconds
#   retries: 2                   # retries on transient/network/5xx errors
""".lstrip()
