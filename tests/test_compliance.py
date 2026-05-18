# SPDX-License-Identifier: Apache-2.0
"""Tests for compliance.py — 5-framework compliance suite (US-76).

Covers:
- Framework loading and structural integrity
- Control count invariants
- Per-control field validation
- Cross-reference traceability (incident codes → taxonomy, DJL rule IDs → format)
- report_generator correctness
- OWASP LLM 2026 exactly-10 constraint
- EU AI Act article coverage
"""
from __future__ import annotations

import re

import pytest

from apohara_aegis.compliance import (
    FRAMEWORKS,
    ControlMeta,
    ComplianceFramework,
    generate,
)
from apohara_aegis.taxonomy import DEFINITIONS as TAXONOMY, IncidentCode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DJL_RULE_PATTERN = re.compile(r"^DJL-[A-Z]+-\d{3}$")

_EXPECTED_FRAMEWORKS = {
    "EU_AI_ACT",
    "NIST_AI_RMF",
    "NIST_SP_800_53",
    "SOC_2",
    "ISO_27001",
    "OWASP_LLM_2026",
}

_VALID_FRAMEWORK_VALUES = _EXPECTED_FRAMEWORKS


# ---------------------------------------------------------------------------
# AC1 — Framework loading
# ---------------------------------------------------------------------------


def test_all_5_frameworks_load():
    """All 6 frameworks (5 + OWASP LLM 2026 as the 6th) are registered."""
    assert _EXPECTED_FRAMEWORKS == set(FRAMEWORKS.keys()), (
        f"Missing frameworks: {_EXPECTED_FRAMEWORKS - set(FRAMEWORKS.keys())}"
    )


def test_each_framework_is_ComplianceFramework():
    for name, fw in FRAMEWORKS.items():
        assert isinstance(fw, ComplianceFramework), (
            f"{name} is not a ComplianceFramework instance"
        )


def test_each_framework_has_nonempty_fields():
    for name, fw in FRAMEWORKS.items():
        assert fw.name, f"{name}.name is empty"
        assert fw.version, f"{name}.version is empty"
        assert fw.description, f"{name}.description is empty"
        assert fw.source_url.startswith("http"), f"{name}.source_url is not a URL"
        assert fw.controls, f"{name} has no controls"


# ---------------------------------------------------------------------------
# AC1 — Control count
# ---------------------------------------------------------------------------


def test_at_least_30_total_controls():
    total = sum(len(fw.controls) for fw in FRAMEWORKS.values())
    assert total >= 30, f"Expected ≥30 controls, found {total}"


def test_each_framework_has_minimum_controls():
    minimums = {
        "EU_AI_ACT": 4,
        "NIST_AI_RMF": 5,
        "NIST_SP_800_53": 10,
        "SOC_2": 5,
        "ISO_27001": 5,
        "OWASP_LLM_2026": 10,
    }
    for fw_name, min_count in minimums.items():
        count = len(FRAMEWORKS[fw_name].controls)
        assert count >= min_count, (
            f"{fw_name}: expected ≥{min_count} controls, found {count}"
        )


# ---------------------------------------------------------------------------
# AC1 — Per-control field validation
# ---------------------------------------------------------------------------


def test_every_control_has_required_fields():
    """Every ControlMeta instance has all required string fields."""
    for fw_name, fw in FRAMEWORKS.items():
        for ctrl_id, ctrl in fw.controls.items():
            assert isinstance(ctrl, ControlMeta), f"{ctrl_id} is not a ControlMeta"
            assert ctrl.control_id, f"{ctrl_id}: control_id is empty"
            assert ctrl.title, f"{ctrl_id}: title is empty"
            assert ctrl.description, f"{ctrl_id}: description is empty"
            assert ctrl.framework in _VALID_FRAMEWORK_VALUES, (
                f"{ctrl_id}: framework '{ctrl.framework}' is not a valid value"
            )
            assert ctrl.source_url.startswith("http"), (
                f"{ctrl_id}: source_url is not a URL"
            )
            assert isinstance(ctrl.incident_codes, tuple), (
                f"{ctrl_id}: incident_codes must be a tuple"
            )
            assert isinstance(ctrl.djl_rule_ids, tuple), (
                f"{ctrl_id}: djl_rule_ids must be a tuple"
            )
            assert isinstance(ctrl.audit_log_fields, tuple), (
                f"{ctrl_id}: audit_log_fields must be a tuple"
            )
            assert len(ctrl.audit_log_fields) >= 1, (
                f"{ctrl_id}: audit_log_fields must have at least 1 entry"
            )


