# SPDX-License-Identifier: Apache-2.0
"""
16-code incident taxonomy for agentic AI misbehavior classification.

Provides a canonical mapping from incident patterns to structured codes
used by soar_pipeline.py DETECT stage and the FORENSICS audit trail.

Part of the Apohara PROBANT Fusion Sprint (2026-05-18).
Implementation per docs/research/* — see plan in
.omc/ralph/SESSION-MEMORY-FUSION-PLAN-2026-05-18T2030Z.md
"""
from __future__ import annotations

# TODO(US-74): implement incident taxonomy
#   - Define IncidentCode enum with 16 codes (e.g. PROMPT_INJECTION,
#     DATA_EXFIL, TOOL_ABUSE, GOAL_HIJACK, ROLE_ESCALATION, etc.)
#   - Each code: severity (LOW/MEDIUM/HIGH/CRITICAL), category, description
#   - classifier(action: str) -> list[IncidentCode] fast-path function
#   - taxonomy_metadata() -> dict for /health endpoint exposure
