# SPDX-License-Identifier: Apache-2.0
"""Apohara Aegis × HuggingFace smolagents — defense-in-depth wrapper.

This module installs two layers of protection around a smolagents agent
without touching its core logic:

    PERIMETER  — re-routes the model's HTTP endpoint to a Lobster Trap
                 proxy (Veea) so the YAML policy (`configs/lobstertrap_policy.yaml`)
                 catches prompt-injection / credential / PII attempts at
                 ingress and egress. We never re-implement Lobster Trap's
                 regex matching here; we just point the SDK at it.

    BEHAVIORAL — installs an ``ActionStep`` step-callback that runs the
                 closed-form INV-15 risk score from ``inv15_gate.py``.
                 If the agent's role is in ``judge_roles`` (default
                 ``{"critic"}``) and the risk exceeds ``tau`` (default
                 0.65), the callback raises ``AegisBlocked`` *before* the
                 tool actually fires.

We deliberately do NOT take a hard PyPI dependency on smolagents; the
import is lazy so users who only need the policy YAML or the local
INV-15 scorer don't pay for the smolagents transitive footprint.

API in 2026 (smolagents 1.25.0, confirmed 2026-05-14):
    - ``CodeAgent(model=...)`` and ``ToolCallingAgent(model=...)`` both
      inherit ``MultiStepAgent``, which accepts ``step_callbacks=[fn]``.
    - Step callbacks fire AFTER the LLM has produced a code block /
      tool call, but BEFORE Python execution actually runs. So raising
      from the callback prevents the unsafe action — exactly what we
      need for INV-15. (Tested live; see ``tests/test_aegis_smolagents.py``.)
    - The model's HTTP base URL lives on ``model.api_base`` for
      ``OpenAIModel`` / ``OpenAIServerModel``. We rewrite this in place.

Limitations (HONEST):
    - We cannot pause Lobster Trap's *Go* enforcement from here; we only
      route traffic through it. If the LT binary isn't running, the
      perimeter layer silently no-ops (we don't raise, because Aegis is
      defense-in-depth, not single-point-of-truth).
    - The risk score uses *static* metadata attached to the agent
      (``agent.aegis_meta``) plus per-call counters maintained by the
      callback. We do not introspect the live KV cache (that requires
      the upstream Apohara Context Forge engine).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

from .inv15_gate import DEFAULT_TAU, JUDGE_ROLES, RiskAssessment, evaluate
from .policy_loader import PolicyDigest, load_policy

logger = logging.getLogger("apohara_aegis")


class AegisBlocked(RuntimeError):
    """Raised when the behavioral gate denies a step.

    Carries the underlying ``RiskAssessment`` so callers can log it.
    """

    def __init__(self, assessment: RiskAssessment):
        super().__init__(assessment.reason)
        self.assessment = assessment


# ---------------------------------------------------------------------------
# Public wrapper
# ---------------------------------------------------------------------------


class AegisGuard:
    """Defense-in-depth wrapper for HuggingFace smolagents.

    Use ``AegisGuard.wrap(agent, ...)`` and run the agent normally;
    the safety layers attach in place.

    Example::

        >>> from smolagents import CodeAgent, OpenAIModel
        >>> from apohara_aegis import AegisGuard
        >>> model = OpenAIModel(model_id="gpt-4o-mini",
        ...                     api_base="http://localhost:8080/v1")
        >>> agent = CodeAgent(tools=[], model=model)
        >>> guarded = AegisGuard.wrap(agent,
        ...     policy_path="configs/lobstertrap_policy.yaml")
        >>> # guarded is the same agent instance, now policy-aware
    """

    @staticmethod
    def wrap(
        agent: Any,
        *,
        policy_path: Optional[str | Path] = None,
        lt_endpoint: Optional[str] = None,
        judge_role: str = "critic",
        tau: float = DEFAULT_TAU,
        audit_log: Optional[str | Path] = None,
    ) -> Any:
        """Install perimeter + behavioral layers on a smolagents agent.

        Args:
            agent: A ``smolagents.MultiStepAgent`` subclass instance
                (e.g. ``CodeAgent`` or ``ToolCallingAgent``).
            policy_path: Path to a Lobster Trap policy YAML. If given,
                the digest is attached to ``agent.aegis_policy`` and
                logged. Pure documentation — Lobster Trap itself enforces
                the rules in Go.
            lt_endpoint: HTTP base URL of a running Lobster Trap proxy
                (e.g. ``http://localhost:8080``). If set, the agent's
                model is reconfigured to send traffic through it.
                If ``None``, falls back to the env var ``AEGIS_LT_ENDPOINT``.
            judge_role: Which agent role to treat as judge-type for
                INV-15. Pass ``"critic"`` for a critic agent; any other
                role is exempted from the gate by design.
            tau: INV-15 risk threshold. Steps with risk > tau are
                blocked when ``agent.aegis_meta['role']`` is a judge role.
            audit_log: Optional path to a JSONL file. Each gate decision
                is appended as one JSON line.

        Returns:
            The same ``agent`` instance, mutated in place. We return it
            for ergonomic chaining; ``agent is AegisGuard.wrap(agent)``.

        Raises:
            ValueError: if the agent doesn't expose ``step_callbacks``
                (i.e. not a smolagents ``MultiStepAgent`` subclass).
        """
        # Detect the smolagents shape *without* a hard import (we want
        # this module to load even if smolagents isn't installed; the
        # type check is done duck-typed).
        if not hasattr(agent, "step_callbacks"):
            raise ValueError(
                "AegisGuard.wrap expected a smolagents agent (MultiStepAgent "
                f"subclass with .step_callbacks); got {type(agent).__name__}. "
                "Install smolagents>=1.0 and pass a CodeAgent or ToolCallingAgent."
            )

        # --- PERIMETER LAYER ----------------------------------------------
        endpoint = lt_endpoint or os.environ.get("AEGIS_LT_ENDPOINT")
        if endpoint:
            _route_through_lobster_trap(agent, endpoint)

        # --- POLICY DIGEST (informational) --------------------------------
        if policy_path is not None:
            digest = load_policy(policy_path)
            agent.aegis_policy = digest
            logger.info(
                "AegisGuard: loaded policy %r v%s (%d ingress, %d egress, "
                "%d DENY rules)",
                digest.name, digest.version,
                digest.ingress_rule_count, digest.egress_rule_count,
                len(digest.deny_rules),
            )
        else:
            agent.aegis_policy = None

        # --- BEHAVIORAL LAYER --------------------------------------------
        # Attach metadata bag (callers populate this with role / candidate
        # counts / reuse rates before each run).
        if not hasattr(agent, "aegis_meta") or agent.aegis_meta is None:
            agent.aegis_meta = {"role": judge_role}

        callback = _make_inv15_callback(
            agent=agent,
            tau=tau,
            judge_roles=frozenset({judge_role.lower()} | JUDGE_ROLES),
            audit_log=Path(audit_log) if audit_log else None,
        )
        # smolagents 1.25.0 exposes step_callbacks as a CallbackRegistry;
        # registering for ActionStep matches the public extension point.
        from smolagents import ActionStep  # type: ignore[import-untyped]
        agent.step_callbacks.register(ActionStep, callback)

        return agent


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _route_through_lobster_trap(agent: Any, endpoint: str) -> None:
    """Re-point the agent's model HTTP base URL at the Lobster Trap proxy.

    In smolagents 1.25.0 the OpenAI-style models (``OpenAIModel`` /
    ``OpenAIServerModel``) do NOT expose ``api_base`` as a public attribute
    after construction — the URL lives on ``model.client.base_url`` (the
    underlying ``openai.OpenAI`` client) and ``model.client_kwargs["base_url"]``
    (used on reconstruction). We patch both so the next request actually
    goes through the proxy, and we also set a top-level ``model.api_base``
    alias for convenience so downstream telemetry can read it. For other
    model classes we log a warning and skip — the behavioral layer still
    applies.
    """
    model = getattr(agent, "model", None)
    if model is None:
        logger.warning(
            "AegisGuard perimeter: agent has no .model attribute; "
            "skipping Lobster Trap routing."
        )
        return

    # Normalize endpoint to a /v1-terminated base URL.
    clean = endpoint.rstrip("/")
    new_base = clean if clean.endswith("/v1") else f"{clean}/v1"

    rewrote = False

    # Path 1 (smolagents 1.x OpenAIModel): patch the live OpenAI client.
    client = getattr(model, "client", None)
    if client is not None and hasattr(client, "base_url"):
        try:
            client.base_url = new_base
            rewrote = True
        except Exception as exc:  # pragma: no cover - SDK-version dependent
            logger.debug("AegisGuard: could not patch model.client.base_url: %s", exc)

    # Path 2: update the reconstruction kwargs so future re-inits use LT too.
    ckw = getattr(model, "client_kwargs", None)
    if isinstance(ckw, dict):
        ckw["base_url"] = new_base
        rewrote = True

    # Path 3 (legacy): some forks still expose .api_base directly.
    if hasattr(model, "api_base"):
        try:
            model.api_base = new_base
            rewrote = True
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("AegisGuard: could not patch model.api_base: %s", exc)

    # Convenience alias so callers / tests can introspect.
    try:
        setattr(model, "api_base", new_base)
    except Exception:  # pragma: no cover - defensive
        pass

    if rewrote:
        logger.info(
            "AegisGuard perimeter: rerouted model HTTP base → %r", new_base
        )
    else:
        logger.warning(
            "AegisGuard perimeter: model %s has no recognisable HTTP "
            "endpoint attribute; cannot reroute through Lobster Trap. "
            "Behavioral layer still active.",
            type(model).__name__,
        )


def _make_inv15_callback(
    *,
    agent: Any,
    tau: float,
    judge_roles: frozenset[str],
    audit_log: Optional[Path],
) -> Callable[..., None]:
    """Build the per-step callback that smolagents will invoke on
    each ``ActionStep``. The closure captures ``agent`` so the
    callback can read the live ``aegis_meta`` bag updated by callers
    between runs."""

    def _on_action_step(memory_step: Any, agent_obj: Any | None = None, **_: Any) -> None:
        # smolagents passes the step (and sometimes the agent) by position
        # or keyword depending on minor-version; we accept both shapes.
        meta = getattr(agent, "aegis_meta", None) or {}
        role = str(meta.get("role", "")).lower()
        candidate_count = int(meta.get("candidate_count", 2))
        reuse_rate = float(meta.get("reuse_rate", 0.0))
        layout_shuffled = bool(meta.get("layout_shuffled", False))

        assessment = evaluate(
            role,
            tau=tau,
            candidate_count=candidate_count,
            reuse_rate=reuse_rate,
            layout_shuffled=layout_shuffled,
            judge_roles=judge_roles,
        )

        if audit_log is not None:
            try:
                audit_log.parent.mkdir(parents=True, exist_ok=True)
                with audit_log.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "role": assessment.agent_role,
                        "risk": assessment.risk_score,
                        "blocked": assessment.blocked,
                        "reason": assessment.reason,
                    }) + "\n")
            except OSError as exc:  # pragma: no cover - filesystem dependent
                logger.warning("AegisGuard audit-log write failed: %s", exc)

        if assessment.blocked:
            # Raising from a step callback aborts the step; smolagents
            # surfaces the exception to the .run() caller. Tested live.
            raise AegisBlocked(assessment)

        # Allow path — annotate the memory_step so downstream telemetry
        # (e.g. Gradio dashboard) can read it.
        try:
            setattr(memory_step, "aegis_assessment", assessment)
        except Exception:  # pragma: no cover - defensive
            pass

    return _on_action_step
