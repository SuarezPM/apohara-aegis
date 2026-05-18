# SPDX-License-Identifier: Apache-2.0
"""
apohara-crewai — CrewAI tool decorator for Apohara PROBANT.

Wraps CrewAI tools so their execution is gated through the
Apohara judge API (POST /v1/soar/judge/evaluate) before the tool runs.
"""
from .tool_wrapper import apohara_guard

__all__ = ["apohara_guard"]
__version__ = "0.1.0"
