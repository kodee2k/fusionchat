"""Tests for config loading and validation."""
from __future__ import annotations

import pytest

from fusionchat.config import (
    DEFAULT_LOG_DIR,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    Config,
    ModelConfig,
    config_template,
    load_config,
)

VALID = """
master:
  base_url: https://api.openai.com/
  api_key: sk-master
  model: gpt-4o
fusion_model_1:
  base_url: https://api.openai.com
  api_key: sk-f1
  model: gpt-4o-mini
fusion_model_2:
  base_url: https://api.anthropic.com
  api_key: sk-f2
  model: claude-3-5-sonnet
effort: high
"""


def write(tmp_path, text):
    p = tmp_path / "cfg.yml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_valid(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    assert cfg.master.model == "gpt-4o"
    assert cfg.master.base_url == "https://api.openai.com"  # trailing slash stripped
    assert [m.model for m in cfg.fusion] == ["gpt-4o-mini", "claude-3-5-sonnet"]
    assert cfg.effort == "high"
    assert cfg.log_dir == DEFAULT_LOG_DIR
    assert cfg.log_prompts is True
    assert cfg.web_password is None


def test_mastermodel_alias(tmp_path):
    text = VALID.replace("master:", "mastermodel:", 1)
    cfg = load_config(write(tmp_path, text))
    assert cfg.master.model == "gpt-4o"


def test_missing_master(tmp_path):
    text = "fusion_model_1:\n  base_url: x\n  api_key: y\n  model: z\n"
    with pytest.raises(ValueError, match="master"):
        load_config(write(tmp_path, text))


def test_missing_model_field(tmp_path):
    text = "master:\n  base_url: x\n  api_key: y\nfusion_model_1:\n  base_url: x\n  api_key: y\n  model: z\n"
    with pytest.raises(ValueError, match="missing required field"):
        load_config(write(tmp_path, text))


def test_effort_validation(tmp_path):
    with pytest.raises(ValueError, match="effort"):
        load_config(write(tmp_path, VALID.replace("effort: high", "effort: extreme")))


def test_fourth_fusion_rejected(tmp_path):
    text = VALID + "fusion_model_3:\n  base_url: a\n  api_key: b\n  model: c\nfusion_model_4:\n  base_url: a\n  api_key: b\n  model: d\n"
    with pytest.raises(ValueError, match="At most 3 fusion models"):
        load_config(write(tmp_path, text))


def test_no_fusion_rejected(tmp_path):
    text = "master:\n  base_url: x\n  api_key: y\n  model: z\n"
    with pytest.raises(ValueError, match="fusion"):
        load_config(write(tmp_path, text))


def test_log_dir_expanduser(tmp_path):
    text = VALID + "log_dir: ~/somewhere/logs\n"
    cfg = load_config(write(tmp_path, text))
    assert "~" not in str(cfg.log_dir)
    assert str(cfg.log_dir).endswith("somewhere/logs")


def test_web_password_and_log_prompts(tmp_path):
    text = VALID + "web_password: hunter2\nlog_prompts: false\n"
    cfg = load_config(write(tmp_path, text))
    assert cfg.web_password == "hunter2"
    assert cfg.log_prompts is False


def test_per_model_timeout_retries(tmp_path):
    text = VALID.replace(
        "  model: gpt-4o\n",
        "  model: gpt-4o\n  timeout: 30\n  retries: 5\n  max_tokens: 4096\n",
    )
    cfg = load_config(write(tmp_path, text))
    assert cfg.master.timeout == 30.0
    assert cfg.master.retries == 5
    assert cfg.master.max_tokens == 4096


def test_modelconfig_defaults():
    m = ModelConfig(base_url="x", api_key="y", model="z")
    assert m.timeout == DEFAULT_TIMEOUT
    assert m.retries == DEFAULT_RETRIES
    assert m.temperature == 1.0


def test_modelconfig_rejects_missing():
    with pytest.raises(ValueError):
        ModelConfig(base_url="", api_key="y", model="z")


def test_modelconfig_rejects_bad_numbers():
    with pytest.raises(ValueError, match="max_context_tokens"):
        ModelConfig(base_url="x", api_key="y", model="z", max_context_tokens=0)
    with pytest.raises(ValueError, match="timeout"):
        ModelConfig(base_url="x", api_key="y", model="z", timeout=0)
    with pytest.raises(ValueError, match="retries"):
        ModelConfig(base_url="x", api_key="y", model="z", retries=-1)


def test_config_rejects_too_many_fusion():
    m = ModelConfig(base_url="x", api_key="y", model="z")
    with pytest.raises(ValueError, match="At most 3"):
        Config(master=m, fusion=[m, m, m, m])


def test_template_is_loadable(tmp_path):
    cfg = load_config(write(tmp_path, config_template()))
    assert cfg.master.model == "gpt-4o"
    assert len(cfg.fusion) == 3
    assert cfg.master.max_tokens == 8192
