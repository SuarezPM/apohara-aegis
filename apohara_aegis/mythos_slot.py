# SPDX-License-Identifier: Apache-2.0
"""
Mythos VendorAdapter subclass for Apohara PROBANT.

Plugs the Mythos AI safety platform into the multi-judge ensemble via
the existing VendorAdapter interface defined in openrouter_adapters.py.
Boundary: Mythos is a vendor integration, not an Anthropic endorsement.

Part of the Apohara PROBANT Fusion Sprint (2026-05-18).
Implementation per docs/research/* — see plan in
.omc/ralph/SESSION-MEMORY-FUSION-PLAN-2026-05-18T2030Z.md
"""
from __future__ import annotations

# TODO(US-79): implement MythosAdapter
#   - Subclass the VendorAdapter ABC from openrouter_adapters.py
#   - MythosAdapter.judge(prompt: str, response: str) -> Verdict
#   - Auth: API key from env MYTHOS_API_KEY (never hardcoded)
#   - Boundary language in responses: "Mythos safety signal" not "Mythos-approved"
#   - Graceful degradation: if Mythos API unavailable, return REVIEW with note
#   - Register in defense_chain.py adapter registry
