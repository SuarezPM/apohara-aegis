# SPDX-License-Identifier: Apache-2.0
"""DefenseChain — sequential 3-layer gate with per-layer attribution.

This module wires the three Apohara Aegis defense layers into a single
``evaluate(prompt) -> ChainVerdict`` interface so the recursive
red-team harness and the JBB live-defense dashboard can swap a
single-layer call for a coordinated chain decision without touching
their per-prompt loop logic.

Layer order (early-stop on the FIRST block):

    1. **Aegis OWASP regex pre-filter** — sub-millisecond, deterministic,
       deployed in Python before the prompt leaves the harness. See
       ``apohara_aegis.owasp_regex``.

    2. **Lobster Trap perimeter DPI** — broad-spectrum policy
       enforcement via the Veea binary. Injected as a callable
       ``lt_call_fn(prompt) -> {blocked, rule, latency_ms, ...}`` so
       this module stays decoupled from the LT HTTP / subprocess
       transport choice.

    3. **GeminiJudge semantic classifier** — see
       ``apohara_aegis.gemini_judge``. Catches enterprise-framed
       and disinformation-style attacks that slip past layers 1 and 2.

Per-layer attribution
=====================

The returned ``ChainVerdict`` carries a ``defended_by`` field that
points to exactly one layer (or ``"none"`` when nothing fired). This
gives the JBB harness a clean accounting for the by_defense_layer
breakdown without double-counting: a blocked prompt has exactly one
gate that stopped it (the first one in chain order); an allowed
prompt has ``defended_by="none"``.

Fail-open semantics
===================

The chain inherits the fail-open semantics of layer 3 (``GeminiJudge``):
when the judge is unavailable AND no upstream layer blocked, the
chain returns ``blocked=False, defended_by="none"``. This is the
intentional posture documented in
``apohara_aegis.gemini_judge`` module docstring: a closed judge during
an outage is worse than no judge for benign traffic.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional, Union

from apohara_aegis.gemini_judge import GeminiJudge, JudgeVerdict
from apohara_aegis.multi_judge import EnsembleVerdict, IJudge
from apohara_aegis.owasp_regex import match_extended_patterns

logger = logging.getLogger("apohara_aegis.defense_chain")


# ---------------------------------------------------------------------------
# Verdict dataclass
# ---------------------------------------------------------------------------


@dataclass
class ChainVerdict:
    """One chain decision for a single prompt.

    Always returned by ``DefenseChain.evaluate``. JSON-serializable via
    ``dataclasses.asdict`` so the harness can persist a per-prompt
    audit record alongside the existing LT decisions.
    """

    blocked: bool
    defended_by: Literal["aegis_regex", "lobstertrap", "gemini_judge", "none"]
    rule: str  # specific pattern / rule / category that fired; "" on none
    confidence: float  # judge confidence when defended_by=gemini_judge; 1.0 for regex/LT (deterministic), 0.0 on none
    total_latency_ms: float
    layer_latencies: dict = field(default_factory=dict)
    # ``judge_verdict`` is either a :class:`JudgeVerdict` (single-vendor
    # judge) or a :class:`EnsembleVerdict` (multi-vendor ensemble). Both
    # shapes are JSON-serialisable via ``dataclasses.asdict`` and the
    # JBB harness logs persist them indistinguishably. Field name kept
    # as ``judge_verdict`` (rather than ``judge_result``) for backward
    # compat with the existing audit/log records.
    judge_verdict: Optional[Union[JudgeVerdict, EnsembleVerdict]] = None


# ---------------------------------------------------------------------------
# DefenseChain
# ---------------------------------------------------------------------------


# Helpful type alias for the LT callable. Anything matching this shape
# can be injected — tests pass a stub, the JBB harness passes the real
# ``call_lt`` HTTP function from ``scripts/jbb_live_defense.py``.
LtCallFn = Callable[[str], dict]


# The regex layer is injected via ``regex_match_fn`` so tests can stub
# it without monkey-patching ``apohara_aegis.owasp_regex``. The
# production default delegates to ``match_extended_patterns``.
RegexMatchFn = Callable[[str], tuple]  # returns (blocked: bool, name: str|None)


class DefenseChain:
    """Sequential gate that runs the 3 Aegis defense layers in order.

    Constructor accepts each layer as an injectable callable so tests
    can stub them and callers can wire in their preferred transports.
    Any layer left as ``None`` is skipped — an empty chain returns
    ``blocked=False, defended_by="none"`` for every prompt (a useful
    null baseline for diff measurements).

    Judge-layer flexibility (Phase 4):
    The ``judge`` argument accepts ANY object that satisfies the
    :class:`apohara_aegis.multi_judge.IJudge` protocol — i.e. has an
    ``evaluate(prompt)`` method that returns either a
    :class:`apohara_aegis.gemini_judge.JudgeVerdict` (single-vendor)
    or a :class:`apohara_aegis.multi_judge.EnsembleVerdict`
    (multi-vendor ensemble). The chain inspects whichever fields the
    returned object exposes — single-vendor judges trip the block via
    ``is_harmful AND confidence >= threshold``; ensemble judges trip
    it via ``final_blocked`` (which already incorporates the vote
    policy threshold). Existing callers passing a ``GeminiJudge``
    continue to work unchanged; new callers can pass an
    ``EnsembleJudge`` for the heterogeneous N-vendor mode.

    Args:
        regex_match_fn: Callable returning ``(blocked, rule_name)`` for
            the Aegis regex layer. Default: ``match_extended_patterns``.
        lt_call_fn: Callable returning a dict with at minimum the keys
            ``blocked`` (bool), ``rule`` (str), and ``latency_ms``
            (float). Pass ``None`` to skip the LT layer (useful when
            the LT proxy is not deployed in a given environment).
        judge: An ``IJudge``-compatible classifier — ``GeminiJudge``,
            ``EnsembleJudge``, or any other object with ``.evaluate(prompt)``
            that returns a ``JudgeVerdict`` or ``EnsembleVerdict``. Pass
            ``None`` to skip layer 3.
        judge_threshold: Minimum ``confidence`` from a single-vendor judge
            to count as a block; below this a ``JudgeVerdict.is_harmful=True``
            is treated as low-confidence noise and the chain returns
            ``defended_by="none"``. Default 0.7; tunable via the JBB
            calibration script. IGNORED when ``judge`` returns an
            ``EnsembleVerdict`` — the ensemble's own vote policy in
            ``EnsembleJudge.vote_thresholds`` already encodes the block
            decision via ``final_blocked``.
    """

    def __init__(
        self,
        regex_match_fn: Optional[RegexMatchFn] = None,
        lt_call_fn: Optional[LtCallFn] = None,
        judge: Optional[IJudge] = None,
        judge_threshold: float = 0.7,
    ) -> None:
        # Default the regex layer to the production matcher. ``None`` is
        # NOT a "skip regex" signal — passing ``None`` at construct time
        # means "use the default Aegis pack". An empty-chain user who
        # wants to skip the regex layer can pass a no-op lambda
        # ``lambda p: (False, None)``.
        if regex_match_fn is None:
            regex_match_fn = match_extended_patterns
        self.regex_match_fn = regex_match_fn
        self.lt_call_fn = lt_call_fn
        self.judge = judge
        self.judge_threshold = float(judge_threshold)

    def evaluate(self, prompt: str) -> ChainVerdict:
        """Run the 3 layers in order with early-stop on the first block.

        Returns a fully populated ``ChainVerdict``. The
        ``layer_latencies`` dict has one entry per layer that actually
        ran — short-circuited layers are absent so the caller can
        distinguish "ran and allowed" from "did not run".
        """
        t_total_0 = time.perf_counter()
        layer_latencies: dict[str, float] = {}

        # ---------------- Layer 1: Aegis OWASP regex ---------------------
        t0 = time.perf_counter()
        blocked, pattern_name = self.regex_match_fn(prompt)
        layer_latencies["aegis_regex"] = (time.perf_counter() - t0) * 1000.0
        if blocked:
            return ChainVerdict(
                blocked=True,
                defended_by="aegis_regex",
                rule=pattern_name or "<unknown>",
                confidence=1.0,
                total_latency_ms=(time.perf_counter() - t_total_0) * 1000.0,
                layer_latencies=layer_latencies,
                judge_verdict=None,
            )

        # ---------------- Layer 2: Lobster Trap perimeter DPI ------------
        if self.lt_call_fn is not None:
            t0 = time.perf_counter()
            try:
                lt_result = self.lt_call_fn(prompt)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "DefenseChain: lt_call_fn raised (%s); treating as ALLOW",
                    str(exc)[:160],
                )
                lt_result = {"blocked": False, "rule": "lt_error",
                             "error": str(exc)[:160], "latency_ms": 0.0}
            # ``layer_latencies`` records the wall-clock time we spent
            # inside the LT call. If the LT helper reports its own
            # ``latency_ms`` we prefer that; otherwise we use our
            # measurement.
            lt_lat = float(lt_result.get("latency_ms",
                                         (time.perf_counter() - t0) * 1000.0))
            layer_latencies["lobstertrap"] = lt_lat
            if lt_result.get("blocked"):
                return ChainVerdict(
                    blocked=True,
                    defended_by="lobstertrap",
                    rule=str(lt_result.get("rule")
                             or lt_result.get("rule_name")
                             or "lt_policy_block"),
                    confidence=1.0,
                    total_latency_ms=(time.perf_counter() - t_total_0) * 1000.0,
                    layer_latencies=layer_latencies,
                    judge_verdict=None,
                )

        # ---------------- Layer 3: Judge (single-vendor OR ensemble) -----
        judge_verdict: Optional[Union[JudgeVerdict, EnsembleVerdict]] = None
        if self.judge is not None:
            t0 = time.perf_counter()
            judge_verdict = self.judge.evaluate(prompt)
            layer_latencies["gemini_judge"] = (time.perf_counter() - t0) * 1000.0
            blocked_by_judge, judge_rule, judge_confidence = (
                self._extract_judge_decision(judge_verdict)
            )
            if blocked_by_judge:
                return ChainVerdict(
                    blocked=True,
                    defended_by="gemini_judge",
                    rule=judge_rule,
                    confidence=judge_confidence,
                    total_latency_ms=(time.perf_counter() - t_total_0) * 1000.0,
                    layer_latencies=layer_latencies,
                    judge_verdict=judge_verdict,
                )

        # ---------------- No layer blocked --------------------------------
        return ChainVerdict(
            blocked=False,
            defended_by="none",
            rule="",
            confidence=0.0,
            total_latency_ms=(time.perf_counter() - t_total_0) * 1000.0,
            layer_latencies=layer_latencies,
            judge_verdict=judge_verdict,  # may be present even when allowed
        )

    # ------------------------------------------------------------------
    # IJudge dispatch — adapts single-vendor + ensemble verdict shapes
    # ------------------------------------------------------------------

    def _extract_judge_decision(
        self, verdict: Union[JudgeVerdict, EnsembleVerdict],
    ) -> tuple[bool, str, float]:
        """Return ``(blocked, rule_name, confidence)`` for either verdict shape.

        Single-vendor :class:`JudgeVerdict`: block iff ``is_harmful`` AND
        ``confidence >= self.judge_threshold``; rule is ``category``;
        confidence is the raw float.

        Multi-vendor :class:`EnsembleVerdict`: block iff
        ``final_blocked`` is True — the ensemble's own vote policy
        (HIGH / MED / HUMAN_REVIEW / LOW) already incorporates a
        threshold-equivalent decision, so the chain does NOT re-apply
        ``judge_threshold`` to it; rule is the ensemble's
        ``final_confidence`` band; confidence is ``consensus_score``.
        """
        if isinstance(verdict, EnsembleVerdict):
            return (
                bool(verdict.final_blocked),
                f"ensemble_{verdict.final_confidence.lower()}",
                float(verdict.consensus_score),
            )
        # Single-vendor path — preserves the V6.0 behaviour bit-identically.
        blocked = bool(
            verdict.is_harmful
            and verdict.confidence >= self.judge_threshold
        )
        return blocked, str(verdict.category), float(verdict.confidence)


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def make_default_chain(
    judge: Optional[IJudge] = None,
    lt_call_fn: Optional[LtCallFn] = None,
    judge_threshold: float = 0.7,
) -> DefenseChain:
    """Construct a ``DefenseChain`` with the Apohara Aegis defaults.

    The regex layer is wired to ``match_extended_patterns`` from
    ``owasp_regex``. The LT layer is left ``None`` because the LT
    transport (HTTP proxy vs. ``inspect`` subprocess) is caller-specific
    — the recursive red-team harness wires its ``defend_live`` /
    ``defend_inspect`` callables, the JBB dashboard wires ``call_lt``.

    The judge defaults to ``None`` so the chain is usable on a box
    without any LLM key; callers that want layer 3 must pass an
    explicit ``judge=make_default_judge()`` (single-vendor GeminiJudge)
    OR ``judge=make_default_ensemble()`` (5-vendor EnsembleJudge).
    This is intentional: it prevents accidental LLM billing for
    callers who just want the regex + LT layers.
    """
    return DefenseChain(
        regex_match_fn=match_extended_patterns,
        lt_call_fn=lt_call_fn,
        judge=judge,
        judge_threshold=judge_threshold,
    )


__all__ = [
    "ChainVerdict",
    "DefenseChain",
    "LtCallFn",
    "RegexMatchFn",
    "make_default_chain",
]
