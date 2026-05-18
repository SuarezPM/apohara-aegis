# SPDX-License-Identifier: Apache-2.0
"""
apohara-langchain — LangChain callback handler for Apohara PROBANT.

Intercepts LLM and tool invocations and gates them through the
Apohara judge API (POST /v1/soar/judge/evaluate) before execution.
"""
from .callback import ApoharaCallbackHandler

__all__ = ["ApoharaCallbackHandler"]
__version__ = "0.1.0"
