# SPDX-License-Identifier: Apache-2.0
"""
Dual-layer verdict combine -- DJL (Zero-LLM Deterministic Judge) +
LLM ensemble (12-vendor adversarial consensus).

Per ralplan principle P3: BOTH layers run in parallel via asyncio.gather.
Both verdicts emitted independently (auditable per-layer in HMAC chain).
ENFORCE layer applies safe-merge policy.

This is NOT "DJL is primary gate, LLM is theater":
- Both layers have peer veto power (BLOCK | BLOCK = BLOCK)
- ALLOW requires CONSENSUS (both must agree)
- Either layer can DEMOTE the other's ALLOW to REVIEW

DJL provides prompt-injection-immune semantic coverage on 62 rules.
LLM ensemble (12-vendor adversarial) provides general-purpose semantic
coverage that catches novel attacks not in the rule corpus.

Part of the Apohara PROBANT Fusion Sprint (2026-05-18).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from .djl import DjlEngine, DjlVerdict


@dataclass(frozen=True)
class LlmEnsembleVerdict:
    """Verdict from the 12-vendor LLM adversarial ensemble."""

    decision: Literal["ALLOW", "REVIEW", "BLOCK"]
    vendor_votes: dict[str, str]  # {"claude": "BLOCK", "gpt": "BLOCK", ...}
    block_count: int
    review_count: int
    allow_count: int
    latency_ms: float
    layer: str = "llm_ensemble"


@dataclass(frozen=True)
class CombinedVerdict:
    """Pair of verdicts + safe-merged decision.

    Both per-layer verdicts are preserved independently so the HMAC
    audit chain can record full per-layer provenance (US-86 wires this
    into the verdict_vault).
    """

    djl_verdict: DjlVerdict
    llm_verdict: LlmEnsembleVerdict | None
    decision: Literal["ALLOW", "REVIEW", "BLOCK"]  # safe-merged
    decision_reason: str  # e.g. "both_layers_block", "djl_review_llm_allow"
    total_latency_ms: float  # max(djl_latency, llm_latency) -- parallel exec
    layer: str = "combined"


async def combine(
    prompt: str,
    context: dict | None,
    djl_engine: DjlEngine,
    llm_ensemble_fn: (
        Callable[[str, dict | None], Awaitable[LlmEnsembleVerdict]] | None
    ) = None,
) -> CombinedVerdict:
    """Run DJL + LLM ensemble in parallel via asyncio.gather + safe-merge.

    If ``llm_ensemble_fn`` is ``None`` (e.g. dev mode without API keys),
    returns djl-only. The combined ``decision`` reduces to ``djl.decision``
    in that case, with ``decision_reason`` reflecting that only one layer
    evaluated.

    Args:
        prompt: Untrusted input to evaluate.
        context: Optional per-tenant policy / agent metadata.
        djl_engine: The :class:`DjlEngine` to run synchronously in a
            worker thread (``asyncio.to_thread``) so it can be awaited
            alongside the LLM ensemble.
        llm_ensemble_fn: Optional async callable returning an
            :class:`LlmEnsembleVerdict`. When omitted, only DJL runs.

    Returns:
        :class:`CombinedVerdict` with both per-layer verdicts preserved
        and the safe-merged decision applied.
    """
    # Schedule both layers in parallel
    djl_task = asyncio.create_task(
        asyncio.to_thread(djl_engine.evaluate, prompt, context)
    )
    llm_task = (
        asyncio.create_task(llm_ensemble_fn(prompt, context))
        if llm_ensemble_fn is not None
        else None
    )

    djl = await djl_task
    llm = await llm_task if llm_task is not None else None

    # Safe-merge policy
    if llm is None:
        return CombinedVerdict(
            djl_verdict=djl,
            llm_verdict=None,
            decision=djl.decision,
            decision_reason=f"djl_only_{djl.decision.lower()}",
            total_latency_ms=djl.latency_ms,
        )

    djl_d, llm_d = djl.decision, llm.decision
    if djl_d == "BLOCK" or llm_d == "BLOCK":
        # Either layer can veto
        if djl_d == "BLOCK" and llm_d == "BLOCK":
            decision, reason = "BLOCK", "both_layers_block"
        elif djl_d == "BLOCK":
            decision, reason = "BLOCK", "djl_block_llm_did_not"
        else:
            decision, reason = "BLOCK", "llm_block_djl_did_not"
    elif djl_d == "ALLOW" and llm_d == "ALLOW":
        decision, reason = "ALLOW", "consensus_allow"
    else:
        # At least one says REVIEW (or DJL says ALLOW + LLM says REVIEW; or vice versa)
        decision, reason = "REVIEW", f"djl_{djl_d.lower()}_llm_{llm_d.lower()}"

    return CombinedVerdict(
        djl_verdict=djl,
        llm_verdict=llm,
        decision=decision,
        decision_reason=reason,
        total_latency_ms=max(djl.latency_ms, llm.latency_ms),
    )


__all__ = [
    "CombinedVerdict",
    "LlmEnsembleVerdict",
    "combine",
]
