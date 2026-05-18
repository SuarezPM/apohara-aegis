# SPDX-License-Identifier: Apache-2.0
"""
Tests for nist_mapping.py — NIST AI RMF / CSA Agentic Profile mapping.

Apohara PROBANT Fusion Sprint (2026-05-18) — US-75.

Coverage:
  - ≥30 controls present
  - Every control has required non-empty fields
  - rmf_function is one of the 4 valid values
  - DJL rule IDs match expected format (cross-resolution deferred to US-86)
  - Incident codes resolve to taxonomy.DEFINITIONS
  - ≥10 controls flagged as CSA Agentic Profile extensions
  - All 4 RMF functions represented
"""
from __future__ import annotations

import re

import pytest

from apohara_aegis.nist_mapping import CONTROLS, AgenticControl
from apohara_aegis.taxonomy import DEFINITIONS as TAXONOMY, IncidentCode


# ---------------------------------------------------------------------------
# AC4-1 — ≥30 controls
# ---------------------------------------------------------------------------


def test_at_least_30_controls() -> None:
    assert len(CONTROLS) >= 30, (
        f"Expected ≥30 NIST controls, found {len(CONTROLS)}"
    )


# ---------------------------------------------------------------------------
# AC4-2 — every control has required non-empty fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("control_id", list(CONTROLS.keys()))
def test_every_control_has_required_fields(control_id: str) -> None:
    ctrl = CONTROLS[control_id]
    assert isinstance(ctrl, AgenticControl)
    assert ctrl.control_id == control_id, (
        f"control_id mismatch: key={control_id!r}, field={ctrl.control_id!r}"
    )
    assert isinstance(ctrl.title, str) and ctrl.title.strip(), (
        f"{control_id}: title must be non-empty"
    )
    assert isinstance(ctrl.description, str) and ctrl.description.strip(), (
        f"{control_id}: description must be non-empty"
    )
    assert isinstance(ctrl.rmf_subcategory, str) and ctrl.rmf_subcategory.strip(), (
        f"{control_id}: rmf_subcategory must be non-empty"
    )
    assert isinstance(ctrl.apohara_audit_log_field, str) and ctrl.apohara_audit_log_field.strip(), (
        f"{control_id}: apohara_audit_log_field must be non-empty"
    )
    assert isinstance(ctrl.csa_agentic_extension, bool), (
        f"{control_id}: csa_agentic_extension must be bool"
    )


# ---------------------------------------------------------------------------
# AC4-3 — rmf_function is one of the 4 valid values
# ---------------------------------------------------------------------------

_VALID_FUNCTIONS = {"GOVERN", "MAP", "MEASURE", "MANAGE"}


@pytest.mark.parametrize("control_id", list(CONTROLS.keys()))
def test_rmf_function_is_valid(control_id: str) -> None:
    ctrl = CONTROLS[control_id]
    assert ctrl.rmf_function in _VALID_FUNCTIONS, (
        f"{control_id}: rmf_function '{ctrl.rmf_function}' not in {_VALID_FUNCTIONS}"
    )


# ---------------------------------------------------------------------------
# AC4-4 — DJL rule IDs match format (format-only; US-86 cross-resolves)
# ---------------------------------------------------------------------------

_DJL_ID_RE = re.compile(r"^DJL-[A-Z]+-\d{3}$")


@pytest.mark.parametrize("control_id", list(CONTROLS.keys()))
def test_djl_rule_ids_format_only(control_id: str) -> None:
    ctrl = CONTROLS[control_id]
    for rule_id in ctrl.apohara_djl_rule_ids:
        assert _DJL_ID_RE.match(rule_id), (
            f"{control_id}: DJL rule ID '{rule_id}' does not match DJL-[A-Z]+-NNN"
        )


# ---------------------------------------------------------------------------
# AC4-5 — incident codes resolve to taxonomy DEFINITIONS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("control_id", list(CONTROLS.keys()))
def test_incident_codes_resolve_to_taxonomy(control_id: str) -> None:
    ctrl = CONTROLS[control_id]
    for code in ctrl.apohara_incident_codes:
        assert isinstance(code, IncidentCode), (
            f"{control_id}: {code!r} is not an IncidentCode instance"
        )
        assert code in TAXONOMY, (
            f"{control_id}: IncidentCode '{code}' not found in taxonomy.DEFINITIONS"
        )


# ---------------------------------------------------------------------------
# AC4-6 — ≥10 controls flagged as CSA Agentic Profile extensions
# ---------------------------------------------------------------------------


def test_csa_extension_count_documented() -> None:
    csa_count = sum(1 for c in CONTROLS.values() if c.csa_agentic_extension)
    assert csa_count >= 10, (
        f"Expected ≥10 CSA Agentic Profile extension controls, found {csa_count}"
    )


# ---------------------------------------------------------------------------
# Additional coverage
# ---------------------------------------------------------------------------


def test_all_four_rmf_functions_represented() -> None:
    functions_present = {c.rmf_function for c in CONTROLS.values()}
    assert functions_present == _VALID_FUNCTIONS, (
        f"Not all 4 RMF functions represented. Present: {functions_present}"
    )


def test_controls_are_frozen() -> None:
    """AgenticControl is frozen=True; direct attribute assignment must raise FrozenInstanceError."""
    ctrl = next(iter(CONTROLS.values()))
    with pytest.raises(Exception):
        # dataclasses.FrozenInstanceError is a subclass of AttributeError in CPython
        ctrl.title = "mutated"  # type: ignore[misc]


def test_base_nist_controls_present() -> None:
    """At least some controls should NOT be CSA extensions (base NIST AI RMF 1.0)."""
    base_count = sum(1 for c in CONTROLS.values() if not c.csa_agentic_extension)
    assert base_count >= 5, (
        f"Expected ≥5 base NIST AI RMF 1.0 controls, found {base_count}"
    )


def test_govern_function_count() -> None:
    govern_count = sum(1 for c in CONTROLS.values() if c.rmf_function == "GOVERN")
    assert govern_count >= 5, (
        f"Expected ≥5 GOVERN controls, found {govern_count}"
    )


def test_manage_function_count() -> None:
    manage_count = sum(1 for c in CONTROLS.values() if c.rmf_function == "MANAGE")
    assert manage_count >= 5, (
        f"Expected ≥5 MANAGE controls, found {manage_count}"
    )
