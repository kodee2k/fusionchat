"""Persistent logging for sessions and generations.

API keys are never written to disk (see ``_model_dict``). When ``log_prompts`` is
False, user prompts, panel responses, and the synthesis text are replaced by their
character counts so logs retain operational metadata without sensitive content.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fusionchat.config import Config, ModelConfig
from fusionchat.fusion import FusionResult

_REDACTED = "[redacted: log_prompts is disabled]"


class SessionLogger:
    def __init__(self, log_dir: Path, log_prompts: bool = True) -> None:
        self.log_dir = Path(log_dir).expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_prompts = log_prompts
        self.session_id = uuid.uuid4().hex[:12]
        self.session_file = self.log_dir / f"session_{self.session_id}.jsonl"
        self._start = datetime.now(timezone.utc).isoformat()
        self._write({
            "event": "session_start",
            "session_id": self.session_id,
            "timestamp": self._start,
        })

    def _write(self, record: dict[str, Any]) -> None:
        with open(self.session_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_config(self, config: Config) -> None:
        self._write({
            "event": "config",
            "session_id": self.session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "master": _model_dict(config.master),
            "fusion": [_model_dict(m) for m in config.fusion],
            "effort": config.effort,
            "log_prompts": config.log_prompts,
        })

    def log_turn(self, turn: int, user_message: str, result: FusionResult) -> None:
        if self.log_prompts:
            panel = [
                {"model": p.model, "response": p.content, "reasoning": p.reasoning, "ok": p.ok}
                for p in result.responses
            ]
            user = user_message
            synthesis = result.synthesis
            master_reasoning = result.master_reasoning
        else:
            panel = [
                {"model": p.model, "response_chars": len(p.content), "ok": p.ok}
                for p in result.responses
            ]
            user = _REDACTED
            synthesis = _REDACTED
            master_reasoning = None
        self._write({
            "event": "turn",
            "session_id": self.session_id,
            "turn": turn,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user": user,
            "user_chars": len(user_message),
            "master_context_used": result.master_context_used,
            "per_fusion_max_tokens": result.per_fusion_max_tokens,
            "used_fallback": result.used_fallback,
            "panel": panel,
            "synthesis": synthesis,
            "synthesis_chars": len(result.synthesis),
            "master_reasoning": master_reasoning,
        })

    def log_error(self, turn: int, error: str) -> None:
        self._write({
            "event": "error",
            "session_id": self.session_id,
            "turn": turn,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": error,
        })


def _model_dict(m: ModelConfig) -> dict[str, Any]:
    """Serialize a model config WITHOUT its api_key. Never log secrets."""
    return {
        "base_url": m.base_url,
        "model": m.model,
        "max_context_tokens": m.max_context_tokens,
        "max_tokens": m.max_tokens,
        "temperature": m.temperature,
        "timeout": m.timeout,
        "retries": m.retries,
    }
