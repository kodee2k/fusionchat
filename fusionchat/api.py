"""OpenAI-compatible API server exposing the fusion pipeline as a single 'model'.

Point any OpenAI-compatible client/harness at this server:

    base_url = http://127.0.0.1:8000/v1
    model    = "fusion"
    api_key  = <web_password from config, or anything if unset>

Each /v1/chat/completions call runs the full fusion pipeline (master consults the
panel, then synthesizes) and returns the synthesis as the assistant message.
Streaming (``stream: true``) streams the master's synthesis tokens once the panel
returns. Per-request sampling params (max_tokens, temperature, …) are ignored — the
fusion token budget is governed by config + effort.
"""
from __future__ import annotations

import json
import secrets
import time
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from fusionchat.config import Config
from fusionchat.fusion import ChatMessage, FusionOrchestrator, FusionResult
from fusionchat.logging import SessionLogger
from fusionchat.models import APIError

DEFAULT_MODEL_ID = "fusion"


def _now() -> int:
    return int(time.time())


def _completion_id() -> str:
    return "chatcmpl-" + uuid.uuid4().hex


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _extract_text(content: Any) -> str:
    """OpenAI message content may be a string or a list of typed parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return "" if content is None else str(content)


def _to_messages(raw_messages: list[dict]) -> list[ChatMessage]:
    return [
        ChatMessage(role=str(m.get("role", "user")), content=_extract_text(m.get("content")))
        for m in raw_messages
    ]


def _error_response(message: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"message": message, "type": "fusion_error", "code": None}},
        status_code=status,
    )


def create_api_app(config: Config, model_id: str = DEFAULT_MODEL_ID) -> FastAPI:
    app = FastAPI(title="fusionChat API")
    app.state.orchestrator = FusionOrchestrator(config)
    app.state.logger = SessionLogger(config.log_dir, log_prompts=config.log_prompts)
    app.state.logger.log_config(config)
    app.state.turn = 0

    def check_auth(authorization: str | None) -> None:
        if not config.web_password:
            return
        token = ""
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        if not secrets.compare_digest(token, config.web_password):
            raise HTTPException(status_code=401, detail="Invalid API key")

    @app.get("/health")
    async def health():
        return {"status": "ok", "fusion_models": len(config.fusion), "effort": config.effort}

    @app.get("/v1/models")
    async def list_models(authorization: str | None = Header(default=None)):
        check_auth(authorization)
        return {
            "object": "list",
            "data": [
                {"id": model_id, "object": "model", "created": _now(), "owned_by": "fusionchat"}
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request, authorization: str | None = Header(default=None)):
        check_auth(authorization)
        try:
            payload = await request.json()
        except Exception:
            return _error_response("Invalid JSON body", 400)
        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            return _error_response("'messages' must be a non-empty array", 400)

        messages = _to_messages(raw_messages)
        requested_model = str(payload.get("model") or model_id)
        stream = bool(payload.get("stream", False))
        user_text = next((m.content for m in reversed(messages) if m.role == "user"), "")
        orch = app.state.orchestrator
        logger = app.state.logger

        if stream:
            return StreamingResponse(
                _stream_completion(orch, config, logger, app, messages, user_text, requested_model),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        try:
            result = await orch.run(messages)
        except APIError as exc:
            return _error_response(str(exc), 502)
        except Exception as exc:  # noqa: BLE001 - surface orchestration errors to the client
            return _error_response(str(exc), 500)

        app.state.turn += 1
        try:
            logger.log_turn(app.state.turn, user_text, result)
        except Exception:  # noqa: BLE001 - logging must never break a response
            pass

        prompt_tokens = sum(_estimate_tokens(m.content) for m in messages)
        completion_tokens = _estimate_tokens(result.synthesis)
        return {
            "id": _completion_id(),
            "object": "chat.completion",
            "created": _now(),
            "model": requested_model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": result.synthesis},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

    return app


async def _stream_completion(orch, config, logger, app, messages, user_text, model_id):
    cid = _completion_id()
    created = _now()

    def sse(delta: dict, finish: str | None = None) -> str:
        data = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_id,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    try:
        prep = await orch.prepare(messages)
    except Exception as exc:  # noqa: BLE001 - emit the error to the client and stop cleanly
        yield sse({"role": "assistant", "content": f"[fusion error: {exc}]"})
        yield sse({}, finish="stop")
        yield "data: [DONE]\n\n"
        return

    yield sse({"role": "assistant"})
    acc: list[str] = []
    try:
        async for piece in orch.master_client.stream_chat(
            [ChatMessage(role="user", content=prep.prompt_text)],
            max_tokens=prep.synth_max,
            temperature=config.master.temperature,
        ):
            acc.append(piece)
            yield sse({"content": piece})
    except Exception as exc:  # noqa: BLE001 - surface a mid-stream failure inline
        yield sse({"content": f"\n[fusion error: {exc}]"})
    yield sse({}, finish="stop")
    yield "data: [DONE]\n\n"

    app.state.turn += 1
    result = FusionResult(
        responses=prep.panel,
        synthesis="".join(acc),
        master_context_used=prep.master_context,
        per_fusion_max_tokens=prep.per_fusion_budget,
        used_fallback=prep.used_fallback,
    )
    try:
        logger.log_turn(app.state.turn, user_text, result)
    except Exception:  # noqa: BLE001
        pass


def run_api(config: Config, host: str, port: int) -> None:
    import uvicorn

    app = create_api_app(config)
    uvicorn.run(app, host=host, port=port)
