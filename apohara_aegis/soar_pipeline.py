# SPDX-License-Identifier: Apache-2.0
"""
4-stage SOAR pipeline: DETECT -> JUDGE -> ENFORCE -> FORENSICS.

Orchestrates the full incident response lifecycle for agent misbehavior
events. Each stage is independently testable and composable.

Stage contract
==============

* **DETECT** -- normalize an arbitrary inbound event (HTTP / SSE / CLI
  dict) into a :class:`SOAREvent` dataclass with stable field shapes.
* **JUDGE**  -- evaluate both layers (Deterministic Judge Layer + LLM
  ensemble) in parallel via :func:`verdict_combine.combine` and package
  the dual-layer result in a :class:`JudgeResult`. The canonical
  :class:`djl.DjlEngine` (62 rules, US-72) is the deterministic layer;
  an optional ``judge_llm_fn`` constructor hook supplies the LLM
  ensemble layer. When the LLM hook is absent the pipeline still runs
  -- it just degrades to djl-only with the combined decision reducing
  to the DJL decision.
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

from .djl import DjlEngine
from .verdict_combine import CombinedVerdict, LlmEnsembleVerdict, combine

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
    """Output of the JUDGE stage.

    US-77 (2026-05-18) wires the canonical dual-layer
    :func:`verdict_combine.combine` -- both per-layer verdicts are now
    available on :attr:`combined_verdict` for audit-chain forensics and
    the legacy :attr:`djl_verdict` / :attr:`llm_verdict` fields are
    projected from it for backward compatibility:

    * ``djl_verdict``     -- legacy-shape projection of the canonical
                             :class:`djl.DjlVerdict` produced by the
                             combine call (see ``_canonical_djl_to_legacy``).
    * ``llm_verdict``     -- ``None`` in djl-only mode; otherwise a
                             dict snapshot of the LLM ensemble verdict
                             for HMAC-chain serialisation.
    * ``combined``        -- safe-merged legacy :class:`DJLVerdict`
                             reflecting the dual-layer decision.
                             Identical to :attr:`djl_verdict` in
                             djl-only mode; differs when the LLM peer
                             vetoes / demotes.
    * ``combined_verdict`` -- canonical :class:`CombinedVerdict`
                              (US-77) carrying both per-layer verdicts
                              with their full provenance (vendor_votes,
                              matched_rules, per-layer latency).
                              Read this in new code; the three legacy
                              fields are kept for pre-US-77 callers.
    """

    djl_verdict: DJLVerdict
    llm_verdict: Optional[dict[str, Any]] = None
    combined: Optional[DJLVerdict] = None
    combined_verdict: Optional[CombinedVerdict] = None


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
# DEPRECATED inline DJL rule pack
# ---------------------------------------------------------------------------
#
# DEPRECATED (US-77, 2026-05-18): the canonical Zero-LLM Deterministic
# Judge now lives in :mod:`apohara_aegis.djl` (62 rules, US-72) and is
# invoked via :func:`verdict_combine.combine` (US-77) inside
# :meth:`SOARPipeline.judge`. This 4-rule inline pack is preserved
# (a) so this module remains self-contained for unit tests that need a
# zero-dependency rule set, and (b) so historic pre-US-77 behaviour can
# be reproduced via :func:`_deprecated_inline_djl` for regression
# analysis. New code MUST NOT call :func:`_deprecated_inline_djl`;
# call :class:`djl.DjlEngine.evaluate` (or the module-level
# :func:`djl.evaluate` singleton) instead.

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


def _deprecated_inline_djl(prompt: str, context: dict[str, Any]) -> DJLVerdict:
    """DEPRECATED -- pre-US-77 inline DJL evaluation.

    .. deprecated:: US-77 (2026-05-18)
        Use :class:`apohara_aegis.djl.DjlEngine` via
        :func:`apohara_aegis.verdict_combine.combine` instead. This
        function is kept only for module self-containment and
        pre-US-77 behavioural regression studies.

    Order of evaluation:
        1. OWASP regex pack (catches prompt-injection family).
        2. Supplementary :data:`_DJL_RULES` (SQLi, destructive shell,
           PII, financial transfer).

    Falls through to ``ALLOW`` when no rule fires. ``context`` is
    accepted for forward compatibility; the shim does not consult it.
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
# Canonical -> legacy adapter
# ---------------------------------------------------------------------------
#
# US-77 swaps the inline 4-rule DJL for the canonical 62-rule
# :class:`djl.DjlEngine`. The legacy :class:`DJLVerdict` shape is kept
# on :class:`JudgeResult` so :meth:`SOARPipeline.enforce` continues to
# read ``rule``, ``reason``, ``confidence`` -- the adapter below
# projects a canonical :class:`djl.DjlVerdict` (decision +
# matched_rules + latency_ms) onto the legacy shape using a stable
# rule-id prefix mapping.

