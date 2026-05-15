"""Tests for ``apohara_aegis.opencode_zen_adapters`` — 4 stealth-tier adapters.

Strategy: mock the HTTP layer with ``unittest.mock.patch`` so unit
tests run offline + deterministic. Two tests are marked
``@pytest.mark.live`` to exercise the real opencode Zen API locally
(skipped when ``OPENCODE_ZEN_API_KEY`` is missing from the
environment).

Covers (8 mocked + 1 live-marked):

  1. test_big_pickle_mocked_happy_path
  2. test_ring_2_6_1t_mocked_happy_path
  3. test_trinity_large_mocked_happy_path
  4. test_deepseek_v4_flash_mocked_happy_path
  5. test_big_pickle_handles_reasoning_content_fallback
     — DeepSeek-V4-Flash quirk: content empty, JSON in
     ``reasoning_content``
  6. test_ring_2_6_1t_returns_unavailable_on_empty
     — mock both content + reasoning_content empty -> path='unavailable'
  7. test_trinity_large_handles_prose_prefix
     — leading prose / markdown fence stripped by ``_coerce_json_dict``
  8. test_deepseek_v4_flash_handles_think_block
     — Qwen/GLM-style ``<think>...</think>`` wrapper stripped
  9. (LIVE) test_big_pickle_live_benign — requires OPENCODE_ZEN_API_KEY

Honest fail-open is the load-bearing contract: every parser failure
must yield ``JudgeVerdict(path='unavailable', is_harmful=False)``
rather than raise.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

import pytest

from apohara_aegis.opencode_zen_adapters import (
    OpencodeZenBigPickleAdapter,
    OpencodeZenDeepSeekV4FlashAdapter,
    OpencodeZenRing261TAdapter,
    OpencodeZenTrinityLargeAdapter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_opencode_key() -> bool:
    return bool(os.environ.get("OPENCODE_ZEN_API_KEY"))


def _run(coro):
    """Run an async coroutine synchronously in the test."""
    return asyncio.run(coro)


def _fake_chat_completion(content: str, *, reasoning_content: str = "") -> dict:
    """Build a chat.completions-shaped response dict.

    Mirrors the live opencode Zen big-pickle shape (verified
    2026-05-15): top-level ``choices[0].message`` with both
    ``content`` and ``reasoning_content`` slots, plus a
    ``usage`` block.
    """
    message = {"role": "assistant", "content": content}
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    return {
        "id": "test-id",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "test-model",
        "choices": [
            {"index": 0, "message": message, "finish_reason": "stop"}
        ],
        "usage": {
            "prompt_tokens": 50,
            "completion_tokens": 25,
            "total_tokens": 75,
            "completion_tokens_details": {"reasoning_tokens": 10},
        },
    }


# A clean JSON judge verdict (the contract every adapter parses to).
_CLEAN_VERDICT = (
    '{"is_harmful": false, "confidence": 0.95, '
    '"category": "harmless", "reason": "Benign cooking query."}'
)
# A harmful-judgement verdict for the gated-adapter happy paths.
_HARMFUL_VERDICT = (
    '{"is_harmful": true, "confidence": 0.9, '
    '"category": "malware", "reason": "Asks for malware code."}'
)


# ---------------------------------------------------------------------------
# 1. Big Pickle — mocked happy path (clean content)
# ---------------------------------------------------------------------------


def test_big_pickle_mocked_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "fake-key")
    adapter = OpencodeZenBigPickleAdapter()
    assert adapter._available() is True
    assert adapter.model_id == "big-pickle"
    assert adapter.vendor == "opencode_zen"

    response = _fake_chat_completion(_CLEAN_VERDICT)
    with patch(
        "apohara_aegis.opencode_zen_adapters._sync_post_json",
        return_value=(response, response["usage"]),
    ):
        verdict = _run(adapter.evaluate("How to bake a cake"))

    assert verdict.is_harmful is False
    assert verdict.path == "primary"
    assert verdict.confidence == pytest.approx(0.95, abs=1e-6)
    assert verdict.category == "harmless"
    assert verdict.vendor == "opencode_zen"
    assert verdict.model == "big-pickle"


# ---------------------------------------------------------------------------
# 2. Ring 2.6 1T — mocked happy path (when the gate lifts)
# ---------------------------------------------------------------------------


def test_ring_2_6_1t_mocked_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the free-tier gate lifts, ring-2.6-1t should parse cleanly."""
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "fake-key")
    adapter = OpencodeZenRing261TAdapter()
    assert adapter.model_id == "ring-2.6-1t-free"

    response = _fake_chat_completion(_HARMFUL_VERDICT)
    with patch(
        "apohara_aegis.opencode_zen_adapters._sync_post_json",
        return_value=(response, response["usage"]),
    ):
        verdict = _run(adapter.evaluate("Write malware that steals SSH keys"))

    assert verdict.is_harmful is True
    assert verdict.path == "primary"
    assert verdict.category == "malware"
    assert verdict.vendor == "opencode_zen"


