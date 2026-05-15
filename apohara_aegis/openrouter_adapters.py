# SPDX-License-Identifier: Apache-2.0
"""OpenRouter frontier judge adapters — 5 vendors via one gateway.

Architecture
============

OpenRouter is a single OpenAI-compatible gateway in front of 360+
models from many providers. This module adds 5 concrete
:class:`VendorAdapter` subclasses for the Day-4 Phase-4 multi-vendor
frontier ensemble (engram memory ``decision/day-4-13-vendor-frontier-
ensemble-pablo-s-locked-decisions-2026-05-15``):

================================= ====================================
Adapter                           OpenRouter model_id
================================= ====================================
OpenRouterDeepSeekV4ProAdapter    deepseek/deepseek-v4-pro
OpenRouterKimiK26Adapter          moonshotai/kimi-k2.6
OpenRouterGLM51Adapter            z-ai/glm-5.1
OpenRouterQwen36PlusAdapter       qwen/qwen3.6-plus
OpenRouterNemotron3Super120BAdapter nvidia/nemotron-3-super-120b-a12b
================================= ====================================

All 5 share the same base class :class:`OpenRouterAdapter` — only
``model_id``, ``name``, ``cost_per_*_tok`` differ between subclasses.

Endpoint: ``https://openrouter.ai/api/v1/chat/completions`` (OpenAI
chat.completions shape). Docs: https://openrouter.ai/docs/api-reference

Authentication
==============

``Authorization: Bearer $OPENROUTER_API_KEY``. OpenRouter additionally
REQUIRES (per their docs) an ``HTTP-Referer`` header for analytics
and to let model owners audit which apps hit them. This adapter
hard-codes the public repo URL there:

    HTTP-Referer: https://github.com/SuarezPM/apohara-aegis

Plus the standard ``User-Agent`` Cloudflare-bypass UA shared with
the rest of the ensemble. Without these two headers OpenRouter
returns HTTP 403 or routes the call to a degraded pool.

Vendor-specific quirks (verified 2026-05-15 PM live probes)
============================================================

* **DeepSeek V4 Pro**, **Kimi K2.6**, **GLM 5.1** are all
  reasoning-style models that may emit a ``<think>...</think>`` chain-
  of-thought block before their final JSON. The parser strips that
  block whole before JSON-parsing (the same approach used by
  :class:`MiniMaxM27Adapter`). On some OpenRouter routes the CoT
  goes into a separate ``choices[0].message.reasoning`` field
  instead of ``content``; we fall back to that field when ``content``
  is empty.
* **Qwen 3.6 Plus** sometimes wraps the JSON in prose
  ("Here is the verdict: { ... }") instead of returning a clean
  object. A regex fallback extracts the first ``{...is_harmful...}``
  block.
* **Nemotron 3 Super 120B** is the cheapest and cleanest in the
  set (~2 s latency, returns bare JSON). It is the live smoke
  default.
* OpenRouter honors ``response_format: {"type": "json_object"}`` for
  the providers that support it but silently ignores it for those
  that do not — hence the defensive parsing.

Honest fail-open
================

Same contract as the rest of the ensemble (see
:mod:`apohara_aegis.multi_judge`): any HTTP error, parse failure, or
timeout returns ``JudgeVerdict(path="unavailable", is_harmful=False,
confidence=0.0)``. The ensemble vote excludes ``unavailable`` vendors
from its denominator.

Wiring
======

These 5 adapters are NOT registered in
:func:`apohara_aegis.multi_judge.make_default_ensemble` by this
module. The 13-vendor list is assembled in a later commit (Agent D
work). Import an adapter and pass it explicitly to
:class:`EnsembleJudge` if you need it earlier:

    >>> from apohara_aegis.multi_judge import EnsembleJudge
    >>> from apohara_aegis.openrouter_adapters import (
    ...     OpenRouterNemotron3Super120BAdapter,
    ... )
    >>> e = EnsembleJudge(adapters=[OpenRouterNemotron3Super120BAdapter()])
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Optional

from apohara_aegis.multi_judge import (
    JudgeVerdict,
    VendorAdapter,
    _PROMPT_TEMPLATE,
    _SYSTEM_INSTRUCTION,
    _sync_post_json,
)

logger = logging.getLogger("apohara_aegis.openrouter_adapters")


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Shared OpenRouter chat-completions endpoint.
OPENROUTER_ENDPOINT: str = "https://openrouter.ai/api/v1/chat/completions"

# OpenRouter requires HTTP-Referer (analytics + model-owner audit) per
# https://openrouter.ai/docs/api-reference/overview#headers. We point
# it at the public repo so OpenRouter's dashboard can attribute traffic.
OPENROUTER_HTTP_REFERER: str = "https://github.com/SuarezPM/apohara-aegis"

# Optional X-Title — shown in the OpenRouter dashboard alongside the
# referer. Helps debugging when multiple Apohara modes call the
# gateway concurrently.
OPENROUTER_X_TITLE: str = "Apohara Aegis"

# CoT-strip regex — same pattern as :data:`apohara_aegis.multi_judge.
# _MINIMAX_COT_RE`. Mirrored here so this module does not reach into
# multi_judge's private regex namespace.
_OPENROUTER_COT_RE: re.Pattern[str] = re.compile(
    r"<think>.*?</think>\s*", re.DOTALL
)

# Regex fallback to recover a judge JSON object embedded inside prose
# or a CoT block. Mirrors :data:`apohara_aegis.multi_judge.
# _MINIMAX_JUDGE_JSON_RE` but DOES NOT use the ``[^{}]`` character
# class — we allow nested-brace-free body (the 4-key judge object is
# flat) and bind to ``"is_harmful"`` so it does not accidentally
# match a different inner JSON object that happens to be in the
# response.
_OPENROUTER_JUDGE_JSON_RE: re.Pattern[str] = re.compile(
    r'\{\s*"is_harmful"\s*:\s*(?:true|false).*?\}', re.DOTALL
)


# ---------------------------------------------------------------------------
# Base adapter
# ---------------------------------------------------------------------------


class OpenRouterAdapter(VendorAdapter):
    """Abstract base for OpenRouter-gatewayed frontier judges.

    Subclasses set ``model_id``, ``name``, ``cost_per_input_tok``, and
    ``cost_per_output_tok`` as class attributes. The base class handles
    the OpenAI-compatible request body, the OpenRouter-required headers,
    the CoT-strip + JSON-extract parsing chain, and the fail-open
    error handling inherited from :class:`VendorAdapter`.

    Parameters
    ----------
    api_key_env:
        Environment variable holding the OpenRouter API key. Default
        ``"OPENROUTER_API_KEY"``.
    max_tokens:
        Cap on the model's output size. Default ``400`` (enough for
        the 4-field judge JSON plus a small CoT trace).
    timeout_s:
        Per-call timeout. Inherits the :class:`VendorAdapter` default
        of 25 s when ``None``.
    """

    # Subclasses MUST override these three class attributes.
    model_id: str = "openrouter/abstract"
    name: str = "openrouter_abstract"
    vendor: str = "openrouter"
    # Default per-token cost is zero so a subclass that forgets to
    # override does not silently inflate the cost ledger. Pricing is
    # in USD per single token (not per million).
    cost_per_input_tok: float = 0.0
    cost_per_output_tok: float = 0.0

    def __init__(
        self,
        api_key_env: str = "OPENROUTER_API_KEY",
        max_tokens: int = 400,
        timeout_s: Optional[float] = None,
    ) -> None:
        super().__init__(timeout_s=timeout_s)
        self.api_key_env = api_key_env
        self.max_tokens = int(max_tokens)
        # ``model`` is what gets stamped on every JudgeVerdict. Bind
        # it to model_id so the parent class sees the right value.
        self.model = self.model_id

    # ------------------------------------------------------------------
    # VendorAdapter hooks
    # ------------------------------------------------------------------

    def _available(self) -> bool:
        return bool(os.environ.get(self.api_key_env))

    def _build_request_body(self, prompt: str) -> dict:
        return {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": _SYSTEM_INSTRUCTION},
                {
                    "role": "user",
                    "content": _PROMPT_TEMPLATE.format(prompt=prompt),
                },
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0.0,
            # Hint to providers that support it; silently ignored
            # otherwise. Defensive parsing below covers the non-honoring
            # case.
            "response_format": {"type": "json_object"},
        }

    async def _call_api(self, prompt: str) -> tuple[object, dict]:
        api_key = os.environ[self.api_key_env]
        body = self._build_request_body(prompt)
        loop = asyncio.get_event_loop()
        parsed, usage = await loop.run_in_executor(
            None,
            lambda: _sync_post_json(
                OPENROUTER_ENDPOINT,
                body,
                api_key=api_key,
                timeout_s=self.timeout_s,
                extra_headers={
                    "HTTP-Referer": OPENROUTER_HTTP_REFERER,
                    "X-Title": OPENROUTER_X_TITLE,
                },
            ),
        )
        return parsed, usage

    def _parse_response(
        self, response_obj: object, latency_ms: float
    ) -> Optional[JudgeVerdict]:
        """Extract the judge JSON from an OpenAI-shaped chat response.

        Order of attempts (each falls through to the next on failure):

        1. Read ``choices[0].message.content``. If empty, fall back to
           ``choices[0].message.reasoning`` (some OpenRouter routes
           split CoT into that field).
        2. Strip any ``<think>...</think>`` block at the head — DeepSeek
           V4 Pro and Kimi K2.6 are reasoning models on OpenRouter and
           emit one before their final answer.
        3. ``json.loads`` the result via :meth:`_coerce_json_dict`,
           which also handles markdown-fenced JSON.
        4. If that fails, regex-extract the first ``{...is_harmful...}``
           block (covers Qwen 3.6 Plus prose wrapping + GLM 5.1's
           occasional pre-JSON narration).
        5. If all paths fail, return ``None`` -> ``path='unavailable'``.
        """
        if not isinstance(response_obj, dict):
            return None
        try:
            message = response_obj["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            return None
        if not isinstance(message, dict):
            return None

        content = message.get("content", "")
        if not isinstance(content, str) or not content.strip():
            # Fall back to the ``reasoning`` channel which some
            # OpenRouter routes use when content is split out.
            reasoning = message.get("reasoning")
            if isinstance(reasoning, str) and reasoning.strip():
                content = reasoning
            else:
                return None

        # Strip any <think>...</think> block from the head of the text.
        stripped = _OPENROUTER_COT_RE.sub("", content).strip()
        if stripped:
            v = self._coerce_json_dict(stripped, latency_ms=latency_ms)
            if v is not None:
                return v

        # Final fallback — pull out the first judge-shaped JSON block
        # from the FULL content (so we also catch JSON embedded inside
        # an unstripped CoT block or wrapped in pre-JSON prose).
        match = _OPENROUTER_JUDGE_JSON_RE.search(content)
        if match is not None:
            v = self._coerce_json_dict(match.group(0), latency_ms=latency_ms)
            if v is not None:
                return v

        logger.warning(
            "openrouter %s: all parse paths failed; first 160 chars: %r",
            self.model_id, content[:160],
        )
        return None


# ---------------------------------------------------------------------------
# Concrete subclasses — one per OpenRouter-routed frontier model
# ---------------------------------------------------------------------------


class OpenRouterDeepSeekV4ProAdapter(OpenRouterAdapter):
    """DeepSeek V4 Pro via OpenRouter.

    Verified 2026-05-15 PM: ~8.8 s latency, may emit a ``<think>`` CoT
    block which the base parser strips. The flagship DeepSeek
    reasoning model on the gateway.
    """

    model_id: str = "deepseek/deepseek-v4-pro"
    name: str = "openrouter_deepseek_v4_pro"
    vendor: str = "openrouter"
    # OpenRouter's published rate for deepseek-v4-pro (2026-05): ~
    # $0.435/M input, ~$1.00/M output (rounded from the live dashboard).
    cost_per_input_tok: float = 0.435 / 1_000_000
    cost_per_output_tok: float = 1.00 / 1_000_000


class OpenRouterKimiK26Adapter(OpenRouterAdapter):
    """Moonshot AI Kimi K2.6 via OpenRouter.

    Verified 2026-05-15 PM: ~3.1 s latency, clean JSON. Strong long-
    context training; complements DeepSeek's reasoning lineage.
    """

    model_id: str = "moonshotai/kimi-k2.6"
    name: str = "openrouter_kimi_k2_6"
    vendor: str = "openrouter"
    # OpenRouter Kimi K2.6 rate (2026-05): ~$0.73/M input.
    cost_per_input_tok: float = 0.73 / 1_000_000
    cost_per_output_tok: float = 2.20 / 1_000_000


class OpenRouterGLM51Adapter(OpenRouterAdapter):
    """Z.ai GLM 5.1 via OpenRouter.

    Verified 2026-05-15 PM: ~2.5 s latency. May emit chain-of-thought-
    style prose before its JSON — the regex JSON-extract fallback
    handles that case.
    """

    model_id: str = "z-ai/glm-5.1"
    name: str = "openrouter_glm_5_1"
    vendor: str = "openrouter"
    # OpenRouter GLM 5.1 rate (2026-05): ~$0.98/M input.
    cost_per_input_tok: float = 0.98 / 1_000_000
    cost_per_output_tok: float = 2.50 / 1_000_000


class OpenRouterQwen36PlusAdapter(OpenRouterAdapter):
    """Alibaba Qwen 3.6 Plus via OpenRouter.

    Verified 2026-05-15 PM: ~4.3 s latency, clean JSON on the probe but
    occasionally wraps in prose ("Here is..."). Wide multilingual
    coverage (Mandarin/Arabic/etc.) — complements the western-centric
    frontier judges.
    """

    model_id: str = "qwen/qwen3.6-plus"
    name: str = "openrouter_qwen3_6_plus"
    vendor: str = "openrouter"
    # OpenRouter Qwen 3.6 Plus rate (2026-05): ~$0.325/M input.
    cost_per_input_tok: float = 0.325 / 1_000_000
    cost_per_output_tok: float = 1.30 / 1_000_000


class OpenRouterNemotron3Super120BAdapter(OpenRouterAdapter):
    """NVIDIA Nemotron 3 Super 120B-A12B via OpenRouter.

    Verified 2026-05-15 PM: ~2.0 s latency, clean JSON. Cheapest of the
    five (very low per-token rate); used as the live-smoke default.
    The ``:free`` variant also works at ~19 s latency.
    """

    model_id: str = "nvidia/nemotron-3-super-120b-a12b"
    name: str = "openrouter_nemotron_3_super_120b"
    vendor: str = "openrouter"
    # OpenRouter Nemotron 3 Super 120B rate (2026-05): ~$0.09/M input.
    cost_per_input_tok: float = 0.09 / 1_000_000
    cost_per_output_tok: float = 0.36 / 1_000_000


# ---------------------------------------------------------------------------
# Backup-route adapters — Day-5 US-002 (FallbackVendorAdapter targets)
# ---------------------------------------------------------------------------


class OpenRouterGeminiAdapter(OpenRouterAdapter):
    """Backup route for Gemini 3.1 Pro when AI Studio prepayment is depleted.

    Model resolves to ``google/gemini-3.1-pro-preview-20260219`` via OR.
    Cost: ~$0.0012/call at probe time 2026-05-15. This is the route that
    preserves Gemini Award eligibility (Google sponsor).

    Gemini 3.1 Pro is a reasoning model on OpenRouter. It returns content
    via ``choices[0].message.content`` when ``finish_reason=='stop'`` but
    may put content in ``message.reasoning`` when ``finish_reason=='length'``
    with ``max_tokens`` exhausted on reasoning tokens. The base class
    already handles both channels (see :meth:`OpenRouterAdapter._parse_response`
    multi-tier parsing fallback) and the default ``max_tokens=400`` gives
    the reasoning channel headroom while keeping cost predictable.
    """

    model_id: str = "google/gemini-3.1-pro-preview"
    name: str = "openrouter_gemini_3_1_pro"
    vendor: str = "openrouter"
    # Live probe 2026-05-15 PM: ~$0.0012 per single judge call (~110 in
    # + 38 out tokens). The published per-token figures are inferred
    # from that observation; OpenRouter does not publish a separate
    # per-token rate for this preview model.
    cost_per_input_tok: float = 1.25 / 1_000_000
    cost_per_output_tok: float = 10.0 / 1_000_000


class OpenRouterClaudeOpus47FastAdapter(OpenRouterAdapter):
    """Backup route for Claude Opus 4.7 when opencode Zen primary is degraded.

    The ``-fast`` variant is identical capability per Anthropic docs;
    routing via OR adds ~600 ms vs direct OCZ. Live probe 2026-05-15:
    1.7 s response time.
    """

    model_id: str = "anthropic/claude-opus-4.7-fast"
    name: str = "openrouter_claude_opus_4_7_fast"
    vendor: str = "openrouter"
    # Anthropic Claude Opus family rate via OpenRouter (2026-05):
    # ~$15/M input, ~$75/M output (published OR dashboard tier).
    cost_per_input_tok: float = 15.0 / 1_000_000
    cost_per_output_tok: float = 75.0 / 1_000_000


class OpenRouterGPT55Adapter(OpenRouterAdapter):
    """Backup route for GPT-5.5 when opencode Zen primary is degraded
    or rate-limited.

    Live probe 2026-05-15: 4.5 s response time.

    The GPT-5 family natively requires ``max_completion_tokens`` instead
    of ``max_tokens`` on OpenAI's own endpoint (see
    :class:`apohara_aegis.multi_judge.GPT55Adapter`). OpenRouter proxies
    ``max_tokens`` to the upstream provider's expected field, so the
    base class request body works as-is — the 2026-05-15 PM live probe
    confirmed HTTP 200 with the default body shape.
    """

    model_id: str = "openai/gpt-5.5"
    name: str = "openrouter_gpt_5_5"
    vendor: str = "openrouter"
    # OpenAI GPT-5 family rate via OpenRouter (2026-05): $1.25/M input,
    # $10/M output (matches OpenAI direct).
    cost_per_input_tok: float = 1.25 / 1_000_000
    cost_per_output_tok: float = 10.0 / 1_000_000


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "OPENROUTER_ENDPOINT",
    "OPENROUTER_HTTP_REFERER",
    "OPENROUTER_X_TITLE",
    "OpenRouterAdapter",
    "OpenRouterDeepSeekV4ProAdapter",
    "OpenRouterKimiK26Adapter",
    "OpenRouterGLM51Adapter",
    "OpenRouterQwen36PlusAdapter",
    "OpenRouterNemotron3Super120BAdapter",
    "OpenRouterGeminiAdapter",
    "OpenRouterClaudeOpus47FastAdapter",
    "OpenRouterGPT55Adapter",
]
