# SPDX-License-Identifier: Apache-2.0
"""Apohara Aegis — defense-in-depth trust layer for multi-agent LLMs.

Public surface::

    from apohara_aegis import AegisGuard, AegisBlocked
    from apohara_aegis import evaluate, compute_risk           # INV-15 scorer
    from apohara_aegis import load_policy, PolicyDigest        # Lobster Trap YAML

The ``AegisGuard.wrap(agent, ...)`` entry point is the recommended way
to attach Aegis to a smolagents pipeline. See ``examples/aegis_smolagents_demo.py``.
"""
from __future__ import annotations

from .inv15_gate import (
    DEFAULT_TAU,
    JUDGE_ROLES,
    RiskAssessment,
    compute_risk,
    evaluate,
)
from .policy_loader import PolicyDigest, load_policy
from .smolagents_integration import AegisBlocked, AegisGuard

__all__ = [
    "AegisGuard",
    "AegisBlocked",
    "DEFAULT_TAU",
    "JUDGE_ROLES",
    "RiskAssessment",
    "compute_risk",
    "evaluate",
    "PolicyDigest",
    "load_policy",
]

__version__ = "0.1.0"