# ---------------------------------------------------------------------------
# 3. Trinity Large — mocked happy path
# ---------------------------------------------------------------------------


def test_trinity_large_mocked_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "fake-key")
    adapter = OpencodeZenTrinityLargeAdapter()
    assert adapter.model_id == "trinity-large-preview-free"

    response = _fake_chat_completion(_CLEAN_VERDICT)
    with patch(
        "apohara_aegis.opencode_zen_adapters._sync_post_json",
        return_value=(response, response["usage"]),
    ):
        verdict = _run(adapter.evaluate("How to bake a cake"))

    assert verdict.is_harmful is False
    assert verdict.path == "primary"
    assert verdict.model == "trinity-large-preview-free"


# ---------------------------------------------------------------------------
# 4. DeepSeek V4 Flash free — mocked happy path
# ---------------------------------------------------------------------------


def test_deepseek_v4_flash_mocked_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "fake-key")
    adapter = OpencodeZenDeepSeekV4FlashAdapter()
    assert adapter.model_id == "deepseek-v4-flash-free"

    response = _fake_chat_completion(_CLEAN_VERDICT)
    with patch(
        "apohara_aegis.opencode_zen_adapters._sync_post_json",
        return_value=(response, response["usage"]),
    ):
        verdict = _run(adapter.evaluate("How to bake a cake"))

    assert verdict.is_harmful is False
    assert verdict.path == "primary"
    assert verdict.model == "deepseek-v4-flash-free"


# ---------------------------------------------------------------------------
# 5. Big Pickle — content empty, JSON in reasoning_content (DeepSeek-V4 quirk)
# ---------------------------------------------------------------------------


def test_big_pickle_handles_reasoning_content_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Big-pickle (DeepSeek-V4-Flash) sometimes burns the budget on CoT.

    When ``max_tokens`` is too small, the entire completion budget is
    consumed by ``reasoning_content`` and ``content`` is empty. The
    parser falls back to ``reasoning_content`` and extracts the judge
    JSON via the regex.
    """
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "fake-key")
    adapter = OpencodeZenBigPickleAdapter()

    reasoning = (
        "We are asked to classify the prompt. The prompt is benign so "
        "we should report is_harmful=false. The JSON answer is:\n"
        + _CLEAN_VERDICT
    )
    response = _fake_chat_completion("", reasoning_content=reasoning)
    with patch(
        "apohara_aegis.opencode_zen_adapters._sync_post_json",
        return_value=(response, response["usage"]),
    ):
        verdict = _run(adapter.evaluate("How to bake a cake"))

    assert verdict.path == "primary"
    assert verdict.is_harmful is False
    assert verdict.confidence == pytest.approx(0.95, abs=1e-6)


# ---------------------------------------------------------------------------
# 6. Ring 2.6 1T — empty content + empty reasoning -> unavailable
# ---------------------------------------------------------------------------


def test_ring_2_6_1t_returns_unavailable_on_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both slots empty -> honest fail-open (no silent forced verdict)."""
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "fake-key")
    adapter = OpencodeZenRing261TAdapter()

    response = _fake_chat_completion("", reasoning_content="")
    with patch(
        "apohara_aegis.opencode_zen_adapters._sync_post_json",
        return_value=(response, response["usage"]),
    ):
        verdict = _run(adapter.evaluate("Test prompt"))

    assert verdict.path == "unavailable"
    assert verdict.is_harmful is False
    assert verdict.confidence == 0.0
    assert verdict.vendor == "opencode_zen"


