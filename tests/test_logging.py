"""Tests for session logging: secret redaction and prompt controls."""
from __future__ import annotations

import json

from _helpers import make_config
from fusionchat.fusion import FusionResult
from fusionchat.logging import SessionLogger


def read_records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def sample_result():
    return FusionResult(
        responses=[("gpt-4o-mini", "panel one"), ("claude", "panel two")],
        synthesis="the final synthesized answer",
        master_context_used=128_000,
        per_fusion_max_tokens=8000,
        used_fallback=False,
    )


def test_api_key_never_written(tmp_path):
    config = make_config(tmp_path)
    logger = SessionLogger(config.log_dir)
    logger.log_config(config)
    text = logger.session_file.read_text(encoding="utf-8")
    assert "sk-SECRET-do-not-log" not in text
    assert "api_key" not in text
    # but non-secret model metadata is present
    assert "master" in text
    assert config.master.model in text


def test_log_turn_with_prompts(tmp_path):
    config = make_config(tmp_path)
    logger = SessionLogger(config.log_dir, log_prompts=True)
    logger.log_turn(1, "what is the user asking", sample_result())
    turn = [r for r in read_records(logger.session_file) if r["event"] == "turn"][0]
    assert turn["user"] == "what is the user asking"
    assert turn["synthesis"] == "the final synthesized answer"
    assert turn["panel"][0]["response"] == "panel one"
    assert turn["used_fallback"] is False


def test_log_turn_redacted(tmp_path):
    config = make_config(tmp_path)
    logger = SessionLogger(config.log_dir, log_prompts=False)
    logger.log_turn(1, "secret user prompt", sample_result())
    text = logger.session_file.read_text(encoding="utf-8")
    assert "secret user prompt" not in text
    assert "the final synthesized answer" not in text
    turn = [r for r in read_records(logger.session_file) if r["event"] == "turn"][0]
    assert turn["user"] == "[redacted: log_prompts is disabled]"
    assert turn["synthesis"] == "[redacted: log_prompts is disabled]"
    # metadata is retained
    assert turn["user_chars"] == len("secret user prompt")
    assert turn["synthesis_chars"] == len("the final synthesized answer")
    assert turn["panel"][0]["response_chars"] == len("panel one")


def test_session_start_and_error_records(tmp_path):
    config = make_config(tmp_path)
    logger = SessionLogger(config.log_dir)
    logger.log_error(2, "something broke")
    records = read_records(logger.session_file)
    events = [r["event"] for r in records]
    assert events[0] == "session_start"
    assert "error" in events
    assert records[-1]["error"] == "something broke"
