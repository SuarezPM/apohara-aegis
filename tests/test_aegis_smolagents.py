# SPDX-License-Identifier: Apache-2.0
"""Tests for the Apohara Aegis × smolagents wrapper.

The whole module is skipped if smolagents isn't installed — Aegis can
still be used as a standalone INV-15 scorer + policy loader. CI runs
without smolagents on smoke machines.

Run::

    pip install smolagents
    PYTHONPATH=. pytest tests/test_aegis_smolagents.py -v
"""
from __future__ import annotations

import pytest

# Skip the whole module if smolagents isn't available. importorskip
# emits a clean message instead of erroring on import.
smolagents = pytest.importorskip(
    "smolagents",
    reason="smolagents is an optional extra; install via `pip install smolagents`",
)

from smolagents import CodeAgent, OpenAIModel  # noqa: E402
from smolagents.models import ChatMessage, MessageRole  # noqa: E402

from apohara_aegis import AegisBlocked, AegisGuard, evaluate  # noqa: E402


# ---------------------------------------------------------------------------
# Stub model — returns a single completed code action so the CodeAgent step
# loop terminates immediately. Lets us trigger callbacks without real LLM.
# ---------------------------------------------------------------------------


class _StubModel:
    """Minimal model that emits ``final_answer("ok")`` once."""

    model_id = "stub-finalanswer"

    def generate(self, messages, stop_sequences=None, **kw):  # noqa: ANN001
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content='Thought: done.\n<code>\nfinal_answer("ok")\n</code>',
        )

    def __call__(self, *a, **kw):  # noqa: ANN001
        return self.generate(*a, **kw)


def _new_agent() -> CodeAgent:
    return CodeAgent(tools=[], model=_StubModel(), max_steps=2)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_aegis_wraps_codeagent(tmp_path):
    """AegisGuard.wrap attaches state without breaking the agent."""
    agent = _new_agent()
    guarded = AegisGuard.wrap(
        agent,
        policy_path="configs/lobstertrap_policy.yaml",
        audit_log=tmp_path / "aegis.jsonl",
    )
    assert guarded is agent  # mutates in place
    # Policy digest exposed
    assert guarded.aegis_policy is not None
    assert guarded.aegis_policy.name == "apohara-contextforge-techex"
    # Callback registry populated for ActionStep
    from smolagents import ActionStep
    cbs = guarded.step_callbacks._callbacks.get(ActionStep, [])
    assert any("_on_action_step" in getattr(c, "__qualname__", "") for c in cbs), \
        f"expected aegis _on_action_step in callbacks; got {cbs!r}"


def test_aegis_blocks_critic_under_high_reuse():
    """Judge role above tau → step is aborted with AegisBlocked."""
    agent = _new_agent()
    guarded = AegisGuard.wrap(agent, judge_role="critic", tau=0.65)
    guarded.aegis_meta = {
        "role": "critic",
        "candidate_count": 5,
        "reuse_rate": 0.9,
        "layout_shuffled": True,
    }
    # smolagents may wrap the inner exception, so walk the chain.
    with pytest.raises(Exception) as ei:
        guarded.run("noop")
    chain = [ei.value]
    cur = ei.value.__cause__ or ei.value.__context__
    while cur is not None:
        chain.append(cur)
        cur = cur.__cause__ or cur.__context__
    assert any(isinstance(x, AegisBlocked) for x in chain), \
        f"AegisBlocked not found in exception chain: {chain!r}"


def test_aegis_allows_low_risk_critic():
    """Judge role at or below tau → step runs normally."""
    agent = _new_agent()
    guarded = AegisGuard.wrap(agent, judge_role="critic", tau=0.65)
    # Bare critic with 2 candidates, no shuffle, low reuse → risk ≈ 0.60
    guarded.aegis_meta = {
        "role": "critic",
        "candidate_count": 2,
        "reuse_rate": 0.1,
        "layout_shuffled": False,
    }
    out = guarded.run("noop")
    assert out == "ok"
    # Sanity-check the scorer directly: 0.60 ≤ 0.65
    a = evaluate("critic", candidate_count=2, reuse_rate=0.1)
    assert not a.blocked
    assert a.risk_score == pytest.approx(0.60, abs=1e-6)


def test_aegis_allows_non_judge_roles():
    """Retriever / reranker / etc are never gated even at max reuse."""
    agent = _new_agent()
    guarded = AegisGuard.wrap(agent, judge_role="critic", tau=0.65)
    guarded.aegis_meta = {
        "role": "retriever",
        "candidate_count": 10,
        "reuse_rate": 1.0,
        "layout_shuffled": True,
    }
    out = guarded.run("noop")
    assert out == "ok"
    a = evaluate("retriever", candidate_count=10, reuse_rate=1.0,
                 layout_shuffled=True)
    assert not a.blocked
    assert "not judge-type" in a.reason


def test_aegis_lt_endpoint_routing():
    """When lt_endpoint is set, the model's HTTP base URL is rewritten
    to the proxy. In smolagents 1.25.0 the live URL lives on
    ``model.client.base_url`` and ``model.client_kwargs['base_url']``.
    We assert on the live client URL — that's the one used at request time.
    """
    model = OpenAIModel(
        model_id="any",
        api_base="https://api.openai.com/v1",
        api_key="sk-not-real-test",
    )
    agent = CodeAgent(tools=[], model=model, max_steps=1)
    AegisGuard.wrap(agent, lt_endpoint="http://localhost:8080")
    # client.base_url is an httpx.URL; coerce to str for compare.
    assert str(agent.model.client.base_url).rstrip("/") == "http://localhost:8080/v1"
    assert agent.model.client_kwargs["base_url"] == "http://localhost:8080/v1"
    # Bare host with /v1 already present — should not double-suffix.
    AegisGuard.wrap(agent, lt_endpoint="http://lt.internal:9000/v1")
    assert str(agent.model.client.base_url).rstrip("/") == "http://lt.internal:9000/v1"


def test_aegis_writes_audit_log(tmp_path):
    """Every step decision is appended to the audit log as JSONL."""
    agent = _new_agent()
    log_path = tmp_path / "audit.jsonl"
    guarded = AegisGuard.wrap(agent, judge_role="critic", tau=0.65,
                              audit_log=log_path)
    guarded.aegis_meta = {"role": "retriever", "candidate_count": 2,
                          "reuse_rate": 0.0, "layout_shuffled": False}
    guarded.run("noop")
    assert log_path.is_file()
    lines = [ln for ln in log_path.read_text().splitlines() if ln.strip()]
    assert lines, "expected at least one audit-log entry"
    import json
    first = json.loads(lines[0])
    assert first["role"] == "retriever"
    assert first["blocked"] is False