# Canonical DJL rule-id prefix -> legacy rule name.
# Prefixes are evaluated left-to-right against the first matched rule;
# the longest match wins so MIS-001/MIS-002 can route to
# "destructive_shell" before the catch-all "MIS-".
_LEGACY_RULE_MAP: tuple[tuple[str, str], ...] = (
    ("DJL-MIS-001", "destructive_shell"),
    ("DJL-MIS-002", "destructive_shell"),
    ("DJL-MIS-007", "destructive_shell"),  # fork bomb
    ("DJL-MIS-008", "destructive_shell"),  # reverse shell
    ("DJL-MIS-003", "unauthorized_financial_transfer"),
    ("DJL-MIS-",    "tool_misuse"),
    ("DJL-SQLI-",   "sql_injection"),
    ("DJL-XSS-",    "xss"),
    ("DJL-PII-",    "pii_leak_attempt"),
    ("DJL-EXF-",    "exfiltration"),
    ("DJL-POL-",    "policy_violation"),
)


def _canonical_djl_to_legacy(
    canonical: "DjlVerdict_T",  # forward ref; real type is djl.DjlVerdict
    *,
    prompt: str = "",
) -> DJLVerdict:
    """Project a canonical :class:`djl.DjlVerdict` onto the legacy shape.

    * ``rule``       -- prefix-mapped from the first ``matched_rules``
                        entry, or ``"empty_input"`` for the empty
                        prompt sentinel, or ``""`` when nothing
                        matched, or ``owasp:<id>`` for any
                        ``DJL-PI-*`` match (preserves the pre-US-77
                        ``owasp:`` audit breadcrumb).
    * ``reason``     -- ``"<rule_id> matched"`` or ``"no rule fired"``.
    * ``confidence`` -- 1.0 for deterministic matches (regex is
                        boolean), 0.85 for the soft-block branches
                        (PII / financial transfer) which the pre-US-77
                        policy routes to REVIEW rather than BLOCK
                        (a PII *mention* or financial-transfer
                        *instruction* is not the same as an
                        exfiltration directive; the LLM ensemble is
                        the right peer to escalate true intent).
    """
    matched = canonical.matched_rules

    # Empty-input sentinel (pre-US-77 backward compatibility)
    if not prompt and not matched:
        return DJLVerdict(
            decision=canonical.decision,
            rule="empty_input",
            reason="empty prompt -- no rule applicable",
            confidence=1.0,
            latency_ms=canonical.latency_ms,
        )

    if not matched:
        return DJLVerdict(
            decision=canonical.decision,
            rule="",
            reason="no rule fired",
            confidence=1.0,
            latency_ms=canonical.latency_ms,
        )

    first_id = matched[0]

    # Prompt-injection family keeps the "owasp:" prefix breadcrumb
    if first_id.startswith("DJL-PI-"):
        legacy_rule = f"owasp:{first_id}"
        return DJLVerdict(
            decision=canonical.decision,
            rule=legacy_rule,
            reason=f"OWASP pattern matched: {first_id}",
            confidence=1.0,
            latency_ms=canonical.latency_ms,
        )

    # Walk longest-prefix-first
    legacy_rule = ""
    for prefix, name in _LEGACY_RULE_MAP:
        if first_id.startswith(prefix):
            legacy_rule = name
            break
    if not legacy_rule:
        legacy_rule = first_id  # unknown family -- pass through raw id

    # Soft-block: keep pre-US-77 REVIEW routing for PII + financial transfer
    # matches. These are matches where the prompt MENTIONS sensitive
    # categories but the intent (audit vs exfil; payroll vs theft) is
    # genuinely ambiguous; the LLM ensemble peer is responsible for
    # escalating to a hard BLOCK when adversarial intent is detected.
    if legacy_rule in ("pii_leak_attempt", "unauthorized_financial_transfer"):
        confidence = 0.85
        decision = "REVIEW"
    else:
        confidence = 1.0
        decision = canonical.decision

    return DJLVerdict(
        decision=decision,
        rule=legacy_rule,
        reason=f"{first_id} matched",
        confidence=confidence,
        latency_ms=canonical.latency_ms,
    )


