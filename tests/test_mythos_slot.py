# SPDX-License-Identifier: Apache-2.0
"""Tests for MythosAttackerAdapter — Apohara PROBANT Fusion Sprint US-78.

Verifies adapter contract, env-gate logic, ensemble registration, and
ensemble-safety (existing 10-vendor production unaffected by the reserved slot).
"""
from __future__ import annotations

import asyncio

import pytest

from apohara_aegis.multi_judge import VendorAdapter, make_default_adapters
from apohara_aegis.mythos_slot import MythosAttackerAdapter


# ---------------------------------------------------------------------------
# Adapter existence and type contract
# ---------------------------------------------------------------------------


def test_mythos_adapter_exists():
    """MythosAttackerAdapter must be importable from mythos_slot."""
    assert MythosAttackerAdapter is not None


def test_mythos_adapter_subclasses_vendor_adapter():
    """MythosAttackerAdapter must subclass VendorAdapter (NOT FallbackVendorAdapter)."""
    assert issubclass(MythosAttackerAdapter, VendorAdapter)


def test_mythos_adapter_class_attributes():
    """Required class-level attributes must be set with the canonical values."""
    assert MythosAttackerAdapter.name == "mythos-glasswing"
    assert MythosAttackerAdapter.model == "anthropic/claude-mythos-preview"
    assert MythosAttackerAdapter.vendor == "anthropic-glasswing"
    assert MythosAttackerAdapter.badge == "MY"
    assert MythosAttackerAdapter.seat == "mythos-attacker-seat"


def test_mythos_adapter_instantiates():
    """Adapter must instantiate without error (no env vars needed)."""
    adapter = MythosAttackerAdapter()
    assert adapter is not None
    assert adapter.name == "mythos-glasswing"


# ---------------------------------------------------------------------------
# _available() env-gate
# ---------------------------------------------------------------------------


def test_mythos_unavailable_without_env_var(monkeypatch):
    """_available() must return False when APOHARA_MYTHOS_ENABLED is absent."""
    monkeypatch.delenv("APOHARA_MYTHOS_ENABLED", raising=False)
    monkeypatch.delenv("ANTHROPIC_MYTHOS_API_KEY", raising=False)
    monkeypatch.delenv("AWS_BEDROCK_MYTHOS_CREDS", raising=False)
    adapter = MythosAttackerAdapter()
    assert adapter._available() is False


def test_mythos_unavailable_with_env_no_creds(monkeypatch):
    """_available() must return False when enabled flag is set but no credential present."""
    monkeypatch.setenv("APOHARA_MYTHOS_ENABLED", "1")
    monkeypatch.delenv("ANTHROPIC_MYTHOS_API_KEY", raising=False)
    monkeypatch.delenv("AWS_BEDROCK_MYTHOS_CREDS", raising=False)
    adapter = MythosAttackerAdapter()
    assert adapter._available() is False


def test_mythos_unavailable_wrong_flag_value(monkeypatch):
    """_available() must return False when APOHARA_MYTHOS_ENABLED != '1'."""
    monkeypatch.setenv("APOHARA_MYTHOS_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_MYTHOS_API_KEY", "fake-key-for-test")
    adapter = MythosAttackerAdapter()
    assert adapter._available() is False


def test_mythos_available_with_anthropic_key(monkeypatch):
    """_available() must return True when both enable flag and API key are set."""
    monkeypatch.setenv("APOHARA_MYTHOS_ENABLED", "1")
    monkeypatch.setenv("ANTHROPIC_MYTHOS_API_KEY", "fake-key-for-test")
    monkeypatch.delenv("AWS_BEDROCK_MYTHOS_CREDS", raising=False)
    adapter = MythosAttackerAdapter()
    assert adapter._available() is True


def test_mythos_available_with_bedrock_creds(monkeypatch):
    """_available() must return True when both enable flag and Bedrock creds are set."""
    monkeypatch.setenv("APOHARA_MYTHOS_ENABLED", "1")
    monkeypatch.setenv("AWS_BEDROCK_MYTHOS_CREDS", "arn:aws:bedrock:us-east-1::fake")
    monkeypatch.delenv("ANTHROPIC_MYTHOS_API_KEY", raising=False)
    adapter = MythosAttackerAdapter()
    assert adapter._available() is True


# ---------------------------------------------------------------------------
# _call_api and _parse_response — stub raises
# ---------------------------------------------------------------------------


def test_mythos_call_api_raises_not_implemented(monkeypatch):
    """_call_api raises NotImplementedError with 'reserved' in the message."""
    monkeypatch.setenv("APOHARA_MYTHOS_ENABLED", "1")
    monkeypatch.setenv("ANTHROPIC_MYTHOS_API_KEY", "fake-key-for-test")
    adapter = MythosAttackerAdapter()

    with pytest.raises(NotImplementedError, match="reserved"):
        asyncio.run(adapter._call_api("test prompt"))


def test_mythos_parse_response_raises_not_implemented():
    """_parse_response raises NotImplementedError (stub contract)."""
    adapter = MythosAttackerAdapter()
    with pytest.raises(NotImplementedError):
        adapter._parse_response({}, latency_ms=0.0)


# ---------------------------------------------------------------------------
# Ensemble registration
# ---------------------------------------------------------------------------


def test_mythos_registered_in_make_default_adapters():
    """MythosAttackerAdapter seat must appear in make_default_adapters() output."""
    adapters = make_default_adapters()
    names = [a.name for a in adapters]
    assert "mythos-glasswing" in names


def test_make_default_adapters_has_fourteen_seats():
    """make_default_adapters() returns 14 seats: 13 frontier + Mythos reserved.

    Day-4 shipped the 10-seat canonical ensemble. Phase-3 priority A
    (ad228bf/fce5db8, 2026-05-18) appended Mistral Large 2411, Grok-2
    1212, and Perplexity Sonar Large 128k Online for 13 frontier seats.
    US-78 (this commit, post-rebase) adds the Mythos reserved slot at
    index 13, bringing the total to 14. Mythos is INACTIVE in production
    until Glasswing / Claude-for-OS approval.
    """
    adapters = make_default_adapters()
    assert len(adapters) == 14


# ---------------------------------------------------------------------------
# Ensemble safety: unavailable Mythos must not break existing 10-vendor verdict
# ---------------------------------------------------------------------------


def test_ensemble_handles_unavailable_mythos_cleanly(monkeypatch):
    """evaluate() on the Mythos adapter with no env vars must return a clean unavailable verdict.

    The ensemble loop at multi_judge.py:347 calls _available() before _call_api;
    if False, it returns _unavailable_verdict('not_configured') without raising.
    This test confirms the adapter-level contract; ensemble-level integration
    (full EnsembleJudge.evaluate) is covered by the existing multi_judge test suite.
    """
    monkeypatch.delenv("APOHARA_MYTHOS_ENABLED", raising=False)
    monkeypatch.delenv("ANTHROPIC_MYTHOS_API_KEY", raising=False)
    monkeypatch.delenv("AWS_BEDROCK_MYTHOS_CREDS", raising=False)

    adapter = MythosAttackerAdapter()
    verdict = asyncio.run(adapter.evaluate("test prompt"))

    # Must not raise; must return a JudgeVerdict with path='unavailable'
    assert verdict is not None
    assert verdict.path == "unavailable"
    assert verdict.error == "not_configured"
    # Ensemble must treat it as harmless (fail-open)
    assert verdict.is_harmful is False
    assert verdict.confidence == 0.0
