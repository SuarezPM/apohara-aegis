"""Tests for taxonomy.py 16-code incident classification — Apohara PROBANT Fusion Sprint.

US-74: Verify IncidentCode enum, IncidentDefinition dataclass, and DEFINITIONS
mapping are internally consistent and match the categorical spec.

NOTE: Do NOT add tests that resolve rule IDs against djl.py — US-72 commits
those definitions in parallel. US-86 CI gate will verify cross-resolution.
"""
from __future__ import annotations

import pytest

from apohara_aegis.taxonomy import DEFINITIONS, IncidentCode, IncidentDefinition


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------

def test_exactly_16_codes():
    assert len(list(IncidentCode)) == 16


def test_categories_balanced():
    """3 PI + 3 EXF + 3 MIS + 2 FIN + 2 PII + 3 GOV = 16."""
    codes = [c.value for c in IncidentCode]
    assert sum(1 for c in codes if c.startswith("AGT-PI-")) == 3
    assert sum(1 for c in codes if c.startswith("AGT-EXF-")) == 3
    assert sum(1 for c in codes if c.startswith("AGT-MIS-")) == 3
    assert sum(1 for c in codes if c.startswith("AGT-FIN-")) == 2
    assert sum(1 for c in codes if c.startswith("AGT-PII-")) == 2
    assert sum(1 for c in codes if c.startswith("AGT-GOV-")) == 3


def test_every_code_has_definition():
    for code in IncidentCode:
        assert code in DEFINITIONS, f"Missing definition for {code}"
        assert DEFINITIONS[code].code == code


def test_definitions_count_matches_codes():
    assert len(DEFINITIONS) == len(list(IncidentCode))


# ---------------------------------------------------------------------------
# Field-level quality gates
# ---------------------------------------------------------------------------

def test_every_definition_has_required_fields():
    for code, defn in DEFINITIONS.items():
        assert defn.name, f"{code}: empty name"
        assert defn.description, f"{code}: empty description"
        assert 1 <= defn.severity <= 10, f"{code}: severity {defn.severity} out of [1,10]"
        assert len(defn.detection_signals) >= 1, f"{code}: no detection signals"
        assert len(defn.default_djl_rule_ids) >= 1, f"{code}: no DJL rule IDs"
        assert len(defn.default_compliance_refs) >= 1, f"{code}: no compliance refs"


def test_compliance_refs_format():
    """All compliance refs must follow <FRAMEWORK>:<CONTROL_ID> format."""
    for code, defn in DEFINITIONS.items():
        for ref in defn.default_compliance_refs:
            assert ":" in ref, f"{code}: compliance ref '{ref}' missing ':' separator"
            framework, control = ref.split(":", 1)
            assert framework, f"{code}: empty framework in ref '{ref}'"
            assert control, f"{code}: empty control ID in ref '{ref}'"


def test_djl_rule_ids_format():
    """DJL rule IDs must follow DJL-CAT-NNN pattern."""
    import re
    pattern = re.compile(r"^DJL-[A-Z]+-\d{3}$")
    for code, defn in DEFINITIONS.items():
        for rule_id in defn.default_djl_rule_ids:
            assert pattern.match(rule_id), (
                f"{code}: rule ID '{rule_id}' does not match DJL-CAT-NNN pattern"
            )


def test_severity_distribution_reasonable():
    """No incident should have severity below 7 — all are high-risk agentic events."""
    for code, defn in DEFINITIONS.items():
        assert defn.severity >= 7, (
            f"{code}: severity {defn.severity} < 7 — all agentic incidents are high-risk"
        )


def test_definitions_frozen():
    """IncidentDefinition must be frozen (immutable at runtime)."""
    defn = DEFINITIONS[IncidentCode.AGT_PI_OVERRIDE]
    with pytest.raises((AttributeError, TypeError)):
        defn.severity = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Specific known codes
# ---------------------------------------------------------------------------

def test_pi_override_signals_include_ignore_previous():
    defn = DEFINITIONS[IncidentCode.AGT_PI_OVERRIDE]
    signals = [s.lower() for s in defn.detection_signals]
    assert any("ignore" in s for s in signals)


def test_gov_human_oversight_refs_eu_ai_act_art14():
    defn = DEFINITIONS[IncidentCode.AGT_GOV_HUMAN_OVERSIGHT_BYPASS]
    assert "EU-AI-ACT:Art-14" in defn.default_compliance_refs


def test_mis_destructive_severity_is_10():
    defn = DEFINITIONS[IncidentCode.AGT_MIS_DESTRUCTIVE]
    assert defn.severity == 10


def test_gov_audit_tampering_severity_is_10():
    defn = DEFINITIONS[IncidentCode.AGT_GOV_AUDIT_TAMPERING]
    assert defn.severity == 10


def test_pi_indirect_severity_higher_than_pi_roleplay():
    """Indirect injection (supply-chain attack) is more severe than roleplay."""
    assert (
        DEFINITIONS[IncidentCode.AGT_PI_INDIRECT].severity
        >= DEFINITIONS[IncidentCode.AGT_PI_ROLEPLAY].severity
    )


def test_code_values_unique():
    values = [c.value for c in IncidentCode]
    assert len(values) == len(set(values)), "Duplicate IncidentCode values detected"


def test_strenum_values_are_strings():
    for code in IncidentCode:
        assert isinstance(code.value, str)
        assert code == code.value  # StrEnum contract
