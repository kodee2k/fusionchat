"""Tests for the FusionOrchestrator (no network — FakeClient stand-ins)."""
from __future__ import annotations

import asyncio

from _helpers import FakeClient, make_config, model_cfg
from fusionchat.fusion import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    ChatMessage,
    FusionOrchestrator,
    direct_prompt,
    fusion_prompt,
    synthesis_prompt,
)


def build_orchestrator(config, master_client, fusion_clients):
    orch = FusionOrchestrator.__new__(FusionOrchestrator)
    orch.config = config
    orch.master_client = master_client
    orch.fusion_clients = fusion_clients
    return orch


def msgs(text="hello"):
    return [ChatMessage(role="user", content=text)]


def test_run_synthesizes_when_panel_succeeds(tmp_path):
    config = make_config(tmp_path, effort="mid")
    master = FakeClient(config.master, reply="FINAL", ctx=128_000)
    fusion = [FakeClient(c, reply=f"resp-{c.model}") for c in config.fusion]
    orch = build_orchestrator(config, master, fusion)

    result = asyncio.run(orch.run(msgs()))

    assert result.synthesis == "FINAL"
    assert result.used_fallback is False
    assert result.master_context_used == 128_000
    assert [p.content for p in result.responses] == ["resp-f1", "resp-f2"]
    assert all(p.ok for p in result.responses)
    # master received a synthesis prompt
    assert "synthesis judge" in master.calls[0]["messages"][0].content
    # per-fusion budget = ctx * 0.5 / 2 fusion models = 32000
    assert result.per_fusion_max_tokens == 32_000


def test_fusion_output_clamped_to_model_max_tokens(tmp_path):
    fusion = [model_cfg(model="f1", max_tokens=100)]
    config = make_config(tmp_path, fusion=fusion)
    master = FakeClient(config.master, ctx=128_000)
    fclients = [FakeClient(config.fusion[0])]
    orch = build_orchestrator(config, master, fclients)

    asyncio.run(orch.run(msgs()))
    # budget would be 32000 but model max_tokens caps it at 100
    assert fclients[0].calls[0]["max_tokens"] == 100


def test_synthesis_clamped_to_default_cap(tmp_path):
    config = make_config(tmp_path, fusion=[model_cfg(model="f1")], effort="mid")
    master = FakeClient(config.master, ctx=128_000)
    orch = build_orchestrator(config, master, [FakeClient(config.fusion[0])])

    asyncio.run(orch.run(msgs()))
    # synth budget = 128000*(1-0.5)/2 = 32000, clamped to default output cap
    assert master.calls[0]["max_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS


def test_synthesis_respects_master_max_tokens(tmp_path):
    master_cfg = model_cfg(model="master", max_tokens=200)
    config = make_config(tmp_path, master=master_cfg, fusion=[model_cfg(model="f1")])
    master = FakeClient(master_cfg, ctx=128_000)
    orch = build_orchestrator(config, master, [FakeClient(config.fusion[0])])

    asyncio.run(orch.run(msgs()))
    assert master.calls[0]["max_tokens"] == 200


def test_master_fallback_when_all_fusion_fail(tmp_path):
    config = make_config(tmp_path)
    master = FakeClient(config.master, reply="DIRECT", ctx=128_000)
    fusion = [FakeClient(c, fail=True) for c in config.fusion]
    orch = build_orchestrator(config, master, fusion)

    result = asyncio.run(orch.run(msgs()))

    assert result.used_fallback is True
    assert result.synthesis == "DIRECT"
    # master got a direct prompt, not a synthesis prompt
    assert "fusion panel was unavailable" in master.calls[0]["messages"][0].content
    # error strings are still recorded in the panel, marked not-ok
    assert all(p.content.startswith("[Error from") for p in result.responses)
    assert not any(p.ok for p in result.responses)


def test_partial_failure_still_synthesizes(tmp_path):
    config = make_config(tmp_path)
    master = FakeClient(config.master, reply="FINAL", ctx=128_000)
    fusion = [FakeClient(config.fusion[0], fail=True), FakeClient(config.fusion[1], reply="good")]
    orch = build_orchestrator(config, master, fusion)

    result = asyncio.run(orch.run(msgs()))
    assert result.used_fallback is False
    assert "synthesis judge" in master.calls[0]["messages"][0].content


def test_effort_ratios_change_budget(tmp_path):
    for effort, ratio in (("low", 0.35), ("mid", 0.5), ("high", 0.65)):
        config = make_config(tmp_path, fusion=[model_cfg(model="f1")], effort=effort)
        master = FakeClient(config.master, ctx=100_000)
        orch = build_orchestrator(config, master, [FakeClient(config.fusion[0])])
        result = asyncio.run(orch.run(msgs()))
        # per-fusion budget = ctx * ratio / n_fusion (n=1 here)
        assert result.per_fusion_max_tokens == int(100_000 * ratio)


def test_master_budget_cannot_overflow(tmp_path):
    # With the per-model output clamp effectively disabled (huge max_tokens), the
    # combined panel output plus the synthesis output must still fit the master window.
    ctx = 128_000
    for effort in ("low", "mid", "high"):
        master_cfg = model_cfg(model="master", max_tokens=10**9)
        fusion = [model_cfg(model=f"f{i}", max_tokens=10**9) for i in range(3)]
        config = make_config(tmp_path, master=master_cfg, fusion=fusion, effort=effort)
        mclient = FakeClient(master_cfg, ctx=ctx)
        fclients = [FakeClient(c) for c in config.fusion]
        orch = build_orchestrator(config, mclient, fclients)
        asyncio.run(orch.run(msgs()))
        combined_panel = sum(fc.calls[0]["max_tokens"] for fc in fclients)
        synth_out = mclient.calls[0]["max_tokens"]
        assert combined_panel + synth_out <= ctx


def test_reasoning_is_captured(tmp_path):
    config = make_config(tmp_path, fusion=[model_cfg(model="f1")])
    master = FakeClient(config.master, reply="FINAL", ctx=128_000, reasoning="master thinks")
    fusion = [FakeClient(config.fusion[0], reply="f-out", reasoning="fusion thinks")]
    orch = build_orchestrator(config, master, fusion)
    result = asyncio.run(orch.run(msgs()))
    assert result.master_reasoning == "master thinks"
    assert result.responses[0].reasoning == "fusion thinks"


def test_prompt_builders_contain_history():
    m = [ChatMessage(role="user", content="WHATABOUTBOB")]
    assert "WHATABOUTBOB" in fusion_prompt(m)
    assert "WHATABOUTBOB" in direct_prompt(m)
    assert "PANELTEXT" in synthesis_prompt(m, [("model-x", "PANELTEXT")])
    assert "model-x" in synthesis_prompt(m, [("model-x", "PANELTEXT")])