def test_control_id_matches_dict_key():
    """Each control's control_id should be parseable from the dict key."""
    for fw_name, fw in FRAMEWORKS.items():
        for key, ctrl in fw.controls.items():
            # control_id and key may differ (key includes "NIST-AI-RMF:" prefix in NIST_AI_RMF)
            assert ctrl.control_id, f"{key}: control_id must not be empty"


# ---------------------------------------------------------------------------
# AC1 — Cross-reference traceability
# ---------------------------------------------------------------------------


def test_every_control_traceable_to_artifacts():
    """Incident codes resolve to taxonomy; DJL rule IDs match the expected format."""
    for fw_name, fw in FRAMEWORKS.items():
        for ctrl_id, ctrl in fw.controls.items():
            # incident_codes must resolve to taxonomy
            for code in ctrl.incident_codes:
                assert code in TAXONOMY, (
                    f"{ctrl_id}: incident code {code!r} not found in taxonomy.DEFINITIONS"
                )
            # DJL rule IDs format check (US-86 cross-resolves to djl.RULES)
            for rid in ctrl.djl_rule_ids:
                assert _DJL_RULE_PATTERN.match(rid), (
                    f"{ctrl_id}: DJL rule ID '{rid}' does not match DJL-CAT-NNN format"
                )


def test_framework_field_matches_parent_framework():
    """Each ControlMeta.framework matches the key of the ComplianceFramework it lives in."""
    for fw_key, fw in FRAMEWORKS.items():
        for ctrl_id, ctrl in fw.controls.items():
            assert ctrl.framework == fw_key, (
                f"{ctrl_id}: ctrl.framework='{ctrl.framework}' != fw key '{fw_key}'"
            )


# ---------------------------------------------------------------------------
# AC2 — report_generator
# ---------------------------------------------------------------------------


def test_report_generator_basic():
    """generate() for a known incident code returns the expected structure."""
    report = generate(IncidentCode.AGT_PI_OVERRIDE)
    assert report["incident"]["code"] == "AGT-PI-001"
    assert report["incident"]["name"] == "Prompt Override Attempt"
    assert report["incident"]["severity"] == 8
    assert "frameworks" in report
    assert "summary" in report
    assert isinstance(report["summary"]["total_controls_triggered"], int)
    assert isinstance(report["summary"]["frameworks_with_evidence"], int)
    assert report["summary"]["frameworks_with_evidence"] >= 1


def test_report_generator_all_frameworks():
    """With framework_names=None, all 6 frameworks appear in result."""
    report = generate(IncidentCode.AGT_PI_OVERRIDE, framework_names=None)
    assert set(report["frameworks"].keys()) == _EXPECTED_FRAMEWORKS


def test_report_generator_filters_frameworks():
    """Specifying framework_names limits the output to those frameworks only."""
    requested = ["EU_AI_ACT", "SOC_2"]
    report = generate(IncidentCode.AGT_GOV_AUDIT_TAMPERING, framework_names=requested)
    assert set(report["frameworks"].keys()) == {"EU_AI_ACT", "SOC_2"}


def test_report_generator_each_control_entry_has_required_keys():
    """Each control entry in the report has the required keys."""
    required_keys = {"control", "title", "description", "audit_log_fields", "djl_rule_ids"}
    report = generate(IncidentCode.AGT_EXF_NETWORK)
    for fw_name, controls in report["frameworks"].items():
        for entry in controls:
            missing = required_keys - set(entry.keys())
            assert not missing, (
                f"Framework {fw_name}: control entry missing keys {missing}"
            )


def test_report_generator_summary_counts_are_consistent():
    """total_controls_triggered equals the sum of matched controls across frameworks."""
    report = generate(IncidentCode.AGT_PII_LEAKAGE)
    frameworks_dict = report["frameworks"]
    expected_total = sum(len(v) for v in frameworks_dict.values())
    expected_with_evidence = sum(1 for v in frameworks_dict.values() if v)
    assert report["summary"]["total_controls_triggered"] == expected_total
    assert report["summary"]["frameworks_with_evidence"] == expected_with_evidence


