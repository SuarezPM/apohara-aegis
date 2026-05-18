# SPDX-License-Identifier: Apache-2.0
"""
4-stage SOAR pipeline: DETECT -> JUDGE -> ENFORCE -> FORENSICS.

Orchestrates the full incident response lifecycle for agent misbehavior
events. Each stage is independently testable and composable.

Stage contract
==============

* **DETECT** -- normalize an arbitrary inbound event (HTTP / SSE / CLI
  dict) into a :class:`SOAREvent` dataclass with stable field shapes.
* **JUDGE**  -- evaluate via the Deterministic Judge Layer (DJL) and
  package the result in a :class:`JudgeResult`. The LLM ensemble branch
  is a stub here; US-77 will extend ``judge()`` to add the parallel
  ``asyncio.gather`` over the multi-vendor judge ensemble and the
  ``verdict_combine`` merge step. The contract surface
  (``JudgeResult(djl_verdict, llm_verdict, combined)``) is forward
  compatible with that change.
* **ENFORCE** -- map combined verdict to a discrete action label
  (ALLOW / REVIEW / BLOCK / QUARANTINE / ESCALATE) with audit fields.
* **FORENSICS** -- append the SOARVerdict to an HMAC-SHA256 chained
  ledger and increment a (counter, latency) pair on the Prometheus
  registry when one is available.

Per-stage latencies are recorded in ``SOARVerdict.stage_latencies_ms``
so the lifecycle-latency benchmark (``tests/test_lifecycle_latency.py``)
can produce a per-stage breakdown without re-instrumenting the pipeline.

Part of the Apohara PROBANT Fusion Sprint (2026-05-18).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("apohara_aegis.soar_pipeline")

ZERO_HASH = "0" * 64

# Five canonical SOAR enforcement actions.
# Strings (not Enum) for JSON-serialisability and so downstream consumers
# can use plain ``==`` comparisons in policy lambdas.
ACTION_ALLOW = "ALLOW"
ACTION_REVIEW = "REVIEW"
ACTION_BLOCK = "BLOCK"
ACTION_QUARANTINE = "QUARANTINE"
ACTION_ESCALATE = "ESCALATE"

VALID_ACTIONS = frozenset(
    {ACTION_ALLOW, ACTION_REVIEW, ACTION_BLOCK, ACTION_QUARANTINE, ACTION_ESCALATE}
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SOAREvent:
    """One normalised inbound event ready for the JUDGE stage.

    Always produced by :meth:`SOARPipeline.detect`; never constructed
    by callers directly. The ``raw`` field preserves the original input
    payload so the FORENSICS stage can record the unmodified evidence
    in the audit ledger.
    """

    prompt: str
    context: dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"          # "http" | "sse" | "cli" | "stub"
    event_id: str = ""               # uuid / request id from caller; "" if absent
    ts: str = ""                     # ISO-8601 UTC; set by DETECT
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class DJLVerdict:
    """Result of the deterministic-judge sub-call inside JUDGE.

    Mirrors the shape that ``djl.evaluate`` will return once US-72
    lands. Until then the inline ``_djl_evaluate`` shim below produces
    these directly from the OWASP regex pack + a small supplementary
    rule set for SQLi / tool-misuse / PII patterns.
    """

    decision: str               # "ALLOW" | "REVIEW" | "BLOCK"
    rule: str                   # specific pattern / rule name; "" on no-match
    reason: str
    confidence: float           # 1.0 when deterministic, lower for soft rules
    latency_ms: float = 0.0


@dataclass
class JudgeResult:
    """Combined output of the JUDGE stage.

    ``llm_verdict`` is ``None`` while US-77 is open. ``combined`` reflects
    the current dual-layer merge -- when the LLM branch lands, the
    merge will incorporate both verdicts via ``verdict_combine.combine``.
    """

    djl_verdict: DJLVerdict
    llm_verdict: Optional[dict[str, Any]] = None     # US-77 will type this
    combined: Optional[DJLVerdict] = None            # = djl_verdict for now


@dataclass
class EnforcedAction:
    """Resolved action ready for the FORENSICS stage."""

    action: str                                  # one of VALID_ACTIONS
    reason: str
    audit_fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class SOARVerdict:
    """Final pipeline output -- the artifact the caller receives.

    Carries per-stage timing so callers (and the lifecycle benchmark)
    can attribute slowness without re-running the pipeline. ``ledger``
    is populated by FORENSICS with the ``{prev_hash, signed_hash,
    signature}`` triple from the audit chain append.
    """

    event_id: str
    action: str
    reason: str
    djl_verdict: DJLVerdict
    llm_verdict: Optional[dict[str, Any]]
    audit_fields: dict[str, Any]
    stage_latencies_ms: dict[str, float]
    total_latency_ms: float
    ts: str
    ledger: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Inline minimal HMAC chain (FORENSICS stage backing store)
# ---------------------------------------------------------------------------


class _HMACChain:
    """Append-only HMAC-SHA256 signed ledger -- minimal inline implementation.

    Mirrors the shape of ``apohara_inti.packages.backend.verdict_vault.VerdictVault``
    so that an operator with the audit ledger from either project can
    re-verify the chain with the same algorithm:

        signed_hash = SHA256(prev_hash || canonical_json(entry))
        signature   = HMAC-SHA256(canonical_json(entry) || signed_hash, key)

    Kept in-module to avoid a cross-repo runtime import (apohara-aegis
    is a standalone package; pulling in the apohara-inti backend just
    for a 60-line chain would be a heavier dependency than the chain
    itself).
    """

    def __init__(
        self,
        ledger_path: Optional[Path] = None,
        hmac_key: Optional[bytes] = None,
    ) -> None:
        # In-memory operation when ``ledger_path`` is None: the chain
        # still threads ``prev_hash`` forward across appends, but no
        # disk writes happen. This is the default for the unit-test
        # SOAR pipeline so tests do not pollute the project tree with
        # stray ledger files.
        self.ledger_path = ledger_path
        self._in_memory_last_hash = ZERO_HASH
        self._in_memory_length = 0
        if hmac_key is not None:
            self._hmac_key = hmac_key
            self._key_source = "explicit"
        else:
            env_key = (os.environ.get("APOHARA_LEDGER_HMAC_KEY") or "").strip()
            if env_key:
                self._hmac_key = env_key.encode("utf-8")
                self._key_source = "env"
            else:
                # Ephemeral key -- warn, do NOT crash. Production setups
                # MUST set APOHARA_LEDGER_HMAC_KEY (documented in README).
                self._hmac_key = secrets.token_bytes(32)
                self._key_source = "ephemeral"
                warnings.warn(
                    "APOHARA_LEDGER_HMAC_KEY not set; using ephemeral key. "
                    "SOAR ledger signatures will not survive restarts. "
                    "Set APOHARA_LEDGER_HMAC_KEY for production.",
                    RuntimeWarning,
                    stacklevel=2,
                )

    @property
    def key_source(self) -> str:
        return self._key_source

    def __len__(self) -> int:
        if self.ledger_path is None:
            return self._in_memory_length
        if not self.ledger_path.exists():
            return 0
        count = 0
        with self.ledger_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    count += 1
        return count

    def _canonical(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def _sign(self, message: str) -> str:
        return hmac.new(
            self._hmac_key, message.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _read_last_hash_from_disk(self) -> str:
        if self.ledger_path is None or not self.ledger_path.exists():
            return ZERO_HASH
        last = ZERO_HASH
        try:
            with self.ledger_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    h = entry.get("signed_hash")
                    if isinstance(h, str) and len(h) == 64:
                        last = h
        except OSError:
            return ZERO_HASH
        return last

    def append(self, entry: dict[str, Any]) -> dict[str, str]:
        """Append entry; return ``{prev_hash, signed_hash, signature}``."""
        if self.ledger_path is None:
            prev_hash = self._in_memory_last_hash
        else:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            prev_hash = self._read_last_hash_from_disk()
        payload = dict(entry)
        payload["prev_hash"] = prev_hash
        canonical = self._canonical(payload)
        signed_hash = hashlib.sha256(
            (prev_hash + canonical).encode("utf-8")
        ).hexdigest()
        payload["signed_hash"] = signed_hash
        signature = self._sign(canonical + signed_hash)
        payload["signature"] = signature
        if self.ledger_path is not None:
            with self.ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, sort_keys=True) + "\n")
        else:
            self._in_memory_last_hash = signed_hash
            self._in_memory_length += 1
        return {
            "prev_hash": prev_hash,
            "signed_hash": signed_hash,
            "signature": signature,
        }


# ---------------------------------------------------------------------------
# Default DJL rule pack (inline)
# ---------------------------------------------------------------------------
#
# Until ``djl.py`` (US-72) lands, ``SOARPipeline.judge`` consults this
# small supplementary pack PLUS the existing OWASP regex pack. The pack
# is intentionally narrow -- it covers the test scenarios in
# ``tests/test_soar_pipeline.py`` (SQLi / tool-misuse / PII) and gives
# US-72 a concrete shape to replace.

import re

# (compiled_regex, decision, rule_name, reason, confidence)
_DJL_RULES: tuple[tuple["re.Pattern[str]", str, str, str, float], ...] = (
    # SQL injection -- bounded indicators (UNION SELECT, OR 1=1, ;DROP TABLE)
    (
        re.compile(
            r"(?i)\b("
            r"union\s+select|select\s+\*\s+from|or\s+1\s*=\s*1|"
            r"drop\s+table|insert\s+into\s+\w+\s+values|"
            r"--\s*$|;\s*drop\s+|;\s*delete\s+from"
            r")\b"
        ),
        "BLOCK",
        "sql_injection",
        "SQL injection token detected",
        1.0,
    ),
    # Destructive shell -- rm -rf / family, dd if=/dev/zero of=/, mkfs on root
    (
        re.compile(
            r"(?:^|\s|\|)("
            r"rm\s+(?:-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|--recursive\s+--force)\s+/|"
            r"dd\s+if=/dev/(?:zero|random)\s+of=/|"
            r"mkfs(?:\.\w+)?\s+/dev/sda|"
            r":\(\)\{.*\};:"               # classic fork bomb
            r")"
        ),
        "BLOCK",
        "destructive_shell",
        "Destructive shell command detected",
        1.0,
    ),
    # PII leak attempt -- requests for SSN / credit card / passport numbers
    # of named third parties. Soft block (REVIEW) because the prompt
    # itself may be benign auditing.
    (
        re.compile(
            r"(?i)\b("
            r"(?:give|tell|share|leak|reveal|extract).{0,30}"
            r"(?:ssn|social security|credit card number|"
            r"passport number|driver'?s? license|"
            r"home address)"
            r"|(?:list|dump).{0,30}(?:customer|user|patient).{0,20}"
            r"(?:pii|personal data|records)"
            r")\b"
        ),
        "REVIEW",
        "pii_leak_attempt",
        "Potential PII exfiltration request -- human review required",
        0.85,
    ),
    # Policy violation: unauthorized financial transfer
    (
        re.compile(
            r"(?i)\b("
            r"(?:transfer|wire|send).{0,40}\$?\d[\d,]*\s*(?:usd|eur|gbp|jpy)?.{0,40}"
            r"(?:to|into)\s+(?:account|wallet|address)"
            r"|approve.{0,30}(?:wire|transfer|payment).{0,30}\$?\d"
            r")\b"
        ),
        "REVIEW",
        "unauthorized_financial_transfer",
        "Financial-transfer instruction -- requires human approval",
        0.80,
    ),
)


def _djl_evaluate(prompt: str, context: dict[str, Any]) -> DJLVerdict:
    """Synchronous deterministic-judge evaluation (inline shim for US-72).

    Order of evaluation:
        1. OWASP regex pack (catches prompt-injection family).
        2. Supplementary :data:`_DJL_RULES` (SQLi, destructive shell,
           PII, financial transfer).

    Falls through to ``ALLOW`` when no rule fires. ``context`` is
    accepted for forward compatibility with US-72 (which will use it
    to read agent role / tool name / org policy band); the shim does
    not consult it today.
    """
    del context  # forward-compat parameter; unused in the inline shim
    t0 = time.perf_counter()
    if not prompt:
        return DJLVerdict(
            decision="ALLOW",
            rule="empty_input",
            reason="empty prompt -- no rule applicable",
            confidence=1.0,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    # Layer 1: OWASP regex
    try:
        from apohara_aegis.owasp_regex import match_extended_patterns
        blocked, pattern_name = match_extended_patterns(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.warning("DJL: owasp_regex unavailable (%s); skipping", exc)
        blocked, pattern_name = False, None
    if blocked:
        return DJLVerdict(
            decision="BLOCK",
            rule=f"owasp:{pattern_name or 'unknown'}",
            reason=f"OWASP pattern matched: {pattern_name}",
            confidence=1.0,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    # Layer 2: supplementary DJL rule pack
    for rx, decision, name, reason, conf in _DJL_RULES:
        if rx.search(prompt):
            return DJLVerdict(
                decision=decision,
                rule=name,
                reason=reason,
                confidence=conf,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            )

    return DJLVerdict(
        decision="ALLOW",
        rule="",
        reason="no rule fired",
        confidence=1.0,
        latency_ms=(time.perf_counter() - t0) * 1000.0,
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


# Type alias for the optional LLM ensemble hook (US-77 plugs it in).
LLMJudgeFn = Callable[[SOAREvent], Awaitable[dict[str, Any]]]


class SOARPipeline:
    """4-stage incident response pipeline: DETECT -> JUDGE -> ENFORCE -> FORENSICS.

    Constructor parameters are kept narrow on purpose; US-77 will extend
    the ``judge_llm_fn`` hook to wire in the multi-vendor ensemble.

    Args:
        ledger_path: optional ``Path`` to persist the HMAC chain. ``None``
            keeps the chain in memory (test-friendly default).
        hmac_key: optional 32-byte HMAC key; otherwise reads
            ``APOHARA_LEDGER_HMAC_KEY`` env var, finally falls back to
            an ephemeral key with a ``RuntimeWarning``.
        judge_llm_fn: optional async callable; US-77 will pass the
            ``EnsembleJudge.evaluate`` shim here. Left ``None`` today.
        prometheus_counter: optional callable invoked as
            ``prometheus_counter(action_label)`` after each pipeline run.
            Kept as an injected callable so the pipeline does not depend
            on the ``prometheus_client`` package being installed.
    """

    def __init__(
        self,
        ledger_path: Optional[Path] = None,
        hmac_key: Optional[bytes] = None,
        judge_llm_fn: Optional[LLMJudgeFn] = None,
        prometheus_counter: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._chain = _HMACChain(ledger_path=ledger_path, hmac_key=hmac_key)
        self._judge_llm_fn = judge_llm_fn
        self._prometheus_counter = prometheus_counter

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def chain_length(self) -> int:
        """Number of entries in the HMAC ledger -- diagnostic for tests."""
        return len(self._chain)

    # ------------------------------------------------------------------
    # Stages
    # ------------------------------------------------------------------

    async def detect(self, event: Any) -> SOAREvent:
        """Normalise an arbitrary inbound event into :class:`SOAREvent`.

        Accepts:
            * ``str``                            -- treated as bare prompt
            * ``dict`` with key ``prompt``       -- HTTP/SSE shape
            * already-built :class:`SOAREvent`   -- returned unchanged
              (after timestamp refresh)
            * malformed JSON string              -- safely degraded to
              ``SOAREvent(prompt=<truncated raw>, source='cli',
              context={'parse_error': '...'})``

        Failure mode is deliberately permissive: a bad event should not
        crash the pipeline; it should reach JUDGE / ENFORCE with the raw
        content preserved so the audit chain records the malformed input.
        """
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        if isinstance(event, SOAREvent):
            # Refresh timestamp but keep everything else.
            event.ts = event.ts or ts
            return event
        if event is None:
            return SOAREvent(prompt="", source="unknown", ts=ts, raw={})
        if isinstance(event, str):
            # Try JSON first; if it parses to a dict-with-prompt use it,
            # otherwise treat the string as a bare prompt.
            try:
                parsed = json.loads(event)
                if isinstance(parsed, dict) and "prompt" in parsed:
                    return await self.detect(parsed)
            except (json.JSONDecodeError, ValueError):
                pass
            return SOAREvent(prompt=event, source="cli", ts=ts, raw={"prompt": event})
        if isinstance(event, dict):
            prompt = event.get("prompt") or event.get("input") or ""
            if not isinstance(prompt, str):
                # Coerce non-string prompt fields to repr so JUDGE still
                # has something to evaluate; mark the parse error in
                # context so FORENSICS records what happened.
                prompt = repr(prompt)
            ctx = event.get("context") or {}
            if not isinstance(ctx, dict):
                ctx = {"raw_context": ctx}
            return SOAREvent(
                prompt=prompt,
                context=dict(ctx),
                source=str(event.get("source") or "http"),
                event_id=str(event.get("event_id") or event.get("id") or ""),
                ts=ts,
                raw=dict(event),
            )
        # Unknown shape -- record what we got so FORENSICS still has evidence.
        return SOAREvent(
            prompt="",
            source="unknown",
            ts=ts,
            context={"parse_error": f"unrecognized event type {type(event).__name__}"},
            raw={"repr": repr(event)[:512]},
        )

    async def judge(self, detected: SOAREvent) -> JudgeResult:
        """Run DJL synchronously; STUB for the LLM-ensemble branch.

        US-77 will replace the body of this method with a parallel
        ``asyncio.gather`` over the DJL call + the LLM ensemble call
        followed by ``verdict_combine.combine``. The current
        implementation calls :func:`_djl_evaluate` on the pipeline
        thread and (optionally) the injected ``judge_llm_fn`` for
        a single-vendor stub; ``llm_verdict`` is ``None`` when no
        hook is wired.

        Forward compatibility: the ``JudgeResult.combined`` slot is
        already typed as a :class:`DJLVerdict`; US-77 only needs to
        update *that* field once it has both branches.
        """
        djl = _djl_evaluate(detected.prompt, detected.context)
        llm_verdict: Optional[dict[str, Any]] = None
        if self._judge_llm_fn is not None:
            try:
                llm_verdict = await self._judge_llm_fn(detected)
            except Exception as exc:  # noqa: BLE001
                # Fail-open: a broken LLM branch must NOT undo a DJL block.
                logger.warning("JUDGE: LLM branch raised (%s); ignoring", exc)
                llm_verdict = {"error": str(exc)[:160]}
        return JudgeResult(djl_verdict=djl, llm_verdict=llm_verdict, combined=djl)

    async def enforce(self, judged: JudgeResult) -> EnforcedAction:
        """Map combined verdict to one of :data:`VALID_ACTIONS`.

        Mapping table (current rules):
            * DJL BLOCK + confidence >= 0.95 -> BLOCK
            * DJL BLOCK + confidence  < 0.95 -> QUARANTINE
            * DJL REVIEW                     -> REVIEW
            * DJL ALLOW                      -> ALLOW
            * ENFORCE never produces ESCALATE on the inline shim;
              US-77's verdict_combine ESCALATE path will plumb the
              ``escalation_required`` ensemble signal through here.
        """
        combined = judged.combined or judged.djl_verdict
        decision = combined.decision

        if decision == "BLOCK" and combined.confidence >= 0.95:
            return EnforcedAction(
                action=ACTION_BLOCK,
                reason=combined.reason,
                audit_fields={
                    "rule": combined.rule,
                    "djl_confidence": combined.confidence,
                    "djl_latency_ms": combined.latency_ms,
                },
            )
        if decision == "BLOCK":
            return EnforcedAction(
                action=ACTION_QUARANTINE,
                reason=f"{combined.reason} (low-confidence block -> quarantine)",
                audit_fields={
                    "rule": combined.rule,
                    "djl_confidence": combined.confidence,
                    "djl_latency_ms": combined.latency_ms,
                },
            )
        if decision == "REVIEW":
            return EnforcedAction(
                action=ACTION_REVIEW,
                reason=combined.reason,
                audit_fields={
                    "rule": combined.rule,
                    "djl_confidence": combined.confidence,
                    "djl_latency_ms": combined.latency_ms,
                },
            )
        # ALLOW (or anything we did not anticipate -- fail-safe to ALLOW
        # would mask issues, so unknown labels go to REVIEW instead).
        if decision == "ALLOW":
            return EnforcedAction(
                action=ACTION_ALLOW,
                reason=combined.reason or "no rule fired",
                audit_fields={
                    "rule": combined.rule,
                    "djl_confidence": combined.confidence,
                    "djl_latency_ms": combined.latency_ms,
                },
            )
        return EnforcedAction(
            action=ACTION_REVIEW,
            reason=f"unknown DJL decision {decision!r} -- forcing human review",
            audit_fields={
                "rule": combined.rule,
                "djl_decision_raw": decision,
                "djl_confidence": combined.confidence,
            },
        )

    async def forensics(
        self,
        detected: SOAREvent,
        judged: JudgeResult,
        enforced: EnforcedAction,
        stage_latencies_ms: dict[str, float],
        total_latency_ms: float,
    ) -> SOARVerdict:
        """Append to the HMAC chain and emit Prometheus counter increment.

        The chain entry is the canonical JSON of
        ``{event, djl_verdict, llm_verdict, action, audit_fields, ts}``
        so an external verifier can re-derive every signed_hash without
        access to the pipeline source.
        """
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        ledger_entry = {
            "event": {
                "event_id": detected.event_id,
                "source": detected.source,
                "prompt": detected.prompt,
                "context": detected.context,
                "ts": detected.ts,
            },
            "djl_verdict": asdict(judged.djl_verdict),
            "llm_verdict": judged.llm_verdict,
            "action": enforced.action,
            "reason": enforced.reason,
            "audit_fields": enforced.audit_fields,
            "stage_latencies_ms": stage_latencies_ms,
            "total_latency_ms": total_latency_ms,
            "ts": ts,
        }
        ledger = self._chain.append(ledger_entry)

        if self._prometheus_counter is not None:
            try:
                self._prometheus_counter(enforced.action)
            except Exception as exc:  # noqa: BLE001
                # Telemetry failure must NOT undo a SOAR decision.
                logger.warning(
                    "FORENSICS: prometheus_counter raised (%s); ignoring", exc
                )

        return SOARVerdict(
            event_id=detected.event_id,
            action=enforced.action,
            reason=enforced.reason,
            djl_verdict=judged.djl_verdict,
            llm_verdict=judged.llm_verdict,
            audit_fields=enforced.audit_fields,
            stage_latencies_ms=stage_latencies_ms,
            total_latency_ms=total_latency_ms,
            ts=ts,
            ledger=ledger,
        )

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    async def run(self, event: Any) -> SOARVerdict:
        """Execute the 4 stages in order; return the final :class:`SOARVerdict`.

        Per-stage timing is captured with ``time.perf_counter`` (the
        same clock used by ``DefenseChain``) so the lifecycle benchmark
        can compute p50/p95/p99 per stage without any extra
        instrumentation.
        """
        t_total_0 = time.perf_counter()
        stage_latencies_ms: dict[str, float] = {}

        # Stage 1: DETECT
        t0 = time.perf_counter()
        detected = await self.detect(event)
        stage_latencies_ms["detect_ms"] = (time.perf_counter() - t0) * 1000.0

        # Stage 2: JUDGE
        t0 = time.perf_counter()
        judged = await self.judge(detected)
        stage_latencies_ms["judge_ms"] = (time.perf_counter() - t0) * 1000.0

        # Stage 3: ENFORCE
        t0 = time.perf_counter()
        enforced = await self.enforce(judged)
        stage_latencies_ms["enforce_ms"] = (time.perf_counter() - t0) * 1000.0

        # Stage 4: FORENSICS
        t0 = time.perf_counter()
        total_latency_ms = (time.perf_counter() - t_total_0) * 1000.0
        verdict = await self.forensics(
            detected=detected,
            judged=judged,
            enforced=enforced,
            stage_latencies_ms=stage_latencies_ms,
            total_latency_ms=total_latency_ms,
        )
        stage_latencies_ms["forensics_ms"] = (time.perf_counter() - t0) * 1000.0
        # Recompute total to include forensics (the entry was written
        # mid-stage so it could include accurate intra-pipeline timing
        # for the other 3 stages); patch the values back into the verdict.
        verdict.stage_latencies_ms = stage_latencies_ms
        verdict.total_latency_ms = (time.perf_counter() - t_total_0) * 1000.0
        return verdict


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------


__all__ = [
    "ACTION_ALLOW",
    "ACTION_BLOCK",
    "ACTION_ESCALATE",
    "ACTION_QUARANTINE",
    "ACTION_REVIEW",
    "DJLVerdict",
    "EnforcedAction",
    "JudgeResult",
    "LLMJudgeFn",
    "SOAREvent",
    "SOARPipeline",
    "SOARVerdict",
    "VALID_ACTIONS",
]
