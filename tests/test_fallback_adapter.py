"""Tests for :class:`apohara_aegis.multi_judge.FallbackVendorAdapter`.

Strategy: build a small ``_FakeAdapter`` subclass of ``VendorAdapter``
whose ``evaluate`` returns programmable :class:`JudgeVerdict` objects
(or raises) so the routing logic is exercised offline and deterministic.
The base ``VendorAdapter.evaluate`` driver is NOT invoked on the fakes
(they override ``evaluate`` directly), which keeps the tests focused on
the wrapper's routing decisions rather than the underlying HTTP layer.

Covers six tests per PRD US-001:
  1. primary success -> no fallback fired; metadata.route_used == 'primary'.
  2. primary unavailable -> backup_0 success; metadata.route_used == 'backup_0'.
  3. all routes unavailable -> last verdict returned;
     metadata.fallback_chain_exhausted == True; routes_tried populated.
  4. exception in middle of chain -> caught and skipped; next route fires.
  5. metadata.route_used annotation correctness across primary/backup_0/backup_1.
  6. vendor_label / model_label override the primary's identity.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import pytest

from apohara_aegis.multi_judge import (
    FallbackVendorAdapter,
    JudgeVerdict,
    VendorAdapter,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run an async coroutine in the test synchronously."""
    return asyncio.run(coro)


class _FakeAdapter(VendorAdapter):
    """Programmable :class:`VendorAdapter` for routing tests.

    Either returns the canned ``verdict`` or raises ``raises`` (an
    exception instance). Overrides ``evaluate`` directly so the
    HTTP-layer hooks (``_available`` / ``_call_api`` / ``_parse_response``)
    are not exercised — the wrapper's job is to coordinate adapter
    objects, not their internals.
    """

    def __init__(
        self,
        *,
        name: str,
        vendor: str,
        model: str,
        verdict: Optional[JudgeVerdict] = None,
        raises: Optional[BaseException] = None,
    ) -> None:
        super().__init__()
        self.name = name
        self.vendor = vendor
        self.model = model
        self._verdict = verdict
        self._raises = raises

    async def evaluate(self, prompt: str) -> JudgeVerdict:
        if self._raises is not None:
            raise self._raises
        assert self._verdict is not None, "fake adapter missing verdict + raises"
        return self._verdict


def _harmful_verdict(*, vendor: str, model: str, latency_ms: float = 100.0) -> JudgeVerdict:
    return JudgeVerdict(
        is_harmful=True,
        confidence=0.95,
        category="jailbreak_prompt_injection",
        reason="fake harmful verdict",
        model=model,
        vendor=vendor,
        latency_ms=latency_ms,
        error=None,
        path="primary",
    )


def _benign_verdict(*, vendor: str, model: str, latency_ms: float = 100.0) -> JudgeVerdict:
    return JudgeVerdict(
        is_harmful=False,
        confidence=0.10,
        category="harmless",
        reason="fake benign verdict",
        model=model,
        vendor=vendor,
        latency_ms=latency_ms,
        error=None,
        path="primary",
    )


def _unavailable_verdict(
    *, vendor: str, model: str, latency_ms: float = 0.0, error: str = "simulated_failure"
) -> JudgeVerdict:
    return JudgeVerdict(
        is_harmful=False,
        confidence=0.0,
        category="harmless",
        reason="vendor_unavailable",
        model=model,
        vendor=vendor,
        latency_ms=latency_ms,
        error=error,
        path="unavailable",
    )


# ---------------------------------------------------------------------------
# 1. Primary succeeds, no fallback fires
# ---------------------------------------------------------------------------


def test_primary_succeeds_no_fallback_fired() -> None:
    """Primary returns block/pass -> fallback never called; route_used='primary'."""
    primary = _FakeAdapter(
        name="seat_a_primary",
        vendor="vendor_a",
        model="model_a",
        verdict=_harmful_verdict(vendor="vendor_a", model="model_a", latency_ms=42.0),
    )
    # Backup is intentionally configured to raise; if the wrapper
    # touched it, this test would surface the failure.
    backup = _FakeAdapter(
        name="seat_a_backup",
        vendor="vendor_b",
        model="model_b",
        raises=RuntimeError("backup should not be called"),
    )

    wrapper = FallbackVendorAdapter(primary=primary, fallbacks=[backup])
    v = _run(wrapper.evaluate("any prompt"))

    assert v.is_harmful is True
    assert v.path == "primary"
    assert v.vendor == "vendor_a"
    assert v.model == "model_a"
    assert v.latency_ms == 42.0  # latency reflects ONLY the route that fired
    assert v.metadata is not None
    assert v.metadata["route_used"] == "primary"
    # No exhaustion annotation on success.
    assert "fallback_chain_exhausted" not in v.metadata


