"""Fusion orchestration: master delegates to fusion models and synthesizes."""
from __future__ import annotations

import asyncio
import textwrap
from dataclasses import dataclass

from fusionchat.config import Config, ModelConfig
from fusionchat.models import APIError, ChatMessage, ModelClient

_EFFORT_RATIOS = {"low": 0.35, "mid": 0.5, "high": 0.65}

# Most chat models cap *output* tokens well below their context window
# (e.g. claude-3.5-sonnet 8k, gpt-4o 16k). The effort formula budgets against the
# context window, so without a cap the synthesis request can exceed the provider's
# output limit and 400. We clamp every output request to the model's configured
# max_tokens, falling back to this conservative default.
DEFAULT_MAX_OUTPUT_TOKENS = 8192


def _output_cap(cfg: ModelConfig) -> int:
    return cfg.max_tokens or DEFAULT_MAX_OUTPUT_TOKENS


def _format_messages(messages: list[ChatMessage]) -> str:
    out = []
    for m in messages:
        role = m.role.capitalize()
        out.append(f"### {role}\n{m.content}\n")
    return "\n".join(out)


def fusion_prompt(task_messages: list[ChatMessage]) -> str:
    history = _format_messages(task_messages)
    return textwrap.dedent(
        f"""\
        You are an independent expert contributor on a fusion panel.
        Analyze the conversation below and produce a concise, high-quality response.
        Do not mention that you are part of a panel. Respond in your own voice.

        {history}
        """
    )


def synthesis_prompt(task_messages: list[ChatMessage], responses: list[tuple[str, str]]) -> str:
    history = _format_messages(task_messages)
    panel = []
    for idx, (model_id, response) in enumerate(responses, 1):
        panel.append(f"--- Panel response {idx} ({model_id}) ---\n{response}\n")
    panel_text = "\n".join(panel)
    return textwrap.dedent(
        f"""\
        You are the synthesis judge for fusionChat.
        Calling the fusion panel is the required first step of every request — never answer before it returns.
        It returns a panel of independent model responses. Use them as reference material and guidance:
        draw on their evidence, weigh their claims critically with your own judgement, and write the
        response that best serves what the request is asking for. Answer in your own voice as if it were
        entirely your own, in clear Markdown; do not name the panel models or describe how the answer was produced.

        Conversation:
        {history}

        Panel responses:
        {panel_text}
        """
    )


def direct_prompt(task_messages: list[ChatMessage]) -> str:
    history = _format_messages(task_messages)
    return textwrap.dedent(
        f"""\
        You are fusionChat's master model. The fusion panel was unavailable for this request,
        so answer the user directly using your own knowledge. Respond in clear Markdown.

        Conversation:
        {history}
        """
    )


@dataclass
class PanelResponse:
    model: str
    content: str
    reasoning: str | None = None
    ok: bool = True


@dataclass
class FusionResult:
    responses: list[PanelResponse]
    synthesis: str
    master_context_used: int
    per_fusion_max_tokens: int
    used_fallback: bool = False
    master_reasoning: str | None = None


@dataclass
class FusionPrep:
    """Everything needed to run the master synthesis after the panel returns."""
    panel: list[PanelResponse]
    prompt_text: str
    synth_max: int
    master_context: int
    per_fusion_budget: int
    used_fallback: bool


class FusionOrchestrator:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.master_client = ModelClient(config.master)
        self.fusion_clients = [ModelClient(m) for m in config.fusion]

    async def _fusion_budget(self) -> tuple[int, int]:
        """Return (master_context_window, per_fusion_token_budget).

        Each fusion model may emit up to ``master_ctx * ratio / n`` tokens, so the
        panel's combined output — which the master must read back in to synthesize —
        is at most ``master_ctx * ratio``.
        """
        master_ctx = await self.master_client.context_window()
        ratio = _EFFORT_RATIOS[self.config.effort]
        per_model = max(1, int(master_ctx * ratio) // len(self.fusion_clients))
        return master_ctx, per_model

    async def _run_fusion_model(
        self, client: ModelClient, prompt: str, budget: int
    ) -> PanelResponse:
        messages = [ChatMessage(role="user", content=prompt)]
        max_tokens = max(1, min(budget, _output_cap(client.cfg)))
        try:
            resp = await client.chat_full(messages, max_tokens=max_tokens, temperature=client.cfg.temperature)
            return PanelResponse(model=client.cfg.model, content=resp.content, reasoning=resp.reasoning, ok=True)
        except APIError as exc:
            return PanelResponse(model=client.cfg.model, content=f"[Error from {client.cfg.model}: {exc}]", ok=False)

    async def prepare(self, messages: list[ChatMessage]) -> FusionPrep:
        """Run the fusion panel and build the master's synthesis prompt + budget."""
        master_ctx, per_fusion_budget = await self._fusion_budget()
        fusion_prompt_text = fusion_prompt(messages)

        # Run all fusion models concurrently.
        tasks = [
            asyncio.create_task(self._run_fusion_model(client, fusion_prompt_text, per_fusion_budget))
            for client in self.fusion_clients
        ]
        raw = await asyncio.gather(*tasks, return_exceptions=True)

        panel: list[PanelResponse] = []
        any_ok = False
        for item in raw:
            if isinstance(item, BaseException):
                panel.append(PanelResponse(model="unknown", content=f"[Unhandled error: {item}]", ok=False))
            else:
                panel.append(item)
                any_ok = any_ok or item.ok

        ratio = _EFFORT_RATIOS[self.config.effort]
        # The panel consumed up to master_ctx * ratio of the window; reserve what it
        # did not (master_ctx * (1 - ratio)) for the conversation history and the
        # synthesis output, split evenly. This keeps the master's synthesis call
        # (history + all panel responses + its own output) inside its context window.
        synth_budget = max(int(master_ctx * (1 - ratio) / 2), 1)
        synth_max = max(1, min(synth_budget, _output_cap(self.config.master)))

        if any_ok:
            prompt_text = synthesis_prompt(messages, [(p.model, p.content) for p in panel])
            used_fallback = False
        else:
            # Every fusion model failed — answer directly rather than synthesizing errors.
            prompt_text = direct_prompt(messages)
            used_fallback = True

        return FusionPrep(
            panel=panel,
            prompt_text=prompt_text,
            synth_max=synth_max,
            master_context=master_ctx,
            per_fusion_budget=per_fusion_budget,
            used_fallback=used_fallback,
        )

    async def run(self, messages: list[ChatMessage]) -> FusionResult:
        prep = await self.prepare(messages)
        synthesis = await self.master_client.chat_full(
            [ChatMessage(role="user", content=prep.prompt_text)],
            max_tokens=prep.synth_max,
            temperature=self.config.master.temperature,
        )
        return FusionResult(
            responses=prep.panel,
            synthesis=synthesis.content,
            master_context_used=prep.master_context,
            per_fusion_max_tokens=prep.per_fusion_budget,
            used_fallback=prep.used_fallback,
            master_reasoning=synthesis.reasoning,
        )

    async def close(self) -> None:
        await self.master_client.close()
        for c in self.fusion_clients:
            await c.close()
