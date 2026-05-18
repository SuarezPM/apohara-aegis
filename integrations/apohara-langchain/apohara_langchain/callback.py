# SPDX-License-Identifier: Apache-2.0
"""
ApoharaCallbackHandler — LangChain BaseCallbackHandler that gates prompts
through the Apohara PROBANT judge API.

On every LLM start and tool start the handler fires a synchronous POST to
  POST ${APOHARA_API_URL}/v1/soar/judge/evaluate
  body: {"prompt": <text>, "layer": "both"}

Decision semantics:
  ALLOW  → continue (no-op)
  BLOCK  → raise ToolException (aborts the chain)
  REVIEW → log a warning and continue; raise ToolException when
            block_on_review=True is passed to the constructor.

Network failures are fail-open by default: a warning is logged but the
chain is NOT aborted.  Set fail_open=False to raise on network error.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Union

import httpx

try:
    from langchain_core.callbacks.base import BaseCallbackHandler
    from langchain_core.tools import ToolException
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "langchain-core is required: pip install 'langchain-core>=0.2,<0.4'"
    ) from exc

logger = logging.getLogger(__name__)

_DEFAULT_API_URL = "https://api.apohara.dev"
_EVALUATE_PATH = "/v1/soar/judge/evaluate"
_DEFAULT_TIMEOUT = 10.0  # seconds


class ApoharaCallbackHandler(BaseCallbackHandler):
    """LangChain callback that intercepts prompts via the Apohara PROBANT API.

    Parameters
    ----------
    block_on_review:
        When True, a REVIEW verdict is treated as BLOCK (raises ToolException).
        Default False — REVIEW only emits a warning.
    fail_open:
        When True (default), network errors are logged as warnings and the
        chain continues.  When False, network errors raise ToolException.
    api_url:
        Base URL of the Apohara API.  Defaults to the APOHARA_API_URL env var
        or https://api.apohara.dev.
    timeout:
        HTTP request timeout in seconds.  Default 10.
    """

    def __init__(
        self,
        *,
        block_on_review: bool = False,
        fail_open: bool = True,
        api_url: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        super().__init__()
        self.block_on_review = block_on_review
        self.fail_open = fail_open
        self.timeout = timeout
        self.api_url = (
            api_url
            or os.environ.get("APOHARA_API_URL", _DEFAULT_API_URL)
        ).rstrip("/")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate(self, prompt: str) -> None:
        """POST to /v1/soar/judge/evaluate and enforce the decision."""
        url = self.api_url + _EVALUATE_PATH
        try:
            response = httpx.post(
                url,
                json={"prompt": prompt, "layer": "both"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            msg = f"Apohara PROBANT: network error during evaluate: {exc}"
            if self.fail_open:
                logger.warning(msg)
                return
            raise ToolException(msg) from exc
        except Exception as exc:  # noqa: BLE001
            msg = f"Apohara PROBANT: unexpected error during evaluate: {exc}"
            if self.fail_open:
                logger.warning(msg)
                return
            raise ToolException(msg) from exc

        decision = (body.get("decision") or "").upper()

        if decision == "BLOCK":
            reason = body.get("decision_reason", "no reason provided")
            raise ToolException(
                f"Apohara PROBANT blocked this prompt. Decision: BLOCK. "
                f"Reason: {reason}"
            )

        if decision == "REVIEW":
            reason = body.get("decision_reason", "")
            msg = (
                f"Apohara PROBANT flagged this prompt for review. "
                f"Reason: {reason}"
            )
            if self.block_on_review:
                raise ToolException(msg)
            logger.warning(msg)

        # ALLOW → continue silently

    def _extract_prompt(self, serialized: Dict[str, Any], *args: Any) -> str:
        """Best-effort extraction of a string prompt from callback args."""
        # on_tool_start passes input as second positional arg (input_str)
        # on_llm_start passes messages as second positional arg (messages)
        if args:
            first = args[0]
            if isinstance(first, str):
                return first
            if isinstance(first, list):
                # Flatten list of message lists
                parts: List[str] = []
                for item in first:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, list):
                        for msg in item:
                            content = getattr(msg, "content", None)
                            if isinstance(content, str):
                                parts.append(content)
                    else:
                        content = getattr(item, "content", None)
                        if isinstance(content, str):
                            parts.append(content)
                return " ".join(parts)
        return serialized.get("name", "")

    # ------------------------------------------------------------------
    # LangChain callback hooks
    # ------------------------------------------------------------------

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        **kwargs: Any,
    ) -> None:
        """Called before an LLM is invoked with a list of string prompts."""
        combined = " ".join(prompts)
        self._evaluate(combined)

    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[Any]],
        **kwargs: Any,
    ) -> None:
        """Called before a chat model is invoked with message lists."""
        parts: List[str] = []
        for batch in messages:
            for msg in batch:
                content = getattr(msg, "content", None)
                if isinstance(content, str):
                    parts.append(content)
        self._evaluate(" ".join(parts))

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Called before a tool is invoked with its input string."""
        self._evaluate(input_str)