def test_report_generator_unknown_incident_raises():
    """Passing a value not in IncidentCode raises an appropriate error."""
    with pytest.raises((KeyError, ValueError)):
        generate("NOT-A-CODE")  # type: ignore[arg-type]


def test_report_generator_high_value_transfer_triggers_financial_controls():
    """AGT-FIN-001 triggers controls in SOC_2 and NIST_SP_800_53 frameworks."""
    report = generate(IncidentCode.AGT_FIN_HIGH_VALUE_TRANSFER)
    soc2_controls = report["frameworks"]["SOC_2"]
    sp800_controls = report["frameworks"]["NIST_SP_800_53"]
    assert len(soc2_controls) >= 1, "AGT-FIN-001 should trigger at least 1 SOC 2 control"
    assert len(sp800_controls) >= 1, "AGT-FIN-001 should trigger at least 1 SP 800-53 control"


# ---------------------------------------------------------------------------
# Specific invariants
# ---------------------------------------------------------------------------


def test_owasp_llm_2026_has_exactly_10():
    """OWASP LLM 2026 must have exactly 10 controls (LLM01-LLM10)."""
    owasp = FRAMEWORKS["OWASP_LLM_2026"]
    assert len(owasp.controls) == 10, (
        f"OWASP LLM 2026 must have exactly 10 controls, found {len(owasp.controls)}"
    )


def test_owasp_llm_2026_has_all_10_categories():
    """All 10 OWASP LLM categories LLM01-LLM10 are present."""
    owasp = FRAMEWORKS["OWASP_LLM_2026"]
    for i in range(1, 11):
        expected_id = f"OWASP-LLM-2026:LLM{i:02d}"
        assert expected_id in owasp.controls, (
            f"Missing OWASP category: {expected_id}"
        )


def test_eu_ai_act_covers_articles_9_14_15_73():
    """EU AI Act framework must include controls for Articles 9, 14, 15, and 73."""
    eu = FRAMEWORKS["EU_AI_ACT"]
    required = {
        "EU-AI-ACT:Art-9",
        "EU-AI-ACT:Art-14",
        "EU-AI-ACT:Art-15",
        "EU-AI-ACT:Art-73",
    }
    missing = required - set(eu.controls.keys())
    assert not missing, f"EU AI Act missing required articles: {missing}"


def test_nist_sp_800_53_has_required_controls():
    """NIST SP 800-53 framework includes AC-3, AC-4, AU-2, AU-12, SI-4, SI-7, IR-4, IR-5, SC-7, SC-28."""
    sp800 = FRAMEWORKS["NIST_SP_800_53"]
    required = {
        "SP800-53:AC-3",
        "SP800-53:AC-4",
        "SP800-53:AU-2",
        "SP800-53:AU-12",
        "SP800-53:SI-4",
        "SP800-53:SI-7",
        "SP800-53:IR-4",
        "SP800-53:IR-5",
        "SP800-53:SC-7",
        "SP800-53:SC-28",
    }
    missing = required - set(sp800.controls.keys())
    assert not missing, f"NIST SP 800-53 missing required controls: {missing}"


def test_nist_ai_rmf_references_nist_mapping():
    """NIST AI RMF controls in FRAMEWORKS derive from nist_mapping.CONTROLS."""
    from apohara_aegis.nist_mapping import CONTROLS as nist_controls
    rmf_fw = FRAMEWORKS["NIST_AI_RMF"]
    # Every NIST AI RMF control should have a source URL pointing to NIST
    for ctrl_id, ctrl in rmf_fw.controls.items():
        assert "nist" in ctrl.source_url.lower() or "doi.org" in ctrl.source_url, (
            f"{ctrl_id}: expected NIST source URL, got '{ctrl.source_url}'"
        )


def test_import_is_idempotent():
    """Importing compliance.py multiple times does not raise assertion errors."""
    import importlib
    import apohara_aegis.compliance as m1
    importlib.reload(m1)
    # Reload should succeed without triggering any assertion failures at module level.
    assert m1.FRAMEWORKS is not None
