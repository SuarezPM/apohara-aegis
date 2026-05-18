# SPDX-License-Identifier: Apache-2.0
"""
apohara_guard — CrewAI tool decorator for Apohara PROBANT.

Wraps a CrewAI BaseTool so its _run method is preceded by a synchronous
POST to POST ${APOHARA_API_URL}/v1/soar/judge/evaluate.

Decision semantics:
  ALLOW  → call through to the original tool
  BLOCK  → raise Exception with BLOCK message (aborts agent step)
  REVIEW → log a warning and call through; raise when block_on_review=True.

Network failures are fail-open by default.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

try:
    from crewai.tools import BaseTool  # type: ignore[import-untyped]
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "crewai is required: pip install 'crewai>=0.30'"
    ) from exc

logger = logging.getLogger(__name__)

_DEFAULT_API_URL = "https://api.apohara.dev"
_EVALUATE_PATH = "/v1/soar/judge/evaluate"
_DEFAULT_TIMEOUT = 10.0


def _evaluate_prompt(
    prompt: str,
    *,
    api_url: str,
    block_on_review: bool,
    fail_open: bool,
    timeout: float,
) -> None:
    """POST to /v1/soar/judge/evaluate and enforce the decision."""
    url = api_url.rstrip("/") + _EVALUATE_PATH
    try:
        response = httpx.post(
            url,
            json={"prompt": prompt, "layer": "both"},
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPError as exc:
        msg = f"Apohara PROBANT: network error during evaluate: {exc}"
        if fail_open:
            logger.warning(msg)
            return
        raise RuntimeError(msg) from exc
    except Exception as exc:  # noqa: BLE001
        msg = f"Apohara PROBANT: unexpected error during evaluate: {exc}"
        if fail_open:
            logger.warning(msg)
            return
        raise RuntimeError(msg) from exc

    decision = (body.get("decision") or "").upper()

    if decision == "BLOCK":
        reason = body.get("decision_reason", "no reason provided")
        raise RuntimeError(
            f"Apohara PROBANT blocked this tool input. Decision: BLOCK. "
            f"Reason: {reason}"
        )

    if decision == "REVIEW":
        reason = body.get("decision_reason", "")
        msg = (
            f"Apohara PROBANT flagged this tool input for review. "
            f"Reason: {reason}"
        )
        if block_on_review:
            raise RuntimeError(msg)
        logger.warning(msg)

    # ALLOW → continue silently


def apohara_guard(
    tool: BaseTool,
    *,
    block_on_review: bool = False,
    fail_open: bool = True,
    api_url: Optional[str] = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> BaseTool:
    """Wrap a CrewAI BaseTool with Apohara PROBANT pre-execution guard.

    Parameters
    ----------
    tool:
        The CrewAI BaseTool instance to wrap.
    block_on_review:
        When True, a REVIEW verdict raises RuntimeError (blocks tool call).
    fail_open:
        When True (default), network errors are logged and the tool proceeds.
    api_url:
        Base URL of the Apohara API. Defaults to APOHARA_API_URL env var
        or https://api.apohara.dev.
    timeout:
        HTTP request timeout in seconds. Default 10.

    Returns
    -------
    BaseTool
        The same tool object with _run monkey-patched to include the guard.
    """
    resolved_url = (
        api_url or os.environ.get("APOHARA_API_URL", _DEFAULT_API_URL)
    )

    original_run = tool._run

    def _guarded_run(tool_input: Any, **kwargs: Any) -> Any:
        # Normalise tool_input to a string for the evaluate call
        prompt = tool_input if isinstance(tool_input, str) else str(tool_input)
        _evaluate_prompt(
            prompt,
            api_url=resolved_url,
            block_on_review=block_on_review,
            fail_open=fail_open,
            timeout=timeout,
        )
        return original_run(tool_input, **kwargs)

    tool._run = _guarded_run  # type: ignore[method-assign]
    return tool