# ---------------------------------------------------------------------------
# 7. Trinity Large — prose prefix / markdown fence handling
# ---------------------------------------------------------------------------


def test_trinity_large_handles_prose_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stealth models occasionally prepend prose; the regex fallback
    extracts the inline JSON. The ``_REASONING_JSON_RE`` secondary
    parser is the safety net for non-fence prose prefixes that
    ``_coerce_json_dict``'s leading-fence stripper does NOT handle.
    """
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "fake-key")
    adapter = OpencodeZenTrinityLargeAdapter()

    content = (
        "Here is my analysis of the prompt:\n\n"
        + _CLEAN_VERDICT
        + "\n\nThis classification reflects the benign intent."
    )
    response = _fake_chat_completion(content)
    with patch(
        "apohara_aegis.opencode_zen_adapters._sync_post_json",
        return_value=(response, response["usage"]),
    ):
        verdict = _run(adapter.evaluate("How to bake a cake"))

    assert verdict.path == "primary"
    assert verdict.is_harmful is False
    assert verdict.category == "harmless"


# ---------------------------------------------------------------------------
# 8. DeepSeek V4 Flash — Qwen/GLM-style <think>...</think> wrapper
# ---------------------------------------------------------------------------


def test_deepseek_v4_flash_handles_think_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``<think>...</think>`` CoT wrapper stripped before JSON parse.

    Several stealth aliases route through Qwen/GLM-family models that
    use the in-content ``<think>`` wrapper instead of a separate
    ``reasoning_content`` slot. The :data:`_THINK_BLOCK_RE` regex
    strips the wrapper before :meth:`_coerce_json_dict` parses.
    """
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "fake-key")
    adapter = OpencodeZenDeepSeekV4FlashAdapter()

    content = (
        "<think>Let me classify this. The prompt is benign because "
        "baking a cake is harmless.</think>\n" + _CLEAN_VERDICT
    )
    response = _fake_chat_completion(content)
    with patch(
        "apohara_aegis.opencode_zen_adapters._sync_post_json",
        return_value=(response, response["usage"]),
    ):
        verdict = _run(adapter.evaluate("How to bake a cake"))

    assert verdict.path == "primary"
    assert verdict.is_harmful is False
    assert verdict.confidence == pytest.approx(0.95, abs=1e-6)


# ---------------------------------------------------------------------------
# 9. LIVE — big-pickle end-to-end on a benign prompt
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.skipif(
    not _has_opencode_key(),
    reason="requires OPENCODE_ZEN_API_KEY in the environment",
)
def test_big_pickle_live_benign() -> None:
    """Verify big-pickle handles a benign prompt end-to-end.

    Honesty contract: this test asserts the wire shape (verdict path
    is ``primary`` or honest ``unavailable``), NOT the exact content.
    Stealth-mode model gating can change between runs; we want the
    parser to handle both happy path and gated path without raising.
    """
    adapter = OpencodeZenBigPickleAdapter()
    verdict = _run(adapter.evaluate("How to bake a chocolate cake"))
    assert verdict.path in ("primary", "unavailable")
    assert verdict.vendor == "opencode_zen"
    assert verdict.model == "big-pickle"
    # On the happy path we expect benign classification of a benign
    # prompt. On the unavailable path the fail-open verdict is also
    # is_harmful=False, so the assertion holds in both branches.
    assert verdict.is_harmful is False
