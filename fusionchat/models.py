"""OpenAI-compatible API client with retries and context-window discovery."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from fusionchat.config import ModelConfig

DEFAULT_CONTEXT_WINDOW = 128_000
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_BACKOFF_BASE_SECONDS = 0.5
_BACKOFF_MAX_SECONDS = 8.0


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


class APIError(Exception):
    pass


class ModelClient:
    def __init__(self, cfg: ModelConfig) -> None:
        self.cfg = cfg
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(cfg.timeout, connect=min(10.0, cfg.timeout)),
            headers={"Authorization": f"Bearer {cfg.api_key}"},
        )

    async def _sleep_backoff(self, attempt: int) -> None:
        delay = min(_BACKOFF_BASE_SECONDS * (2 ** attempt), _BACKOFF_MAX_SECONDS)
        await asyncio.sleep(delay)

    def _payload(self, messages: list[ChatMessage], max_tokens: int | None, temperature: float | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        return payload

    async def chat(
        self,
        messages: list[ChatMessage],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        payload = self._payload(messages, max_tokens, temperature)
        url = f"{self.cfg.base_url}/v1/chat/completions"

        last_error: APIError | None = None
        for attempt in range(self.cfg.retries + 1):
            try:
                resp = await self.client.post(url, json=payload)
            except httpx.RequestError as exc:
                last_error = APIError(f"Request failed for {self.cfg.model}: {exc}")
                if attempt < self.cfg.retries:
                    await self._sleep_backoff(attempt)
                    continue
                raise last_error from exc

            if resp.status_code >= 400:
                body = resp.text
                if resp.status_code in RETRYABLE_STATUS and attempt < self.cfg.retries:
                    last_error = APIError(f"API error ({resp.status_code}) for {self.cfg.model}: {body}")
                    await self._sleep_backoff(attempt)
                    continue
                raise APIError(f"API error ({resp.status_code}) for {self.cfg.model}: {body}")

            data = resp.json()
            try:
                return str(data["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError) as exc:
                raise APIError(f"Unexpected response shape from {self.cfg.model}: {data}") from exc

        # Loop always returns or raises; this satisfies type checkers.
        raise last_error or APIError(f"Request to {self.cfg.model} failed.")

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, max_tokens, temperature)
        payload["stream"] = True
        url = f"{self.cfg.base_url}/v1/chat/completions"
        try:
            async with self.client.stream("POST", url, json=payload) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise APIError(f"API error ({resp.status_code}) for {self.cfg.model}: {body.decode()}")
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        try:
                            chunk = json.loads(line[6:])
                            delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                            if delta:
                                yield delta
                        except (json.JSONDecodeError, IndexError, KeyError, TypeError):
                            continue
        except httpx.RequestError as exc:
            raise APIError(f"Streaming request failed for {self.cfg.model}: {exc}") from exc

    async def context_window(self) -> int:
        if self.cfg.max_context_tokens:
            return self.cfg.max_context_tokens
        url = f"{self.cfg.base_url}/v1/models"
        try:
            resp = await self.client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                for m in models:
                    if m.get("id") == self.cfg.model:
                        # Common keys used by providers.
                        for key in ("max_context_length", "context_window", "max_context_tokens", "max_input_tokens"):
                            val = m.get(key)
                            if isinstance(val, int) and val > 0:
                                return val
                        break
        except httpx.RequestError:
            pass
        return DEFAULT_CONTEXT_WINDOW

    async def close(self) -> None:
        await self.client.aclose()