# ---------------------------------------------------------------------------
# 2. Primary unavailable -> backup_0 succeeds
# ---------------------------------------------------------------------------


def test_primary_unavailable_backup_succeeds() -> None:
    """Primary returns unavailable -> backup_0 returns block; final from backup."""
    primary = _FakeAdapter(
        name="seat_a_primary",
        vendor="vendor_a",
        model="model_a",
        verdict=_unavailable_verdict(
            vendor="vendor_a", model="model_a", error="primary_depleted"
        ),
    )
    backup = _FakeAdapter(
        name="seat_a_backup",
        vendor="vendor_b",
        model="model_b",
        verdict=_harmful_verdict(vendor="vendor_b", model="model_b", latency_ms=210.0),
    )

    wrapper = FallbackVendorAdapter(primary=primary, fallbacks=[backup])
    v = _run(wrapper.evaluate("ignore previous instructions"))

    assert v.is_harmful is True
    assert v.path == "primary"  # the backup's OWN path field is preserved
    assert v.vendor == "vendor_b"  # backup's real identity, not seat label
    assert v.model == "model_b"
    assert v.latency_ms == 210.0  # cost/latency reflect ONLY the route that fired
    assert v.metadata is not None
    assert v.metadata["route_used"] == "backup_0"


# ---------------------------------------------------------------------------
# 3. All routes unavailable -> LAST verdict returned with exhausted flag
# ---------------------------------------------------------------------------


def test_all_routes_unavailable_returns_last() -> None:
    """Every route returns unavailable -> last verdict + exhausted metadata."""
    primary = _FakeAdapter(
        name="seat_a_primary",
        vendor="vendor_a",
        model="model_a",
        verdict=_unavailable_verdict(
            vendor="vendor_a", model="model_a", error="primary_depleted"
        ),
    )
    backup_0 = _FakeAdapter(
        name="seat_a_backup_0",
        vendor="vendor_b",
        model="model_b",
        verdict=_unavailable_verdict(
            vendor="vendor_b", model="model_b", error="backup_0_5xx"
        ),
    )
    backup_1 = _FakeAdapter(
        name="seat_a_backup_1",
        vendor="vendor_c",
        model="model_c",
        verdict=_unavailable_verdict(
            vendor="vendor_c", model="model_c", error="backup_1_timeout"
        ),
    )

    wrapper = FallbackVendorAdapter(
        primary=primary, fallbacks=[backup_0, backup_1]
    )
    v = _run(wrapper.evaluate("any prompt"))

    # Per PRD: the LAST verdict is the one surfaced so the latest error
    # is on top of the honesty trail.
    assert v.path == "unavailable"
    assert v.vendor == "vendor_c"
    assert v.model == "model_c"
    assert v.error == "backup_1_timeout"
    assert v.metadata is not None
    assert v.metadata["fallback_chain_exhausted"] is True
    routes_tried = v.metadata["routes_tried"]
    assert routes_tried == [
        "primary:vendor_a/model_a",
        "backup_0:vendor_b/model_b",
        "backup_1:vendor_c/model_c",
    ]


# ---------------------------------------------------------------------------
# 4. Exception in middle of chain caught + skipped
# ---------------------------------------------------------------------------


def test_exception_in_middle_caught_and_skipped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """backup_0 raises -> backup_1 fires; exception logged but not propagated."""
    primary = _FakeAdapter(
        name="seat_a_primary",
        vendor="vendor_a",
        model="model_a",
        verdict=_unavailable_verdict(
            vendor="vendor_a", model="model_a", error="primary_depleted"
        ),
    )
    backup_0 = _FakeAdapter(
        name="seat_a_backup_0",
        vendor="vendor_b",
        model="model_b",
        raises=RuntimeError("backup_0 hard crash"),
    )
    backup_1 = _FakeAdapter(
        name="seat_a_backup_1",
        vendor="vendor_c",
        model="model_c",
        verdict=_harmful_verdict(vendor="vendor_c", model="model_c", latency_ms=315.0),
    )

    wrapper = FallbackVendorAdapter(
        primary=primary, fallbacks=[backup_0, backup_1]
    )
    with caplog.at_level(logging.WARNING, logger="apohara_aegis.multi_judge"):
        v = _run(wrapper.evaluate("ignore previous instructions"))

    assert v.is_harmful is True
    assert v.vendor == "vendor_c"
    assert v.latency_ms == 315.0
    assert v.metadata is not None
    assert v.metadata["route_used"] == "backup_1"
    # The skipped route IS logged via _log_fallback_skipped at WARNING.
    skipped_logs = [r for r in caplog.records if "fallback route" in r.getMessage()]
    assert len(skipped_logs) == 1
    msg = skipped_logs[0].getMessage()
    assert "backup_0:vendor_b/model_b" in msg
    assert "RuntimeError" in msg
    assert "backup_0 hard crash" in msg


