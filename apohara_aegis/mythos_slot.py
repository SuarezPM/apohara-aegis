# SPDX-License-Identifier: Apache-2.0
"""
MythosAttackerAdapter — reserved slot in the adversarial ensemble for
Claude Mythos via Project Glasswing / Claude for Open Source program.

ARCHITECTURAL READINESS, NOT ACCESS CLAIM:
Apohara has NOT been granted Mythos access at the time of writing.
This adapter is reserved and inactive; it activates only upon Glasswing
approval / Claude for Open Source program approval AND provisioning of
legitimate API credentials.

This module does not claim Anthropic endorsement, sponsorship, or
relationship beyond Apohara's submitted Claude for Open Source application.

Architectural readiness rationale:
- Subclasses VendorAdapter (apohara_aegis/multi_judge.py:313) per the
  Architect+Critic review of the fusion plan.
- _available() returns False unless APOHARA_MYTHOS_ENABLED=1 AND a
  credential env var is present. Ensemble loop at multi_judge.py:347
  gates on _available() and returns _unavailable_verdict("not_configured")
  cleanly without raising.
- When enabled, _call_api routes to Anthropic Mythos API (Bedrock or
  Vertex AI). Implementation stubbed pending program approval.
"""
from __future__ import annotations

import os
from typing import Optional

from apohara_aegis.multi_judge import JudgeVerdict, VendorAdapter


class MythosAttackerAdapter(VendorAdapter):
    """Reserved slot. Inactive until Glasswing/Claude-for-OS approval + creds.

    This adapter subclasses VendorAdapter directly (NOT FallbackVendorAdapter,
    which is a routing wrapper for primary+backup chains). It carries its own
    seat-level identity and participates in the ensemble as the 11th seat
    (0-indexed: seat 10). The seat is INACTIVE in production until both
    environment gates are satisfied.

    Env-gate (both required to activate):
        APOHARA_MYTHOS_ENABLED=1
        ANTHROPIC_MYTHOS_API_KEY=<provisioned-key>
        -OR-
        AWS_BEDROCK_MYTHOS_CREDS=<credentials>

    Audit-log provenance:
        CombinedVerdict.llm_verdict.vendor_votes["mythos-glasswing"] will
        surface Mythos votes in the HMAC chain when active.
    """

    name: str = "mythos-glasswing"
    model: str = "anthropic/claude-mythos-preview"
    vendor: str = "anthropic-glasswing"
    # Anthropic Mythos pricing (public Anthropic pricing page, 2026-05):
    # $25/M input tokens, $125/M output tokens via Bedrock/Vertex AI/Foundry.
    cost_per_input_tok: float = 25.0 / 1_000_000
    cost_per_output_tok: float = 125.0 / 1_000_000

    # Seat metadata (used by audit log and dissent-summary UI)
    gateway: str = "anthropic-glasswing"
    badge: str = "MY"
    seat: str = "mythos-attacker-seat"

    def _available(self) -> bool:
        """Return True iff APOHARA_MYTHOS_ENABLED=1 AND a credential is present.

        Ensemble loop at multi_judge.py:347 gates on this method; returning
        False causes the loop to call _unavailable_verdict('not_configured')
        without raising, keeping the existing 10-vendor production unaffected.
        """
        if os.environ.get("APOHARA_MYTHOS_ENABLED") != "1":
            return False
        if not (
            os.environ.get("ANTHROPIC_MYTHOS_API_KEY")
            or os.environ.get("AWS_BEDROCK_MYTHOS_CREDS")
        ):
            return False
        return True

    async def _call_api(self, prompt: str) -> tuple[object, dict]:
        """Unreachable unless _available() returns True.

        Stub pending Glasswing / Claude for Open Source approval.
        Replace with real Anthropic Mythos Bedrock/Vertex AI call upon
        program approval + APOHARA_MYTHOS_ENABLED=1 + credential env var.

        The ensemble driver at multi_judge.py:345-371 calls this only after
        _available() returns True, so this raise is a clean guard — not
        a production path.
        """
        raise NotImplementedError(
            "Mythos slot reserved; Claude for Open Source / Glasswing application pending. "
            "Adapter activates upon program approval + APOHARA_MYTHOS_ENABLED=1 + credential env var."
        )

    def _parse_response(
        self, response_obj: object, latency_ms: float = 0.0
    ) -> Optional[JudgeVerdict]:
        """Stub; mirrors VendorAdapter contract. Unreachable until _call_api is implemented."""
        raise NotImplementedError(
            "Mythos _parse_response stub — activate after Glasswing approval."
        )
