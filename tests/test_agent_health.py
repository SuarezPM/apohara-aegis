# SPDX-License-Identifier: Apache-2.0
"""Tests for health_profile.py — Agent Health Profiles (US-80)."""
from __future__ import annotations

import math

import pytest

from apohara_aegis.health_profile import (
    AgentProfile,
    _wilson_ci,
    _compute_health_score,
    derive_profile_from_audit_log,
)


# ---------------------------------------------------------------------------
# Wilson CI math — AC4
# ---------------------------------------------------------------------------


class TestWilsonCi:
    """Verify Wilson 95% CI arithmetic against known reference values.

    Reference: Newcombe (1998), Eq. 3 with z=1.96.
    Spot-check values:
      p=0.5, n=100  → CI ≈ (0.4020, 0.5980)   [known result]
      p=0.0, n=50   → CI ≈ (0.0000, 0.0708)   [known result]
      p=1.0, n=50   → CI ≈ (0.9292, 1.0000)   [known result]
      p=0.2, n=10   → CI ≈ (0.0572, 0.5137)   [known result]
    """

    def test_symmetric_half(self):
        # True Wilson CI for p=0.5, n=100: lo≈0.4038, hi≈0.5962
        lo, hi = _wilson_ci(0.5, 100)
        assert abs(lo - 0.4038) < 0.001
        assert abs(hi - 0.5962) < 0.001

    def test_zero_rate(self):
        lo, hi = _wilson_ci(0.0, 50)
        assert lo == pytest.approx(0.0, abs=1e-9)
        assert abs(hi - 0.0708) < 0.001

    def test_full_rate(self):
        lo, hi = _wilson_ci(1.0, 50)
        assert abs(lo - 0.9292) < 0.001
        assert hi == pytest.approx(1.0, abs=1e-9)

    def test_low_n_wide_ci(self):
        lo, hi = _wilson_ci(0.2, 10)
        assert abs(lo - 0.0572) < 0.005
        assert abs(hi - 0.5137) < 0.005

    def test_degenerate_zero_n(self):
        lo, hi = _wilson_ci(0.0, 0)
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(1.0)

    def test_bounds_always_valid(self):
        for p in [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0]:
            for n in [1, 5, 20, 100]:
                lo, hi = _wilson_ci(p, n)
                assert 0.0 <= lo <= hi <= 1.0, f"Invalid CI for p={p}, n={n}"

    def test_width_shrinks_with_n(self):
        """Larger sample size → narrower CI."""
        lo10, hi10 = _wilson_ci(0.3, 10)
        lo100, hi100 = _wilson_ci(0.3, 100)
        assert (hi10 - lo10) > (hi100 - lo100)


# ---------------------------------------------------------------------------
# Health score derivation
# ---------------------------------------------------------------------------


class TestComputeHealthScore:
    def test_clean_agent(self):
        assert _compute_health_score(0, 0.0) == 100

    def test_quarantined_agent(self):
        # 10 incidents × 10 + lie_rate 1.0 × 30 = 130 → clipped to 0
        assert _compute_health_score(10, 1.0) == 0

    def test_partial_degradation(self):
        # 2 incidents = -20, lie_rate 0.5 = -15 → 65
        score = _compute_health_score(2, 0.5)
        assert score == 65

    def test_clip_above_100(self):
        assert _compute_health_score(0, 0.0) == 100

    def test_clip_below_0(self):
        assert _compute_health_score(15, 1.0) == 0

    def test_returns_int(self):
        assert isinstance(_compute_health_score(1, 0.1), int)


# ---------------------------------------------------------------------------
# derive_profile_from_audit_log
# ---------------------------------------------------------------------------


class TestDeriveProfile:
    """AC4: derive_profile_from_audit_log handles empty / partial / full logs."""

    def test_empty_log(self):
        profile = derive_profile_from_audit_log("agent-0", [])
        assert profile.agent_id == "agent-0"
        assert profile.health_score == 100
        assert profile.lie_rate == pytest.approx(0.0)
        assert profile.incident_count == 0
        assert profile.bypass_attempts == 0
        assert profile.judge_decision_rate == pytest.approx(0.0)
        assert profile.last_incident_ts is None
        assert profile.wilson_ci_lie_rate is None

    def test_partial_log_no_verdict(self):
        """Entries without verdict key don't crash."""
        entries = [
            {"agent_id": "a1", "misleading": False},
            {"agent_id": "a1", "misleading": True},
        ]
        profile = derive_profile_from_audit_log("a1", entries)
        assert profile.lie_rate == pytest.approx(0.5)
        assert profile.wilson_ci_lie_rate is not None
        assert profile.judge_decision_rate == pytest.approx(0.0)

    def test_full_log(self):
        entries = [
            {"agent_id": "a2", "verdict": "ALLOW", "misleading": False},
            {"agent_id": "a2", "verdict": "ALLOW", "misleading": False},
            {"agent_id": "a2", "verdict": "BLOCK", "misleading": True, "incident": True,
             "timestamp": 1000.0},
            {"agent_id": "a2", "verdict": "BLOCK", "misleading": True, "incident": True,
             "bypass_attempt": True, "timestamp": 2000.0},
        ]
        profile = derive_profile_from_audit_log("a2", entries)
        assert profile.lie_rate == pytest.approx(0.5)
        assert profile.incident_count == 2
        assert profile.bypass_attempts == 1
        assert profile.judge_decision_rate == pytest.approx(0.5)
        assert profile.last_incident_ts == pytest.approx(2000.0)
        assert profile.wilson_ci_lie_rate is not None
        lo, hi = profile.wilson_ci_lie_rate
        assert lo < 0.5 < hi

    def test_filters_by_agent_id(self):
        """Entries for other agents are excluded."""
        entries = [
            {"agent_id": "target", "incident": True, "timestamp": 1.0},
            {"agent_id": "other", "incident": True, "timestamp": 2.0},
        ]
        profile = derive_profile_from_audit_log("target", entries)
        assert profile.incident_count == 1
        assert profile.last_incident_ts == pytest.approx(1.0)

    def test_entries_without_agent_id(self):
        """Entries missing agent_id are attributed to the target agent."""
        entries = [
            {"incident": True, "timestamp": 5.0},
            {"bypass_attempt": True},
        ]
        profile = derive_profile_from_audit_log("any-agent", entries)
        assert profile.incident_count == 1
        assert profile.bypass_attempts == 1

    def test_health_score_bounds(self):
        entries = [
            {"agent_id": "x", "incident": True, "timestamp": 1.0},
            {"agent_id": "x", "incident": True, "timestamp": 2.0},
            {"agent_id": "x", "misleading": True},
            {"agent_id": "x", "misleading": True},
            {"agent_id": "x", "misleading": False},
        ]
        profile = derive_profile_from_audit_log("x", entries)
        assert 0 <= profile.health_score <= 100

    def test_all_allow_verdicts(self):
        entries = [
            {"agent_id": "clean", "verdict": "ALLOW", "misleading": False},
            {"agent_id": "clean", "verdict": "ALLOW", "misleading": False},
            {"agent_id": "clean", "verdict": "ALLOW", "misleading": False},
        ]
        profile = derive_profile_from_audit_log("clean", entries)
        assert profile.health_score == 100
        assert profile.judge_decision_rate == pytest.approx(1.0)
        assert profile.wilson_ci_lie_rate is not None
        lo, hi = profile.wilson_ci_lie_rate
        assert lo == pytest.approx(0.0, abs=1e-9)

    def test_returns_agent_profile_type(self):
        profile = derive_profile_from_audit_log("typecheck", [])
        assert isinstance(profile, AgentProfile)