# Forward-ref alias so the function annotation does not need to import
# the canonical DjlVerdict eagerly (it does, but the alias keeps the
# adapter signature readable).
from .djl import DjlVerdict as DjlVerdict_T  # noqa: E402


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


# Type alias for the optional LLM ensemble hook (US-77 plugs it in).
#
# Pre-US-77 contract:  ``LLMJudgeFn = Callable[[SOAREvent],
#                                              Awaitable[dict[str, Any]]]``
# US-77 forward path:  the canonical hook is
#                      ``Callable[[str, dict | None],
#                                 Awaitable[LlmEnsembleVerdict]]``
#                      and is wired through ``verdict_combine.combine``.
# Both shapes are supported on the constructor for backward
# compatibility; the new shape (``LlmEnsembleFn``) is preferred.
LLMJudgeFn = Callable[[SOAREvent], Awaitable[dict[str, Any]]]
LlmEnsembleFn = Callable[[str, Optional[dict]], Awaitable[LlmEnsembleVerdict]]


class SOARPipeline:
    """4-stage incident response pipeline: DETECT -> JUDGE -> ENFORCE -> FORENSICS.

    Constructor parameters are kept narrow on purpose; US-77 wires the
    canonical 62-rule :class:`djl.DjlEngine` + the 12-vendor LLM
    ensemble through :func:`verdict_combine.combine`.

    Args:
        ledger_path: optional ``Path`` to persist the HMAC chain. ``None``
            keeps the chain in memory (test-friendly default).
        hmac_key: optional 32-byte HMAC key; otherwise reads
            ``APOHARA_LEDGER_HMAC_KEY`` env var, finally falls back to
            an ephemeral key with a ``RuntimeWarning``.
        judge_llm_fn: pre-US-77 LLM judge hook -- ``Callable[[SOAREvent],
            Awaitable[dict[str, Any]]]``. Preserved for backward
            compatibility; when set, the returned dict is recorded on
            :attr:`JudgeResult.llm_verdict` for forensics, but the
            combined decision is djl-only (because the dict shape does
            not carry per-vendor votes the safe-merge policy needs).
        llm_ensemble_fn: US-77 canonical LLM ensemble hook --
            ``Callable[[str, dict | None],
            Awaitable[LlmEnsembleVerdict]]``. When supplied this is run
            in parallel with DJL via :func:`verdict_combine.combine` and
            the dual-layer safe-merge policy decides the combined
            verdict.
        djl_engine: optional pre-built :class:`djl.DjlEngine`; defaults
            to a fresh engine with the canonical 62-rule corpus.
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
        llm_ensemble_fn: Optional[LlmEnsembleFn] = None,
        djl_engine: Optional[DjlEngine] = None,
        prometheus_counter: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._chain = _HMACChain(ledger_path=ledger_path, hmac_key=hmac_key)
        self._judge_llm_fn = judge_llm_fn
        self._llm_ensemble_fn = llm_ensemble_fn
        self._djl_engine = djl_engine if djl_engine is not None else DjlEngine()
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
        """Run DJL + LLM ensemble in parallel via :func:`verdict_combine.combine`.

        US-77 (2026-05-18) replaces the pre-US-77 single-thread DJL
        shim with the canonical dual-layer combine: the 62-rule
        :class:`djl.DjlEngine` and (when configured) the 12-vendor
        LLM ensemble fire in parallel and the safe-merge policy in
        :func:`verdict_combine.combine` decides the combined verdict.

        Backward compatibility (pre-US-77 ``judge_llm_fn`` shape):
        when the constructor was given the old
        ``Callable[[SOAREvent], Awaitable[dict]]`` hook instead of the
        new ``LlmEnsembleFn``, the dict result is recorded on
        :attr:`JudgeResult.llm_verdict` for forensics but does NOT
        participate in the safe-merge (the dict shape lacks the
        ``vendor_votes`` field). The combined decision in that path
        reduces to djl-only.

        Fail-open guarantee: if the LLM branch raises, the DJL branch
        result is preserved -- a broken vendor MUST NOT undo a DJL
        block.
        """
        # Canonical dual-layer combine (US-77)
        try:
            combined_verdict = await combine(
                prompt=detected.prompt,
                context=detected.context,
                djl_engine=self._djl_engine,
                llm_ensemble_fn=self._llm_ensemble_fn,
            )
        except Exception as exc:  # noqa: BLE001
            # Fail-open: if combine() itself blows up, fall back to a
            # raw DJL call so we still return a verdict (and an audit
            # record).
            logger.warning("JUDGE: combine() raised (%s); falling back to djl-only", exc)
            raw_djl = self._djl_engine.evaluate(detected.prompt, detected.context)
            combined_verdict = CombinedVerdict(
                djl_verdict=raw_djl,
                llm_verdict=None,
                decision=raw_djl.decision,
                decision_reason=f"combine_fallback_{raw_djl.decision.lower()}",
                total_latency_ms=raw_djl.latency_ms,
            )

        # Project canonical -> legacy DJLVerdict for enforce()/forensics()
        legacy_djl = _canonical_djl_to_legacy(
            combined_verdict.djl_verdict,
            prompt=detected.prompt,
        )

        # Build the safe-merged legacy verdict reflecting the dual-layer
        # decision. In djl-only mode combined.decision == djl.decision so
        # this collapses to the same legacy_djl object.
        if combined_verdict.llm_verdict is None:
            combined_legacy = legacy_djl
        else:
            combined_legacy = DJLVerdict(
                decision=combined_verdict.decision,
                rule=legacy_djl.rule,
                reason=combined_verdict.decision_reason,
                confidence=legacy_djl.confidence,
                latency_ms=combined_verdict.total_latency_ms,
            )

        # llm_verdict dict for HMAC-chain serialisation
        llm_dict: Optional[dict[str, Any]] = None
        if combined_verdict.llm_verdict is not None:
            llm_dict = {
                "decision": combined_verdict.llm_verdict.decision,
                "vendor_votes": combined_verdict.llm_verdict.vendor_votes,
                "block_count": combined_verdict.llm_verdict.block_count,
                "review_count": combined_verdict.llm_verdict.review_count,
                "allow_count": combined_verdict.llm_verdict.allow_count,
                "latency_ms": combined_verdict.llm_verdict.latency_ms,
                "layer": combined_verdict.llm_verdict.layer,
            }

        # Pre-US-77 ``judge_llm_fn`` (dict-returning) hook: still honoured
        # for backward compatibility, but only as a forensics recorder.
        if self._judge_llm_fn is not None and llm_dict is None:
            try:
                llm_dict = await self._judge_llm_fn(detected)
            except Exception as exc:  # noqa: BLE001
                logger.warning("JUDGE: legacy judge_llm_fn raised (%s); ignoring", exc)
                llm_dict = {"error": str(exc)[:160]}

        return JudgeResult(
            djl_verdict=legacy_djl,
            llm_verdict=llm_dict,
            combined=combined_legacy,
            combined_verdict=combined_verdict,
        )

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
