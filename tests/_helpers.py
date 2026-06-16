"""Shared test helpers (non-fixture)."""
from __future__ import annotations

import contextlib
from pathlib import Path

import httpx

from fusionchat.config import Config, ModelConfig
from fusionchat.models import APIError, ChatMessage, ModelClient


def model_cfg(**kw) -> ModelConfig:
    base = dict(base_url="https://api.test", api_key="sk-SECRET-do-not-log", model="m")
    base.update(kw)
    return ModelConfig(**base)


def make_config(log_dir: Path, **kw) -> Config:
    master = kw.pop("master", model_cfg(model="master"))
    fusion = kw.pop("fusion", [model_cfg(model="f1"), model_cfg(model="f2")])
    return Config(master=master, fusion=fusion, log_dir=Path(log_dir), **kw)


def chat_response(content: str = "ok") -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@contextlib.asynccontextmanager
async def mock_client(cfg: ModelConfig, handler):
    """Yield a ModelClient whose transport is driven by ``handler``."""
    mc = ModelClient(cfg)
    await mc.client.aclose()  # discard the real client created in __init__
    mc.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": f"Bearer {cfg.api_key}"},
        timeout=cfg.timeout,
    )
    try:
        yield mc
    finally:
        await mc.close()


class FakeClient:
    """Stand-in for ModelClient used in orchestration tests (no network)."""

    def __init__(self, cfg: ModelConfig, reply: str | None = None, fail: bool = False, ctx: int = 128_000) -> None:
        self.cfg = cfg
        self.reply = reply if reply is not None else f"reply-{cfg.model}"
        self.fail = fail
        self.ctx = ctx
        self.calls: list[dict] = []

    async def chat(self, messages: list[ChatMessage], max_tokens=None, temperature=None) -> str:
        self.calls.append({"messages": messages, "max_tokens": max_tokens, "temperature": temperature})
        if self.fail:
            raise APIError(f"boom from {self.cfg.model}")
        return self.reply

    async def context_window(self) -> int:
        return self.ctx

    async def close(self) -> None:
        pass
