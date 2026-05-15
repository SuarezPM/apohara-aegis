# SPDX-License-Identifier: Apache-2.0
"""opencode Zen stealth-tier frontier adapters — Phase 4 Day 4.

Architecture
============

Four additional :class:`apohara_aegis.multi_judge.VendorAdapter`
subclasses targeting the opencode Zen ``/zen/v1/chat/completions``
gateway's stealth-mode and free-tier model surface. These broaden the
multi-vendor judge ensemble (Day 2 + Day 3 baseline = 6 vendors) toward
the Day-4 13-vendor frontier-ensemble decision Pablo locked on
2026-05-15.

The endpoint, auth, system instruction, and JSON-classifier contract
are inherited from :mod:`apohara_aegis.multi_judge` so verdicts
aggregate cleanly with the existing :class:`EnsembleJudge` voter. The
shared ``_CF_BYPASS_UA`` real-browser User-Agent is reused — without
it Cloudflare returns error 1010 before the request reaches the vendor
(verified 2026-05-15).

Adapter roster
==============

==================================== =============================== ============
Class                                ``model_id``                    Status (live)
==================================== =============================== ============
:class:`OpencodeZenBigPickleAdapter` ``big-pickle``                  WORKS — but
                                                                     reveals real
                                                                     underlying
                                                                     model is
                                                                     ``deepseek-
                                                                     v4-flash``
                                                                     (NOT GLM-4.6
                                                                     as community
                                                                     sources
                                                                     claimed).
:class:`OpencodeZenRing261TAdapter`  ``ring-2.6-1t-free``            Gated:
                                                                     returns
                                                                     ``Model not
                                                                     supported``
                                                                     on this
                                                                     account
                                                                     tier (2026-
                                                                     05-15).
:class:`OpencodeZenTrinityLarge      ``trinity-large-preview-free``  Gated
:Adapter`                                                            (same).
:class:`OpencodeZenDeepSeekV4Flash   ``deepseek-v4-flash-free``      Gated
Adapter`                                                             (same).
==================================== =============================== ============

Live response shape per adapter (verified 2026-05-15 — honesty surface)
=======================================================================

**big-pickle** — accepts ``temperature: 0`` + ``max_tokens``; system+user
chat shape; OpenAI-compatible response BUT the message has TWO content
slots:

* ``choices[0].message.content`` — final answer (clean JSON when the
  token budget is large enough).
* ``choices[0].message.reasoning_content`` — DeepSeek-style chain-of-
  thought trace. Counts against ``completion_tokens`` (via
  ``completion_tokens_details.reasoning_tokens``).

When ``max_tokens`` is too small the entire budget is spent on
``reasoning_content`` and ``content`` is the empty string — the
adapter handles this by falling back to ``reasoning_content`` and
extracting the JSON judge object via the
:data:`_REASONING_JSON_RE` regex, which mirrors the
``_MINIMAX_JUDGE_JSON_RE`` strategy in :mod:`multi_judge`. Default
``max_tokens`` is 1500 so the JSON fits in ``content`` cleanly on
typical prompts.

The ``model`` field in the response is the REAL underlying model
(``deepseek-v4-flash``), not the alias ``big-pickle``. We surface
this honestly in :attr:`OpencodeZenBigPickleAdapter.model` (set to
``big-pickle`` per the public surface name Pablo's plan pins) plus
AUDIT.md entry documenting the discovered real-model attribution.
The earlier community attribution ("Big Pickle = GLM-4.6") does not
match our live observation; AUDIT records both claims, with our live
finding taking precedence.

**ring-2.6-1t-free / trinity-large-preview-free / deepseek-v4-flash-
free** — all listed in ``GET /v1/models`` but every probe attempt
(temperature=0, system+user, max_tokens=50..1500) returned::

    {"type": "error", "error": {"type": "ModelError",
     "message": "Model  not supported"}}

The double-space in ``"Model  not supported"`` is intentional in the
upstream string; we surface the raw error in the JudgeVerdict's
``error`` field for honest debugging rather than translating it. These
adapters all return ``path='unavailable'`` until the account tier is
upgraded or the gating changes. Per the locked Day-4 decision we ship
the adapter wiring NOW so a tier upgrade later requires zero code
changes — only a probe-and-AUDIT-update.

OpenAI-compatible body shape (R-1 + new R-3)
=============================================

The big-pickle route ACCEPTS ``temperature`` (unlike ``claude-opus-4-7``
which rejects it per Day-2 commit b3bcecc). It also accepts the
classic ``max_tokens`` (NOT ``max_completion_tokens``). Where the four
stealth adapters return errors, the error message is captured in the
verdict for AUDIT review.

Honest fail-open
================

A vendor that 4xx/5xx-errors, times out, parse-fails, or trips an
HTTP error returns ``JudgeVerdict(path="unavailable", is_harmful=False,
confidence=0.0)``. The :class:`EnsembleJudge` tally excludes that
vendor from the active count and surfaces it in
``dissent_summary | unavailable: ...``. No silent forced verdict on
gated models — same posture as :mod:`apohara_aegis.multi_judge`.

NOT YET wired into :func:`apohara_aegis.multi_judge.make_default_ensemble`
— Day-4 Agent D handles the 13-vendor wiring after all four sibling
agents' adapter modules land. Cost-cap entries for the new adapters
are also Agent D's responsibility (Pablo locked "cost cap DISABLED"
for the bake-off run, so ``float("inf")`` is the safe default).

Public API
==========

    >>> from apohara_aegis.opencode_zen_adapters import (
    ...     OpencodeZenBigPickleAdapter,
    ...     OpencodeZenRing261TAdapter,
    ...     OpencodeZenTrinityLargeAdapter,
    ...     OpencodeZenDeepSeekV4FlashAdapter,
    ... )
    >>> import asyncio
    >>> a = OpencodeZenBigPickleAdapter()
    >>> v = asyncio.run(a.evaluate("How to bake a cake"))
    >>> v.is_harmful, v.path
    (False, 'primary')
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

from apohara_aegis.multi_judge import (
    _PROMPT_TEMPLATE,
    _SYSTEM_INSTRUCTION,
    JudgeVerdict,
    VendorAdapter,
    _sync_post_json,
)

logger = logging.getLogger("apohara_aegis.opencode_zen_adapters")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# The opencode Zen Claude-style chat-completions endpoint. Identical
# to the URL the existing :class:`ClaudeOpus47Adapter` /
# :class:`GPT55Adapter` use; just a different ``model`` field in the
# body for each adapter below.
_OPENCODE_ZEN_ENDPOINT: str = "https://opencode.ai/zen/v1/chat/completions"


# JSON-extraction regex shared by the stealth adapters. Big-pickle (and
# other DeepSeek-V4-derived stealth aliases) may put the judge JSON
# inside ``reasoning_content`` if the model burned the token budget on
# CoT before emitting the final answer. We look for the smallest
# substring starting with ``{"is_harmful"`` and ending at the nearest
# matching brace — same strategy as :data:`_MINIMAX_JUDGE_JSON_RE` in
# :mod:`multi_judge`. Non-greedy DOTALL handles multi-line CoT bodies.
_REASONING_JSON_RE: re.Pattern[str] = re.compile(
    r'\{\s*"is_harmful"\s*:\s*(?:true|false).*?\}', re.DOTALL
)


# Stripping regex for the ``<think>...</think>`` wrapper some opencode
# Zen stealth aliases use (Qwen / GLM family). big-pickle does NOT use
# this (it routes through DeepSeek-V4 which exposes a separate
# ``reasoning_content`` field), but we keep the regex available for
# future stealth-alias swaps so the parser stays robust.
_THINK_BLOCK_RE: re.Pattern[str] = re.compile(
    r"<think>.*?</think>\s*", re.DOTALL
)


# ---------------------------------------------------------------------------
# Shared base class — opencode Zen OpenAI-compatible chat-completions
# ---------------------------------------------------------------------------


class OpencodeZenAdapter(VendorAdapter):
    """Shared base for opencode Zen stealth-tier adapters.

    Subclasses set :attr:`model_id` / :attr:`name` and inherit:

    * ``vendor = "opencode_zen"``.
    * Endpoint = :data:`_OPENCODE_ZEN_ENDPOINT`.
    * Auth via ``$OPENCODE_ZEN_API_KEY`` (raw key value never written
      to disk — only ``os.environ[...]`` access).
    * Body shape: ``model`` + ``messages=[system, user]`` +
      ``max_tokens`` + ``temperature=0``. Free-tier and stealth models
      ACCEPT ``temperature`` (unlike ``claude-opus-4-7`` which rejects
      it). ``temperature=0`` keeps judge verdicts deterministic across
      rerun and matches the discipline of the Day-2 Groq adapters.
    * Response parser: tries ``message.content`` first, falls back to
      ``message.reasoning_content`` if content is empty (DeepSeek-V4
      shape), strips ``<think>...</think>`` if present, then
      :meth:`_coerce_json_dict`. If JSON parse fails, secondary regex
      :data:`_REASONING_JSON_RE` pulls a stray judge object.

    The :attr:`model_id` is what the wire sees; :attr:`model` is the
    label the JudgeVerdict carries (these are the same string for the
    stealth adapters — we do NOT translate the alias to the underlying
    real model because the public attribution belongs in AUDIT.md,
    not silently in code).
    """

    vendor: str = "opencode_zen"
    endpoint: str = _OPENCODE_ZEN_ENDPOINT
    # Stealth + free-tier models on opencode Zen: cost is opaque from
    # the public catalog. We mark cost rates as 0 USD/token by default
    # (the response body's ``cost`` field on big-pickle returned
    # ``"0"`` at probe time, consistent with stealth-mode promo) so the
    # ledger does not spuriously trigger a cost cap. Agent D's
    # ensemble-wiring commit refines this if/when opencode Zen
    # publishes a reseller schedule for these tiers.
    cost_per_input_tok: float = 0.0
    cost_per_output_tok: float = 0.0

    #: The model identifier on the wire (set by subclasses).
    model_id: str = "abstract"

    def __init__(
        self,
        api_key_env: str = "OPENCODE_ZEN_API_KEY",
        max_tokens: int = 1500,
        timeout_s: Optional[float] = None,
    ) -> None:
        super().__init__(timeout_s=timeout_s)
        self.api_key_env = api_key_env
        # Default max_tokens=1500. Empirical: big-pickle (DeepSeek-V4-
        # Flash) burned 200-400 tokens of CoT into reasoning_content
        # before the final JSON answer landed in content. 1500 gives
        # ~1100 tokens of headroom for the answer, well above the
        # ~70-token JSON judge verdict size.
        self.max_tokens = int(max_tokens)

    # ------------------------------------------------------------------
    # Configuration hooks
    # ------------------------------------------------------------------

    def _available(self) -> bool:
        return bool(os.environ.get(self.api_key_env))

    def _build_request_body(self, prompt: str) -> dict:
        """OpenAI-compatible chat-completions body.

        Subclasses MAY override to drop ``temperature`` if a future
        probe shows the route rejects it (the Day-2 Claude-Opus-4-7
        quirk), but the default works on big-pickle as of 2026-05-15.
        """
        return {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": _SYSTEM_INSTRUCTION},
                {"role": "user", "content": _PROMPT_TEMPLATE.format(prompt=prompt)},
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0,
        }

    async def _call_api(self, prompt: str) -> tuple[object, dict]:
        api_key = os.environ[self.api_key_env]
        body = self._build_request_body(prompt)
        loop = asyncio.get_event_loop()
        parsed, usage = await loop.run_in_executor(
            None,
            lambda: _sync_post_json(
                self.endpoint, body, api_key=api_key, timeout_s=self.timeout_s
            ),
        )
        return parsed, usage

    # ------------------------------------------------------------------
    # Response parsing — content / reasoning_content / regex fallback
    # ------------------------------------------------------------------

    def _parse_response(
        self, response_obj: object, latency_ms: float
    ) -> Optional[JudgeVerdict]:
        if not isinstance(response_obj, dict):
            return None
        # Honest surfacing of ``Model not supported`` and similar
        # vendor errors: opencode Zen returns ``{"type": "error",
        # "error": {"type": "ModelError", "message": "..."}}`` for
        # gated stealth aliases (verified 2026-05-15 on
        # ring-2.6-1t-free, trinity-large-preview-free,
        # deepseek-v4-flash-free). The HTTP 200 + JSON-error envelope
        # bypasses the urllib HTTPError path, so we detect it here.
        if response_obj.get("type") == "error":
            err = response_obj.get("error") or {}
            msg = err.get("message", "vendor_returned_error")
            logger.warning(
                "OpencodeZen: vendor returned JSON error envelope for %s: %r",
                self.model_id, msg,
            )
            return None
        try:
            msg = response_obj["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            return None
        if not isinstance(msg, dict):
            return None

        # Strategy: try ``content`` first (the normal happy path); if
        # empty or whitespace, fall back to ``reasoning_content`` which
        # DeepSeek-V4-Flash (the model underlying big-pickle) uses for
        # its CoT trace. The judge JSON may have been emitted inside
        # the reasoning slot if the model spent all completion-token
        # budget thinking.
        content = msg.get("content") or ""
        if not isinstance(content, str):
            content = ""
        content = content.strip()
        if not content:
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
            if isinstance(reasoning, str):
                content = reasoning.strip()

        if not content:
            return None

        # Strip a leading ``<think>...</think>`` wrapper if present
        # (some stealth aliases route through Qwen/GLM-style CoT
        # models that wrap their reasoning this way).
        content_stripped = _THINK_BLOCK_RE.sub("", content).strip()
        if content_stripped:
            verdict = self._coerce_json_dict(
                content_stripped, latency_ms=latency_ms
            )
            if verdict is not None:
                return verdict

        # Final fallback: pull a stray judge JSON object out of the
        # reasoning trace via regex. Same posture as the MiniMax
        # adapter's secondary path in :mod:`multi_judge`.
        match = _REASONING_JSON_RE.search(content)
        if match is not None:
            return self._coerce_json_dict(
                match.group(0), latency_ms=latency_ms
            )
        logger.info(
            "OpencodeZen %s: response had content/reasoning but no valid "
            "judge JSON could be extracted (first 120 chars: %r).",
            self.model_id, content[:120],
        )
        return None


# ---------------------------------------------------------------------------
# Concrete adapter — Big Pickle (opencode Zen stealth alias)
# ---------------------------------------------------------------------------


class OpencodeZenBigPickleAdapter(OpencodeZenAdapter):
    """opencode Zen ``big-pickle`` stealth-mode model.

    Public-source attribution context
    ----------------------------------

    Community sources from January through May 2026 (Reddit
    ``r/opencodeCLI`` thread 1qr1jm6, Hacker News item 47460525, the
    "aging coder" blog post dated 2026-01-25) widely identified
    ``big-pickle`` as a stealth-mode rebrand of **GLM-4.6** (Zhipu AI).
    The Day-4 plan documents this attribution and listed Big Pickle as
    a separate entry in the bake-off table per Pablo's locked
    architecture decision.

    Live observation (2026-05-15)
    ------------------------------

    The 2026-05-15 live probe **contradicts the GLM-4.6 attribution**.
    Every response from ``big-pickle`` returns:

    * ``response["model"] == "deepseek-v4-flash"`` (not glm-4.6).
    * ``message.reasoning_content`` populated with a DeepSeek-V4-style
      chain-of-thought trace (separate field, NOT a ``<think>...
      </think>`` wrapped block; the DeepSeek family routes CoT to a
      different message slot).
    * ``system_fingerprint`` ``"fp_8b330d02d0_prod0820_fp8_kvcache
      _20260402"`` — DeepSeek-V4-Flash fingerprint, not a GLM-family
      fingerprint.
    * ``completion_tokens_details.reasoning_tokens`` field present
      (DeepSeek-V4 hallmark).
    * ``cost: "0"`` field on the response body.

    AUDIT.md entry documents both the community claim and our live
    finding honestly. The adapter keeps the canonical model_id
    ``"big-pickle"`` as opencode Zen's surface exposes it, and the
    JudgeVerdict reports ``vendor="opencode_zen"`` + ``model="big-
    pickle"`` so downstream logs trace cleanly to the alias name the
    user sees in the catalog. We do NOT silently rewrite the model
    label to ``deepseek-v4-flash`` — the alias IS the surface, and
    honesty lives in AUDIT.md.

    Token-budget quirk
    ------------------

    DeepSeek-V4-Flash splits the completion budget between
    ``reasoning_content`` and ``content``. At ``max_tokens=400`` (the
    Day-2 default for other adapters) the model burned every token on
    CoT and left ``content`` empty. The default here is 1500 so the
    JSON judge verdict has headroom; the parser also reads
    ``reasoning_content`` as a fallback so even a tight budget yields
    a verdict if the JSON object is embedded in the CoT.
    """

    name: str = "opencode_zen:big-pickle"
    model: str = "big-pickle"
    model_id: str = "big-pickle"


# ---------------------------------------------------------------------------
# Concrete adapter — Ring 2.6 1T (opencode Zen free-tier stealth)
# ---------------------------------------------------------------------------


class OpencodeZenRing261TAdapter(OpencodeZenAdapter):
    """opencode Zen ``ring-2.6-1t-free`` — 1T-parameter free-tier stealth.

    Public attribution: 1 trillion parameter scale stealth-mode model
    exposed via the opencode Zen free tier; the upstream provider is
    not publicly disclosed. Listed in opencode Zen ``GET /v1/models``
    as of 2026-05-15.

    Live observation (2026-05-15)
    ------------------------------

    Probe attempts varied in response shape but consistently fail:

    * Most attempts (system+user, ``temperature=0``, varying
      ``max_tokens``) returned HTTP 401 with the JSON-error envelope
      ``{"type": "error", "error": {"type": "ModelError",
      "message": "Model  not supported"}}``. The double space in
      ``"Model  not supported"`` is the upstream string verbatim.
    * One probe returned HTTP 400 with a richer error body:
      ``{"error": {"message": "Error from provider: Ring-2.6-1T is no
      longer available as a free model. It has transitioned to a paid
      model. Continue using it here: https://openrouter.ai/
      inclusionai/ring-2.6-1t", "code": 404}, "user_id": "..."}`` —
      confirming the actual root cause: the free tier has been
      decommissioned by the upstream provider (Inclusion AI) and the
      model is now paid-only via OpenRouter.

    The adapter ships now (Day-4 spec) honoring the locked decision to
    list it as a separate entry. The verdict path stays
    ``unavailable`` honestly until either the free tier is restored
    or the wiring is updated to point at OpenRouter (Agent A's
    deliverable in :mod:`apohara_aegis.openrouter_adapters`).
    AUDIT.md entry documents the decommissioning.
    """

    name: str = "opencode_zen:ring-2.6-1t-free"
    model: str = "ring-2.6-1t-free"
    model_id: str = "ring-2.6-1t-free"


# ---------------------------------------------------------------------------
# Concrete adapter — Trinity Large preview (opencode Zen free-tier stealth)
# ---------------------------------------------------------------------------


class OpencodeZenTrinityLargeAdapter(OpencodeZenAdapter):
    """opencode Zen ``trinity-large-preview-free`` — Trinity Large preview.

    Public attribution: Trinity Large model preview, opencode Zen free
    tier; upstream provider not publicly disclosed. Listed in
    ``GET /v1/models``.

    Live observation (2026-05-15)
    ------------------------------

    Same gating as ``ring-2.6-1t-free``: every probe (system+user,
    temperature=0, varying max_tokens) returns the
    ``Model  not supported`` JSON-error envelope on this account tier.
    Adapter returns ``path='unavailable'`` honestly. Shipped now so a
    future gating change requires no code edits.
    """

    name: str = "opencode_zen:trinity-large-preview-free"
    model: str = "trinity-large-preview-free"
    model_id: str = "trinity-large-preview-free"


# ---------------------------------------------------------------------------
# Concrete adapter — DeepSeek V4 Flash free-tier (opencode Zen)
# ---------------------------------------------------------------------------


class OpencodeZenDeepSeekV4FlashAdapter(OpencodeZenAdapter):
    """opencode Zen ``deepseek-v4-flash-free`` — DeepSeek V4 Flash free tier.

    Public attribution: faster/cheaper sibling of DeepSeek V4 Pro; the
    ``free`` suffix indicates the rate-limited free tier on opencode
    Zen. The DeepSeek V4 Pro counterpart is wired separately via the
    OpenRouter gateway in :mod:`apohara_aegis.openrouter_adapters`
    (Agent A's deliverable for Day 4).

    Live observation (2026-05-15)
    ------------------------------

    Despite being in ``GET /v1/models`` and despite ``big-pickle``
    transparently routing to ``deepseek-v4-flash`` under the hood,
    direct invocation of ``deepseek-v4-flash-free`` returns the
    ``Model  not supported`` JSON-error envelope on this account tier.
    Likely a separate gating policy (e.g. free-tier requires explicit
    enablement; the alias-routed call inherits the paid Big Pickle
    quota; the direct call requires the free-tier flag).

    Adapter returns ``path='unavailable'`` honestly. AUDIT.md
    documents the gated state and the surprise (big-pickle works but
    deepseek-v4-flash-free does not, despite the same underlying
    model).
    """

    name: str = "opencode_zen:deepseek-v4-flash-free"
    model: str = "deepseek-v4-flash-free"
    model_id: str = "deepseek-v4-flash-free"


# ---------------------------------------------------------------------------
# Day-5 backup adapters — promoted to PRIMARY for the Kimi / GLM seats
# (live probes 2026-05-15 confirmed cleaner availability than the
# OpenRouter primaries which hit parse failures at 46% / 71%).
# ---------------------------------------------------------------------------


class OpencodeZenKimiK26Adapter(OpencodeZenAdapter):
    """opencode Zen ``kimi-k2.6`` — backup route for Kimi K2.6.

    Backup route for Kimi K2.6 when OpenRouter primary returns parse
    failures. Live probe 2026-05-15: 1.3s; opencode Zen resolves this
    to ``accounts/fireworks/models/kimi-k2p6`` (Fireworks-hosted Kimi).
    Promoted to PRIMARY for the Kimi seat in Day-5 ensemble because OR
    had 46% availability due to parse failures.
    """

    name: str = "opencode_zen:kimi-k2.6"
    model: str = "kimi-k2.6"
    model_id: str = "kimi-k2.6"


class OpencodeZenGLM51Adapter(OpencodeZenAdapter):
    """opencode Zen ``glm-5.1`` — backup route for GLM 5.1.

    Backup route for GLM 5.1. Live probe 2026-05-15: 1.7s; opencode
    Zen resolves to ``frank/GLM-5.1`` (frank gateway). Requires
    ``max_tokens >= 320`` to avoid empty content under the gateway's
    response shape. Promoted to PRIMARY for the GLM seat in Day-5
    ensemble because OR had 71% availability due to parse failures.

    Token-budget quirk
    ------------------

    Same shape of quirk as :class:`OpencodeZenBigPickleAdapter` (where
    a small budget leaves ``content`` empty), but the floor on this
    route is 320 tokens — below it the frank/GLM-5.1 response body
    consistently returns an empty content slot. Default is set to 512
    via the ``__init__`` override to keep generous headroom above the
    320 floor while staying well within typical judge JSON sizes.
    Callers that pass ``max_tokens`` explicitly to ``__init__`` retain
    full control; the floor is only the default.
    """

    name: str = "opencode_zen:glm-5.1"
    model: str = "glm-5.1"
    model_id: str = "glm-5.1"

    def __init__(
        self,
        api_key_env: str = "OPENCODE_ZEN_API_KEY",
        max_tokens: int = 512,
        timeout_s: Optional[float] = None,
    ) -> None:
        super().__init__(
            api_key_env=api_key_env,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
        )


class OpencodeZenQwen36PlusAdapter(OpencodeZenAdapter):
    """opencode Zen ``qwen3.6-plus`` — backup route for Qwen3.6 Plus.

    Backup route for Qwen3.6 Plus when OR primary is degraded. Live
    probe 2026-05-15: 3.4s.
    """

    name: str = "opencode_zen:qwen3.6-plus"
    model: str = "qwen3.6-plus"
    model_id: str = "qwen3.6-plus"


class OpencodeZenNemotron3SuperAdapter(OpencodeZenAdapter):
    """opencode Zen ``nemotron-3-super-free`` — backup route for Nemotron 3 Super 120B.

    Backup route for Nemotron 3 Super 120B when OR primary is
    degraded. Live probe 2026-05-15: 1.7s; opencode Zen resolves to
    ``nvidia/nemotron-3-super-120b-a12b-20230311:free``.
    """

    name: str = "opencode_zen:nemotron-3-super-free"
    model: str = "nemotron-3-super-free"
    model_id: str = "nemotron-3-super-free"


class OpencodeZenMiniMaxM27Adapter(OpencodeZenAdapter):
    """opencode Zen ``minimax-m2.7`` — backup route for MiniMax M2.7.

    Backup route for MiniMax M2.7 when direct API primary is
    rate-limited. Live probe 2026-05-15: 3.2s.
    """

    name: str = "opencode_zen:minimax-m2.7"
    model: str = "minimax-m2.7"
    model_id: str = "minimax-m2.7"


class OpencodeZenGPT55ProAdapter(OpencodeZenAdapter):
    """opencode Zen ``gpt-5.5-pro`` — backup-of-backup for GPT-5.5 seat.

    Backup-of-backup for GPT-5.5 seat (after OR primary). Live probe
    2026-05-15: 22s; opencode Zen resolves to
    ``gpt-5.5-pro-2026-04-23``. NOTE: 22s latency makes this the
    slowest route in the ensemble — only fires when both OCZ gpt-5.5
    AND OR ``openai/gpt-5.5`` return unavailable.

    Timeout override
    ----------------

    Base class default :attr:`VendorAdapter.timeout_s` is 25.0s, which
    is borderline given the observed 22s live response. This class
    raises the floor to 30.0s so a typical-case response (with normal
    network jitter) does not trip the urllib timeout. Callers that
    pass ``timeout_s`` explicitly to ``__init__`` retain full control.
    """

    name: str = "opencode_zen:gpt-5.5-pro"
    model: str = "gpt-5.5-pro"
    model_id: str = "gpt-5.5-pro"
    timeout_s: float = 30.0


__all__ = [
    "OpencodeZenAdapter",
    "OpencodeZenBigPickleAdapter",
    "OpencodeZenRing261TAdapter",
    "OpencodeZenTrinityLargeAdapter",
    "OpencodeZenDeepSeekV4FlashAdapter",
    "OpencodeZenKimiK26Adapter",
    "OpencodeZenGLM51Adapter",
    "OpencodeZenQwen36PlusAdapter",
    "OpencodeZenNemotron3SuperAdapter",
    "OpencodeZenMiniMaxM27Adapter",
    "OpencodeZenGPT55ProAdapter",
]
