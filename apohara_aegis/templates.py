# SPDX-License-Identifier: Apache-2.0
"""
6 industry-specific configuration templates for Apohara PROBANT deployment.

Templates pre-configure the SOAR pipeline, DJL rules, and compliance checks
for common regulated verticals without requiring manual policy authoring.

Each IndustryTemplate is a frozen dataclass listing:
  - regulatory_refs  : tuples of framework identifiers
  - default_djl_rule_subset : DJL rule IDs (resolved by djl.py, US-72)
  - mandatory_incident_codes : codes from taxonomy.py that MUST trigger alerts
  - default_compliance_report_sections : report chapter names for that vertical
  - description : 1-3 sentence human-readable summary

Part of the Apohara PROBANT Fusion Sprint (2026-05-18).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .taxonomy import IncidentCode, DEFINITIONS as TAXONOMY  # noqa: F401 — TAXONOMY re-exported


# ---------------------------------------------------------------------------
# Template dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndustryTemplate:
    """Immutable deployment configuration for a regulated industry vertical."""

    name: str
    """Human-readable vertical name (e.g. "Finance")."""

    regulatory_refs: tuple[str, ...]
    """Tuple of framework identifiers (e.g. "PCI-DSS-4.0", "SOX", "GLBA")."""

    default_djl_rule_subset: tuple[str, ...]
    """DJL rule IDs from djl.py activated by default for this vertical.
    Format: DJL-<CAT>-<NNN>.  US-86 CI gate cross-resolves these."""

    mandatory_incident_codes: tuple[IncidentCode, ...]
    """Taxonomy codes that must always fire an alert regardless of threshold."""

    default_compliance_report_sections: tuple[str, ...]
    """Ordered chapter names included in compliance evidence exports."""

    description: str
    """1-3 sentences describing the vertical and its key risk concerns."""


# ---------------------------------------------------------------------------
# 6 Industry Templates
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, IndustryTemplate] = {

    # ── Finance ────────────────────────────────────────────────────────────
    "finance": IndustryTemplate(
        name="Finance",
        regulatory_refs=(
            "PCI-DSS-4.0",
            "SOX",
            "GLBA",
            "EU-MIFID-II",
            "FinCEN-31-CFR-1020",
            "NIST-SP-800-53",
        ),
        default_djl_rule_subset=(
            "DJL-PI-001",
            "DJL-PI-002",
            "DJL-PI-003",
            "DJL-FIN-001",
            "DJL-FIN-002",
            "DJL-FIN-003",
            "DJL-EXF-002",
            "DJL-EXF-003",
            "DJL-PII-002",
            "DJL-PII-003",
            "DJL-POL-002",
            "DJL-POL-003",
            "DJL-POL-006",
        ),
        mandatory_incident_codes=(
            IncidentCode.AGT_FIN_HIGH_VALUE_TRANSFER,
            IncidentCode.AGT_FIN_FRAUD_PATTERN,
            IncidentCode.AGT_GOV_AUDIT_TAMPERING,
            IncidentCode.AGT_PII_LEAKAGE,
            IncidentCode.AGT_EXF_NETWORK,
        ),
        default_compliance_report_sections=(
            "PCI-DSS cardholder data flow audit",
            "SOX financial reporting controls (Section 404)",
            "AML transaction monitoring (FinCEN structuring detection)",
            "GLBA data-sharing consent evidence",
            "High-value transfer dual-control log",
        ),
        description=(
            "Banks, broker-dealers, payment processors, and fintech platforms. "
            "Stricter on AGT-FIN-* codes and PII leakage; requires audit-tamper "
            "resistance for SOX 404 compliance and AML structuring detection for "
            "FinCEN obligations."
        ),
    ),

    # ── Healthcare ─────────────────────────────────────────────────────────
    "healthcare": IndustryTemplate(
        name="Healthcare",
        regulatory_refs=(
            "HIPAA-Privacy-Rule",
            "HIPAA-Security-Rule",
            "HITECH",
            "21-CFR-Part-11",
            "NIST-SP-800-66",
            "EU-MDR-2017-745",
        ),
        default_djl_rule_subset=(
            "DJL-PI-001",
            "DJL-PI-002",
            "DJL-PI-006",
            "DJL-PII-001",
            "DJL-PII-002",
            "DJL-PII-003",
            "DJL-PII-004",
            "DJL-EXF-001",
            "DJL-EXF-004",
            "DJL-MIS-001",
            "DJL-POL-004",
            "DJL-POL-006",
            "DJL-POL-007",
        ),
        mandatory_incident_codes=(
            IncidentCode.AGT_PII_LEAKAGE,
            IncidentCode.AGT_PII_RECONSTRUCTION,
            IncidentCode.AGT_EXF_PII_AGGREGATION,
            IncidentCode.AGT_GOV_HUMAN_OVERSIGHT_BYPASS,
            IncidentCode.AGT_MIS_DESTRUCTIVE,
        ),
        default_compliance_report_sections=(
            "HIPAA PHI access and disclosure log",
            "Breach notification assessment (HITECH §13402)",
            "21-CFR-Part-11 electronic records audit trail",
            "De-identification validation (Safe Harbor vs. Expert Determination)",
            "Human-in-the-loop gate evidence for clinical decision support",
        ),
        description=(
            "Hospitals, health insurers, clinical decision-support tools, and "
            "medical device software. HIPAA PHI handling and de-identification "
            "validation are primary concerns; EU MDR applies when AI is embedded "
            "in regulated medical devices."
        ),
    ),

    # ── Government ─────────────────────────────────────────────────────────
    "government": IndustryTemplate(
        name="Government",
        regulatory_refs=(
            "FedRAMP-Moderate",
            "FISMA",
            "NIST-SP-800-53-Rev5",
            "NIST-SP-800-171",
            "CISA-Zero-Trust-Maturity",
            "EO-14028",
        ),
        default_djl_rule_subset=(
            "DJL-PI-001",
            "DJL-PI-002",
            "DJL-PI-003",
            "DJL-PI-006",
            "DJL-PI-007",
            "DJL-EXF-001",
            "DJL-EXF-002",
            "DJL-EXF-003",
            "DJL-MIS-003",
            "DJL-MIS-004",
            "DJL-POL-004",
            "DJL-POL-005",
            "DJL-POL-006",
            "DJL-POL-007",
        ),
        mandatory_incident_codes=(
            IncidentCode.AGT_PI_INDIRECT,
            IncidentCode.AGT_MIS_PRIVILEGE_ESCALATION,
            IncidentCode.AGT_GOV_POLICY_BYPASS,
            IncidentCode.AGT_GOV_AUDIT_TAMPERING,
            IncidentCode.AGT_GOV_HUMAN_OVERSIGHT_BYPASS,
        ),
        default_compliance_report_sections=(
            "FedRAMP continuous monitoring evidence",
            "FISMA annual security assessment artifacts",
            "NIST SP 800-53 Rev5 control satisfaction matrix",
            "Privilege escalation attempt log (AC-6)",
            "Audit log integrity chain (AU-9 tamper-evidence)",
        ),
        description=(
            "Federal agencies, defence contractors, and critical infrastructure "
            "operators under FISMA. FedRAMP Moderate authorization controls and "
            "EO-14028 zero-trust requirements drive mandatory audit-tamper and "
            "privilege escalation monitoring."
        ),
    ),

    # ── Retail ─────────────────────────────────────────────────────────────
    "retail": IndustryTemplate(
        name="Retail",
        regulatory_refs=(
            "PCI-DSS-4.0",
            "CCPA",
            "GDPR",
            "CAN-SPAM",
            "FTC-Act-Section-5",
        ),
        default_djl_rule_subset=(
            "DJL-PI-001",
            "DJL-PI-002",
            "DJL-SQLI-001",
            "DJL-PII-001",
            "DJL-PII-002",
            "DJL-PII-003",
            "DJL-EXF-002",
            "DJL-EXF-004",
            "DJL-MIS-005",
            "DJL-POL-003",
            "DJL-POL-004",
        ),
        mandatory_incident_codes=(
            IncidentCode.AGT_PII_LEAKAGE,
            IncidentCode.AGT_EXF_PII_AGGREGATION,
            IncidentCode.AGT_FIN_FRAUD_PATTERN,
            IncidentCode.AGT_MIS_UNAUTHORIZED_TRANSACTION,
        ),
        default_compliance_report_sections=(
            "PCI-DSS cardholder data environment scope",
            "CCPA consumer rights request log",
            "GDPR data subject access request evidence",
            "Fraud pattern and velocity anomaly summary",
        ),
        description=(
            "E-commerce, brick-and-mortar chains, and marketplace platforms. "
            "PCI-DSS governs payment card data; CCPA and GDPR mandate consumer "
            "rights controls; fraud pattern detection is critical for "
            "AI-assisted checkout and promotions abuse."
        ),
    ),

    # ── Manufacturing ──────────────────────────────────────────────────────
    "manufacturing": IndustryTemplate(
        name="Manufacturing",
        regulatory_refs=(
            "NIST-CSF-2.0",
            "IEC-62443-3-3",
            "ISO-27001-2022",
            "CMMC-2.0-Level2",
            "EU-CRA-2024",
        ),
        default_djl_rule_subset=(
            "DJL-PI-001",
            "DJL-PI-003",
            "DJL-PI-006",
            "DJL-MIS-001",
            "DJL-MIS-002",
            "DJL-MIS-003",
            "DJL-MIS-004",
            "DJL-EXF-002",
            "DJL-EXF-003",
            "DJL-POL-001",
            "DJL-POL-005",
            "DJL-POL-006",
        ),
        mandatory_incident_codes=(
            IncidentCode.AGT_MIS_DESTRUCTIVE,
            IncidentCode.AGT_MIS_PRIVILEGE_ESCALATION,
            IncidentCode.AGT_MIS_UNAUTHORIZED_TRANSACTION,
            IncidentCode.AGT_PI_INDIRECT,
            IncidentCode.AGT_EXF_NETWORK,
        ),
        default_compliance_report_sections=(
            "IEC 62443-3-3 OT network segmentation evidence",
            "NIST CSF 2.0 Respond function incident timeline",
            "CMMC Level 2 access control attestation",
            "Destructive command invocation log",
            "OT/IT boundary crossing anomalies",
        ),
        description=(
            "Discrete and process manufacturers, smart factory OT/IT convergence, "
            "and defence supply-chain operators. IEC 62443 OT segmentation and "
            "CMMC defence-contractor requirements drive privilege escalation and "
            "destructive command monitoring."
        ),
    ),

    # ── Energy ─────────────────────────────────────────────────────────────
    "energy": IndustryTemplate(
        name="Energy",
        regulatory_refs=(
            "NERC-CIP-013-2",
            "IEC-62443-2-1",
            "NIST-SP-800-82-Rev3",
            "EU-NIS2-2022",
            "TSA-Security-Directive-2B",
        ),
        default_djl_rule_subset=(
            "DJL-PI-001",
            "DJL-PI-003",
            "DJL-PI-006",
            "DJL-PI-007",
            "DJL-MIS-001",
            "DJL-MIS-002",
            "DJL-MIS-003",
            "DJL-MIS-004",
            "DJL-EXF-002",
            "DJL-EXF-003",
            "DJL-POL-004",
            "DJL-POL-005",
            "DJL-POL-006",
            "DJL-POL-007",
        ),
        mandatory_incident_codes=(
            IncidentCode.AGT_MIS_DESTRUCTIVE,
            IncidentCode.AGT_MIS_PRIVILEGE_ESCALATION,
            IncidentCode.AGT_GOV_POLICY_BYPASS,
            IncidentCode.AGT_GOV_AUDIT_TAMPERING,
            IncidentCode.AGT_PI_INDIRECT,
        ),
        default_compliance_report_sections=(
            "NERC CIP-013 supply-chain risk management evidence",
            "IEC 62443-2-1 ICS security management evidence",
            "NIST SP 800-82 ICS asset inventory and patch status",
            "EU NIS2 incident report (72-hour notification timeline)",
            "TSA Security Directive 2B cybersecurity architecture assessment",
        ),
        description=(
            "Electric utilities, oil & gas pipelines, and renewable energy "
            "operators. NERC CIP governs bulk electric system cybersecurity; "
            "IEC 62443 applies to ICS/SCADA control systems; EU NIS2 mandates "
            "72-hour incident notification for critical infrastructure operators."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Sanity assertion — evaluated at import time
# ---------------------------------------------------------------------------
assert len(TEMPLATES) == 6, (
    f"Industry template integrity failure: expected 6 templates, found {len(TEMPLATES)}."
)

for _name, _tpl in TEMPLATES.items():
    assert len(_tpl.mandatory_incident_codes) >= 1, (
        f"Template '{_name}' must have ≥1 mandatory_incident_codes."
    )
    assert len(_tpl.default_djl_rule_subset) >= 5, (
        f"Template '{_name}' must have ≥5 default_djl_rule_subset entries."
    )
    assert len(_tpl.regulatory_refs) >= 3, (
        f"Template '{_name}' must have ≥3 regulatory_refs."
    )
    assert len(_tpl.default_compliance_report_sections) >= 2, (
        f"Template '{_name}' must have ≥2 default_compliance_report_sections."
    )