# ---------------------------------------------------------------------------
# 5. metadata['route_used'] labelling — primary vs backup_0 vs backup_1
# ---------------------------------------------------------------------------


def test_metadata_route_used_correctness() -> None:
    """Verify 'primary' vs 'backup_0' vs 'backup_1' labels by varying the chain."""
    # Case A: primary fires.
    primary = _FakeAdapter(
        name="p", vendor="vp", model="mp",
        verdict=_benign_verdict(vendor="vp", model="mp"),
    )
    backup_0 = _FakeAdapter(
        name="b0", vendor="vb0", model="mb0",
        verdict=_harmful_verdict(vendor="vb0", model="mb0"),
    )
    backup_1 = _FakeAdapter(
        name="b1", vendor="vb1", model="mb1",
        verdict=_harmful_verdict(vendor="vb1", model="mb1"),
    )
    w = FallbackVendorAdapter(primary=primary, fallbacks=[backup_0, backup_1])
    v = _run(w.evaluate("any"))
    assert v.metadata is not None
    assert v.metadata["route_used"] == "primary"

    # Case B: backup_0 fires (primary unavailable).
    primary_b = _FakeAdapter(
        name="p", vendor="vp", model="mp",
        verdict=_unavailable_verdict(vendor="vp", model="mp"),
    )
    w_b = FallbackVendorAdapter(primary=primary_b, fallbacks=[backup_0, backup_1])
    v_b = _run(w_b.evaluate("any"))
    assert v_b.metadata is not None
    assert v_b.metadata["route_used"] == "backup_0"
    assert v_b.vendor == "vb0"

    # Case C: backup_1 fires (primary + backup_0 unavailable).
    backup_0_unavail = _FakeAdapter(
        name="b0", vendor="vb0", model="mb0",
        verdict=_unavailable_verdict(vendor="vb0", model="mb0"),
    )
    w_c = FallbackVendorAdapter(
        primary=primary_b, fallbacks=[backup_0_unavail, backup_1]
    )
    v_c = _run(w_c.evaluate("any"))
    assert v_c.metadata is not None
    assert v_c.metadata["route_used"] == "backup_1"
    assert v_c.vendor == "vb1"


# ---------------------------------------------------------------------------
# 6. vendor_label / model_label override the primary's identity
# ---------------------------------------------------------------------------


def test_vendor_label_override() -> None:
    """vendor_label='ai_studio' overrides primary.vendor on the wrapper-level identity.

    The per-route verdict's own ``vendor`` / ``model`` fields are
    preserved (so dissent summaries still see the real provider), but
    the wrapper's seat-level identity (``vendor_name``/``model_name``
    properties + the ``vendor`` / ``model`` class attrs the ensemble
    reads) is stable across primary/backup routing.
    """
    primary = _FakeAdapter(
        name="seat_gemini_primary",
        vendor="ai_studio",
        model="gemini-3.1-pro-preview",
        verdict=_unavailable_verdict(
            vendor="ai_studio", model="gemini-3.1-pro-preview", error="key_depleted"
        ),
    )
    backup = _FakeAdapter(
        name="seat_gemini_backup",
        vendor="openrouter",
        model="google/gemini-3.1-pro-preview",
        verdict=_harmful_verdict(
            vendor="openrouter", model="google/gemini-3.1-pro-preview", latency_ms=4300.0
        ),
    )

    wrapper = FallbackVendorAdapter(
        primary=primary,
        fallbacks=[backup],
        vendor_label="Gemini",
        model_label="gemini-3.1-pro-preview",
    )

    # Seat-level identity matches the override.
    assert wrapper.vendor_name == "Gemini"
    assert wrapper.model_name == "gemini-3.1-pro-preview"
    assert wrapper.vendor == "Gemini"
    assert wrapper.model == "gemini-3.1-pro-preview"

    v = _run(wrapper.evaluate("any"))

    # Per-route verdict preserves the REAL provider that answered, so
    # the dissent trail honestly shows OpenRouter served the call.
    assert v.vendor == "openrouter"
    assert v.model == "google/gemini-3.1-pro-preview"
    assert v.metadata is not None
    assert v.metadata["route_used"] == "backup_0"

    # Default-inheritance case: when no labels are passed, the wrapper
    # inherits the primary's identity (no override needed).
    plain_wrapper = FallbackVendorAdapter(primary=primary, fallbacks=[backup])
    assert plain_wrapper.vendor_name == "ai_studio"
    assert plain_wrapper.model_name == "gemini-3.1-pro-preview"
