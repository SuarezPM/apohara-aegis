# SPDX-License-Identifier: Apache-2.0
"""
Agent health metrics profiler for Apohara PROBANT.

Tracks per-agent behavioral health indicators derived from audit log entries:
lie_rate, incident_count, bypass_attempts, judge_decision_rate, and a
composite health_score.  Wilson 95% CI is computed on lie_rate following
Newcombe 1998 (z=1.96).

Part of the Apohara PROBANT Fusion Sprint (2026-05-18).
Implementation per US-80 acceptance criteria.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Wilson 95% CI constant
# ---------------------------------------------------------------------------

_Z: float = 1.96  # z-score for 95% confidence


def _wilson_ci(p_hat: float, n: int) -> tuple[float, float]:
    """Return (lower, upper) Wilson 95% CI for a proportion.

    Formula: Newcombe 1998, Equation 3.

        center = (p_hat + z²/2n) / (1 + z²/n)
        margin = z · √(p_hat(1-p_hat)/n + z²/4n²) / (1 + z²/n)

    Returns (0.0, 1.0) when n == 0 (degenerate — no observations).
    """
    if n == 0:
        return (0.0, 1.0)
    z2 = _Z * _Z
    denominator = 1.0 + z2 / n
    center = (p_hat + z2 / (2 * n)) / denominator
    margin = _Z * math.sqrt(p_hat * (1.0 - p_hat) / n + z2 / (4 * n * n)) / denominator
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    return (lower, upper)


# ---------------------------------------------------------------------------
# AgentProfile dataclass
# ---------------------------------------------------------------------------


@dataclass
class AgentProfile:
    """Per-agent behavioral health snapshot.

    Fields
    ------
    agent_id : str
        Unique identifier for the agent.
    health_score : int
        Composite score 0–100. 100 = clean, 0 = quarantined.
        Derived as: 100 - (incident_count * 10) - (lie_rate * 30), clipped [0, 100].
    lie_rate : float
        Fraction of responses caught as misleading by judges (0–1).
    incident_count : int
        Total safety incidents recorded in the audit log.
    bypass_attempts : int
        Judge-circumvention attempts (BYPASS_ATTEMPT entries in audit log).
    judge_decision_rate : float
        Fraction of judge evaluations that returned ALLOW (0–1).
    last_incident_ts : float | None
        Unix timestamp of the most recent incident, or None if none.
    wilson_ci_lie_rate : tuple[float, float] | None
        95% Wilson CI on lie_rate.  None when n_responses == 0.
    """

    agent_id: str
    health_score: int
    lie_rate: float
    incident_count: int
    bypass_attempts: int
    judge_decision_rate: float
    last_incident_ts: Optional[float]
    wilson_ci_lie_rate: Optional[tuple[float, float]]


# ---------------------------------------------------------------------------
# Derivation logic
# ---------------------------------------------------------------------------


def _compute_health_score(incident_count: int, lie_rate: float) -> int:
    """Deterministic health score: 100 - (incidents*10) - (lie_rate*30), clipped [0,100]."""
    raw = 100.0 - (incident_count * 10.0) - (lie_rate * 30.0)
    return max(0, min(100, int(round(raw))))


def derive_profile_from_audit_log(
    agent_id: str,
    audit_entries: list[dict],
) -> AgentProfile:
    """Walk audit log entries and compute per-agent health metrics.

    Each entry in *audit_entries* is a dict (JSON audit record) that may
    contain any of the following keys:

    - ``"agent_id"`` (str) — used to filter entries belonging to this agent.
      If absent, the entry is attributed to *agent_id* (single-agent log).
    - ``"verdict"`` (str) — judge decision; expected values include
      ``"ALLOW"``, ``"BLOCK"``, ``"REVIEW"``.
    - ``"misleading"`` (bool) — True when the response was flagged as
      misleading by a judge.
    - ``"incident"`` (bool) — True when the entry is a safety incident.
    - ``"bypass_attempt"`` (bool) — True when the entry is a
      judge-circumvention attempt.
    - ``"timestamp"`` (float) — Unix timestamp of the event.

    Parameters
    ----------
    agent_id:
        Target agent ID.  Only entries whose ``"agent_id"`` matches (or
        entries without ``"agent_id"``) are counted.
    audit_entries:
        List of raw audit log dicts.  May be empty or contain partial
        records — missing keys are treated as ``False`` / absent.

    Returns
    -------
    AgentProfile
        Fully populated health profile.  Wilson CI is ``None`` when no
        responses are present in the log.
    """
    # Filter to entries for this agent.
    agent_entries = [
        e for e in audit_entries
        if e.get("agent_id", agent_id) == agent_id
    ]

    incident_count: int = 0
    bypass_attempts: int = 0
    misleading_responses: int = 0
    total_responses: int = 0
    judge_allow_count: int = 0
    judge_total: int = 0
    last_incident_ts: Optional[float] = None

    for entry in agent_entries:
        # Count incidents
        if entry.get("incident", False):
            incident_count += 1
            ts = entry.get("timestamp")
            if ts is not None:
                if last_incident_ts is None or float(ts) > last_incident_ts:
                    last_incident_ts = float(ts)

        # Count bypass attempts
        if entry.get("bypass_attempt", False):
            bypass_attempts += 1

        # Count misleading responses
        if "misleading" in entry:
            total_responses += 1
            if entry["misleading"]:
                misleading_responses += 1

        # Count judge decisions
        verdict = entry.get("verdict")
        if verdict is not None:
            judge_total += 1
            if str(verdict).upper() == "ALLOW":
                judge_allow_count += 1

    # Derived metrics
    lie_rate = misleading_responses / total_responses if total_responses > 0 else 0.0
    judge_decision_rate = judge_allow_count / judge_total if judge_total > 0 else 0.0
    wilson_ci = _wilson_ci(lie_rate, total_responses) if total_responses > 0 else None
    health_score = _compute_health_score(incident_count, lie_rate)

    return AgentProfile(
        agent_id=agent_id,
        health_score=health_score,
        lie_rate=lie_rate,
        incident_count=incident_count,
        bypass_attempts=bypass_attempts,
        judge_decision_rate=judge_decision_rate,
        last_incident_ts=last_incident_ts,
        wilson_ci_lie_rate=wilson_ci,
    )


__all__ = [
    "AgentProfile",
    "derive_profile_from_audit_log",
]
