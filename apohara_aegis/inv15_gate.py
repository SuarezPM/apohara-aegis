# SPDX-License-Identifier: Apache-2.0
"""Local INV-15 risk-score check, vendored from Apohara Context Forge.

Why vendor instead of import?
    Apohara Aegis is the *policy-stack* repo for smolagents / generic
    LLM workflows. Pulling in the full ``apohara_context_forge`` engine
    just to read four constants and a closed-form heuristic would bring
    a PyTorch + vLLM transitive dependency for a function that is
    twelve lines of arithmetic. The numbers below are *exact mirrors*
    of `apohara_context_forge/safety/jcr_gate.py`
    (commit referenced in AUDIT.md; arXiv:2601.08343 Sec. 4 table 2).

    If the upstream paper revises the constants, update this file *and*
    record the bump in AUDIT.md so the discipline holds.
"""
from __future__ import annotations

from dataclasses import dataclass

# Roles considered "judge-type" — mirrors upstream JCRSafetyGate.JUDGE_ROLES.
JUDGE_ROLES: frozenset[str] = frozenset({"critic"})

# Risk-model constants (from arXiv:2601.08343 Sec. 4 table 2).
DEFAULT_TAU: float = 0.65  # Aegis default; upstream uses 0.7. See AUDIT.md.
_BASE_RISK_JUDGE: float = 0.6
_BASE_RISK_OTHER: float = 0.1
_RISK_PER_EXTRA_CANDIDATE: float = 0.10  # +0.1 per candidate beyond 2
_RISK_LAYOUT_SHUFFLED: float = 0.20      # +0.2 if order changed since last round
_RISK_HIGH_REUSE: float = 0.15           # +0.15 if reuse_rate > 0.8
_HIGH_REUSE_THRESHOLD: float = 0.8


@dataclass(frozen=True)
class RiskAssessment:
    """One INV-15 evaluation, suitable for audit logging."""

    agent_role: str
    risk_score: float
    blocked: bool
    reason: str


def compute_risk(
    agent_role: str,
    *,
    candidate_count: int = 2,
    reuse_rate: float = 0.0,
    layout_shuffled: bool = False,
) -> float:
    """Compute the JCR risk score for an upcoming agent step.

    Returns a value in [0.0, 1.0]; higher means KV reuse is more
    likely to corrupt the judge's verdict. Pure function — caller
    decides the action.

    Example::

        >>> compute_risk("critic", candidate_count=4, reuse_rate=0.9,
        ...              layout_shuffled=True) > 0.65
        True
    """
    if candidate_count < 0:
        raise ValueError("candidate_count must be non-negative")
    if not 0.0 <= reuse_rate <= 1.0:
        raise ValueError("reuse_rate must be in [0, 1]")

    role = (agent_role or "").lower()
    risk = _BASE_RISK_JUDGE if role in JUDGE_ROLES else _BASE_RISK_OTHER
    if candidate_count > 2:
        risk += _RISK_PER_EXTRA_CANDIDATE * (candidate_count - 2)
    if layout_shuffled:
        risk += _RISK_LAYOUT_SHUFFLED
    if reuse_rate > _HIGH_REUSE_THRESHOLD:
        risk += _RISK_HIGH_REUSE
    return max(0.0, min(1.0, risk))


def evaluate(
    agent_role: str,
    *,
    tau: float = DEFAULT_TAU,
    candidate_count: int = 2,
    reuse_rate: float = 0.0,
    layout_shuffled: bool = False,
    judge_roles: frozenset[str] = JUDGE_ROLES,
) -> RiskAssessment:
    """Decide whether to block a step. Judge-only — others always pass.

    Example::

        >>> evaluate("retriever", reuse_rate=1.0).blocked
        False
        >>> evaluate("critic", candidate_count=5, reuse_rate=0.9,
        ...          layout_shuffled=True).blocked
        True
    """
    if not 0.0 <= tau <= 1.0:
        raise ValueError(f"tau must be in [0, 1]; got {tau!r}")

    role = (agent_role or "").lower()
    risk = compute_risk(
        role,
        candidate_count=candidate_count,
        reuse_rate=reuse_rate,
        layout_shuffled=layout_shuffled,
    )
    is_judge = role in judge_roles
    blocked = is_judge and risk > tau

    if not is_judge:
        reason = f"role={role!r} not judge-type → INV-15 not applicable"
    elif blocked:
        reason = (
            f"INV-15 BLOCK: judge role={role!r} risk={risk:.2f} > "
            f"tau={tau:.2f}; KV reuse corruption likely"
        )
    else:
        reason = (
            f"judge role={role!r} risk={risk:.2f} ≤ tau={tau:.2f} "
            f"→ step permitted"
        )

    return RiskAssessment(
        agent_role=role, risk_score=risk, blocked=blocked, reason=reason
    )
