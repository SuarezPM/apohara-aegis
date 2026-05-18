# SPDX-License-Identifier: Apache-2.0
"""
Compliance suite mapping — 5 regulatory frameworks aligned to PROBANT
incidents, DJL rules, and audit log fields.

Frameworks:
- EU AI Act (Articles 9, 14, 15, 73 — high-risk AI system obligations)
- NIST AI RMF 1.0 (base 19 subcategories, via nist_mapping.CONTROLS)
- NIST SP 800-53 Rev 5 (controls applicable to AI agent governance)
- SOC 2 Type II (Trust Services Criteria — Security, Availability, Confidentiality)
- ISO/IEC 27001:2022 (Information Security Management System)
- OWASP LLM 2026 Top 10 (LLM01-LLM10)

Honesty contract:
- "compliance mapping" != certification. This module maps Apohara PROBANT
  artifacts to control requirements. Certification (SOC 2 Type II, ISO 27001)
  requires a 6-12 month engagement with an accredited auditor.
- EU AI Act applicability depends on whether PROBANT is deployed in the EU
  and classified as "high-risk" under Annex III — consult legal counsel.
- NIST AI RMF entries reference the base NIST AI 100-1 framework (Jan 2023)
  plus the CSA Agentic Profile draft (March 2026, not yet officially published
  by NIST). See nist_mapping.py and docs/research/prior-art-nist-agentic-profile.md
  for the honesty caveat on draft status.

Part of the Apohara PROBANT Fusion Sprint (2026-05-18).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from .nist_mapping import CONTROLS as _NIST_CONTROLS
from .taxonomy import DEFINITIONS as TAXONOMY, IncidentCode


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlMeta:
    """A single compliance control mapped to PROBANT artifacts."""

    control_id: str
    """Unique control ID e.g. "EU-AI-ACT:Art-14"."""

    title: str
    """Short human-readable control title."""

    description: str
    """Normative statement of the control requirement (1-2 sentences)."""

    framework: str
    """One of: EU_AI_ACT | NIST_AI_RMF | NIST_SP_800_53 | SOC_2 | ISO_27001 | OWASP_LLM_2026."""

    incident_codes: tuple[IncidentCode, ...]
    """taxonomy.IncidentCode entries that trigger evidence collection."""

    djl_rule_ids: tuple[str, ...]
    """DJL rule IDs from djl.py that enforce this control."""

    audit_log_fields: tuple[str, ...]
    """JSONL audit-log field paths where evidence for this control is written."""

    source_url: str
    """Primary normative reference URL."""


@dataclass(frozen=True)
class ComplianceFramework:
    """A compliance framework with versioned controls."""

    name: str
    version: str
    description: str
    controls: dict[str, ControlMeta]
    source_url: str


# ---------------------------------------------------------------------------
# EU AI Act controls  (≥4 — Articles 9, 14, 15, 73)
# ---------------------------------------------------------------------------

_EU_AI_ACT_CONTROLS: dict[str, ControlMeta] = {

    "EU-AI-ACT:Art-9": ControlMeta(
        control_id="EU-AI-ACT:Art-9",
        title="Risk Management System",
        description=(
            "High-risk AI systems shall have a risk management system in place "
            "establishing, implementing, documenting, and maintaining a continuous "
            "iterative risk management process throughout the lifecycle."
        ),
        framework="EU_AI_ACT",
        incident_codes=(
            IncidentCode.AGT_GOV_POLICY_BYPASS,
            IncidentCode.AGT_MIS_DESTRUCTIVE,
            IncidentCode.AGT_PI_ROLEPLAY,
        ),
        djl_rule_ids=("DJL-POL-004", "DJL-POL-005", "DJL-MIS-001", "DJL-MIS-002"),
        audit_log_fields=("verdict.djl.matched_rules", "governance.risk_register"),
        source_url="https://artificialintelligenceact.eu/article/9/",
    ),

    "EU-AI-ACT:Art-14": ControlMeta(
        control_id="EU-AI-ACT:Art-14",
        title="Human Oversight",
        description=(
            "High-risk AI systems shall be designed and developed with human oversight "
            "measures enabling natural persons to effectively oversee and intervene "
            "during use; systems must be able to halt operation."
        ),
        framework="EU_AI_ACT",
        incident_codes=(
            IncidentCode.AGT_GOV_HUMAN_OVERSIGHT_BYPASS,
            IncidentCode.AGT_MIS_UNAUTHORIZED_TRANSACTION,
        ),
        djl_rule_ids=("DJL-POL-007",),
        audit_log_fields=(
            "verdict.hitl.gate_triggered",
            "verdict.hitl.escalation_ticket_id",
        ),
        source_url="https://artificialintelligenceact.eu/article/14/",
    ),

    "EU-AI-ACT:Art-15": ControlMeta(
        control_id="EU-AI-ACT:Art-15",
        title="Accuracy, Robustness and Cybersecurity",
        description=(
            "High-risk AI systems shall achieve an appropriate level of accuracy, "
            "robustness and cybersecurity; they shall be resilient against attempts "
            "by unauthorised third parties to alter use, outputs, or performance."
        ),
        framework="EU_AI_ACT",
        incident_codes=(
            IncidentCode.AGT_PI_OVERRIDE,
            IncidentCode.AGT_PI_INDIRECT,
            IncidentCode.AGT_EXF_DUMP,
        ),
        djl_rule_ids=("DJL-PI-001", "DJL-PI-002", "DJL-PI-006", "DJL-PI-007", "DJL-SQLI-001"),
        audit_log_fields=(
            "metrics.adversarial_test_results",
            "metrics.jbb_defense_score",
            "verdict.djl.matched_rules",
        ),
        source_url="https://artificialintelligenceact.eu/article/15/",
    ),

    "EU-AI-ACT:Art-73": ControlMeta(
        control_id="EU-AI-ACT:Art-73",
        title="Serious Incident Reporting",
        description=(
            "Providers of high-risk AI systems shall report any serious incidents "
            "to market surveillance authorities of the Member States where the "
            "incident occurred without undue delay."
        ),
        framework="EU_AI_ACT",
        incident_codes=(
            IncidentCode.AGT_GOV_AUDIT_TAMPERING,
            IncidentCode.AGT_EXF_NETWORK,
            IncidentCode.AGT_FIN_HIGH_VALUE_TRANSFER,
        ),
        djl_rule_ids=("DJL-EXF-002", "DJL-EXF-003", "DJL-MIS-006"),
        audit_log_fields=("soar.incident_ticket_id", "soar.playbook_execution_log"),
        source_url="https://artificialintelligenceact.eu/article/73/",
    ),

    "EU-AI-ACT:Art-12": ControlMeta(
        control_id="EU-AI-ACT:Art-12",
        title="Record-Keeping and Logging",
        description=(
            "High-risk AI systems shall have logging capabilities enabling automatic "
            "recording of events; logs shall be kept for a period appropriate to the "
            "system's intended purpose and legal obligations."
        ),
        framework="EU_AI_ACT",
        incident_codes=(
            IncidentCode.AGT_GOV_AUDIT_TAMPERING,
        ),
        djl_rule_ids=("DJL-POL-006",),
        audit_log_fields=("verdict.audit.hmac_chain_valid", "soar.lessons_learned_doc_ref"),
        source_url="https://artificialintelligenceact.eu/article/12/",
    ),
}


# ---------------------------------------------------------------------------
# NIST AI RMF controls — reference nist_mapping.CONTROLS for the agentic subset
# ---------------------------------------------------------------------------
#
# We expose a curated subset of the 35 controls already in nist_mapping.py
# rather than duplicating them. Each ControlMeta here acts as a bridge adapter.
# ---------------------------------------------------------------------------

def _rmf_from_agentic(ctrl_id: str) -> ControlMeta:
    """Adapt an AgenticControl from nist_mapping.CONTROLS to ControlMeta."""
    ac = _NIST_CONTROLS[ctrl_id]
    return ControlMeta(
        control_id=f"NIST-AI-RMF:{ctrl_id}",
        title=ac.title,
        description=ac.description,
        framework="NIST_AI_RMF",
        incident_codes=ac.apohara_incident_codes,
        djl_rule_ids=ac.apohara_djl_rule_ids,
        audit_log_fields=(ac.apohara_audit_log_field,),
        source_url="https://doi.org/10.6028/NIST.AI.100-1",
    )


# Select representative subset: 5 base RMF + 2 CSA Agentic extensions
_NIST_AI_RMF_CONTROLS: dict[str, ControlMeta] = {
    f"NIST-AI-RMF:{cid}": _rmf_from_agentic(cid)
    for cid in [
        "RMF-GOVERN-1.1",
        "RMF-GOVERN-1.7",
        "RMF-MEASURE-2.5",
        "RMF-MANAGE-2.2",
        "RMF-MANAGE-4.1",
        "AGENTIC-GOVERN-AUDIT-INTEGRITY",
        "AGENTIC-MAP-PROMPT-SURFACE",
        "AGENTIC-MANAGE-BLOCK-RESPONSE",
        "AGENTIC-MANAGE-SOAR-PLAYBOOK",
        "AGENTIC-MEASURE-PROMPT-INJECTION",
    ]
}


# ---------------------------------------------------------------------------
# NIST SP 800-53 Rev 5 controls  (≥10)
# ---------------------------------------------------------------------------

_NIST_SP_800_53_CONTROLS: dict[str, ControlMeta] = {

    "SP800-53:AC-3": ControlMeta(
        control_id="SP800-53:AC-3",
        title="Access Enforcement",
        description=(
            "The information system enforces approved authorizations for logical "
            "access to information and system resources in accordance with applicable "
            "access control policies."
        ),
        framework="NIST_SP_800_53",
        incident_codes=(
            IncidentCode.AGT_EXF_DUMP,
            IncidentCode.AGT_MIS_PRIVILEGE_ESCALATION,
        ),
        djl_rule_ids=("DJL-SQLI-001", "DJL-EXF-001", "DJL-MIS-003"),
        audit_log_fields=("verdict.djl.matched_rules", "agent.identity.authorization_scope"),
        source_url="https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/SP_800_53_5_1_0/home?element=AC-3",
    ),

    "SP800-53:AC-4": ControlMeta(
        control_id="SP800-53:AC-4",
        title="Information Flow Enforcement",
        description=(
            "The information system enforces approved authorizations for controlling "
            "the flow of information within the system and between interconnected "
            "systems based on information flow control policies."
        ),
        framework="NIST_SP_800_53",
        incident_codes=(
            IncidentCode.AGT_EXF_PII_AGGREGATION,
            IncidentCode.AGT_EXF_NETWORK,
        ),
        djl_rule_ids=("DJL-PII-001", "DJL-EXF-004", "DJL-EXF-002"),
        audit_log_fields=("pipeline.data_flow_manifest", "verdict.djl.matched_rules"),
        source_url="https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/SP_800_53_5_1_0/home?element=AC-4",
    ),

    "SP800-53:AU-2": ControlMeta(
        control_id="SP800-53:AU-2",
        title="Event Logging",
        description=(
            "The organization determines that the information system is capable of "
            "auditing events; coordinates the security audit function with other "
            "organizations requiring audit-related information."
        ),
        framework="NIST_SP_800_53",
        incident_codes=(
            IncidentCode.AGT_GOV_AUDIT_TAMPERING,
        ),
        djl_rule_ids=("DJL-POL-006",),
        audit_log_fields=("verdict.audit.hmac_chain_valid",),
        source_url="https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/SP_800_53_5_1_0/home?element=AU-2",
    ),

    "SP800-53:AU-12": ControlMeta(
        control_id="SP800-53:AU-12",
        title="Audit Record Generation",
        description=(
            "The information system generates audit records for events identified in "
            "AU-2, provides the capability to generate audit records for events on "
            "demand, and allows authorized individuals to select which events are audited."
        ),
        framework="NIST_SP_800_53",
        incident_codes=(
            IncidentCode.AGT_GOV_AUDIT_TAMPERING,
            IncidentCode.AGT_PI_OVERRIDE,
        ),
        djl_rule_ids=("DJL-POL-006", "DJL-PI-001"),
        audit_log_fields=("soar.playbook_execution_log", "soar.incident_ticket_id"),
        source_url="https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/SP_800_53_5_1_0/home?element=AU-12",
    ),

    "SP800-53:SI-4": ControlMeta(
        control_id="SP800-53:SI-4",
        title="System Monitoring",
        description=(
            "The organization monitors the information system to detect attacks and "
            "indicators of potential attacks, unauthorized connections, and unusual "
            "or unauthorized activities or conditions."
        ),
        framework="NIST_SP_800_53",
        incident_codes=(
            IncidentCode.AGT_PI_OVERRIDE,
            IncidentCode.AGT_EXF_NETWORK,
            IncidentCode.AGT_MIS_PRIVILEGE_ESCALATION,
        ),
        djl_rule_ids=("DJL-PI-001", "DJL-EXF-002", "DJL-MIS-003", "DJL-MIS-004"),
        audit_log_fields=("verdict.djl.matched_rules", "metrics.exfiltration_attempt_count"),
        source_url="https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/SP_800_53_5_1_0/home?element=SI-4",
    ),

    "SP800-53:SI-7": ControlMeta(
        control_id="SP800-53:SI-7",
        title="Software, Firmware, and Information Integrity",
        description=(
            "The organization employs integrity verification tools to detect "
            "unauthorized changes to software, firmware, and information; uses "
            "automated tools that provide notification upon discovering discrepancies."
        ),
        framework="NIST_SP_800_53",
        incident_codes=(
            IncidentCode.AGT_GOV_AUDIT_TAMPERING,
        ),
        djl_rule_ids=("DJL-POL-006",),
        audit_log_fields=("verdict.audit.hmac_chain_valid",),
        source_url="https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/SP_800_53_5_1_0/home?element=SI-7",
    ),

    "SP800-53:IR-4": ControlMeta(
        control_id="SP800-53:IR-4",
        title="Incident Handling",
        description=(
            "The organization implements an incident handling capability for security "
            "incidents that includes preparation, detection and analysis, containment, "
            "eradication, and recovery."
        ),
        framework="NIST_SP_800_53",
        incident_codes=(
            IncidentCode.AGT_PI_INDIRECT,
            IncidentCode.AGT_EXF_DUMP,
            IncidentCode.AGT_FIN_HIGH_VALUE_TRANSFER,
        ),
        djl_rule_ids=("DJL-EXF-001", "DJL-PI-006", "DJL-MIS-006"),
        audit_log_fields=("soar.playbook_execution_log", "soar.incident_ticket_id"),
        source_url="https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/SP_800_53_5_1_0/home?element=IR-4",
    ),

    "SP800-53:IR-5": ControlMeta(
        control_id="SP800-53:IR-5",
        title="Incident Monitoring",
        description=(
            "The organization tracks and documents information system security incidents "
            "to identify the nature, scope, and impact, and to determine recurrence."
        ),
        framework="NIST_SP_800_53",
        incident_codes=(
            IncidentCode.AGT_GOV_POLICY_BYPASS,
            IncidentCode.AGT_MIS_UNAUTHORIZED_TRANSACTION,
        ),
        djl_rule_ids=("DJL-POL-004", "DJL-POL-005", "DJL-MIS-005"),
        audit_log_fields=("soar.incident_ticket_id", "soar.lessons_learned_doc_ref"),
        source_url="https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/SP_800_53_5_1_0/home?element=IR-5",
    ),

    "SP800-53:SC-7": ControlMeta(
        control_id="SP800-53:SC-7",
        title="Boundary Protection",
        description=(
            "The information system monitors and controls communications at the "
            "external boundary of the system and at key internal boundaries; "
            "implements subnetworks for publicly accessible system components."
        ),
        framework="NIST_SP_800_53",
        incident_codes=(
            IncidentCode.AGT_EXF_NETWORK,
        ),
        djl_rule_ids=("DJL-EXF-002", "DJL-EXF-003"),
        audit_log_fields=("verdict.djl.matched_rules",),
        source_url="https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/SP_800_53_5_1_0/home?element=SC-7",
    ),

    "SP800-53:SC-28": ControlMeta(
        control_id="SP800-53:SC-28",
        title="Protection of Information at Rest",
        description=(
            "The information system protects the confidentiality and integrity of "
            "information at rest in organizational information systems, including "
            "portable digital media."
        ),
        framework="NIST_SP_800_53",
        incident_codes=(
            IncidentCode.AGT_PII_LEAKAGE,
            IncidentCode.AGT_EXF_DUMP,
        ),
        djl_rule_ids=("DJL-PII-002", "DJL-PII-003", "DJL-SQLI-001"),
        audit_log_fields=("soar.pii_quarantine_record",),
        source_url="https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/SP_800_53_5_1_0/home?element=SC-28",
    ),

    "SP800-53:AC-6": ControlMeta(
        control_id="SP800-53:AC-6",
        title="Least Privilege",
        description=(
            "The organization employs the concept of least privilege, allowing only "
            "authorized accesses required to accomplish assigned tasks; explicit "
            "authorizations are required for privileged access."
        ),
        framework="NIST_SP_800_53",
        incident_codes=(
            IncidentCode.AGT_MIS_PRIVILEGE_ESCALATION,
        ),
        djl_rule_ids=("DJL-MIS-003", "DJL-MIS-004"),
        audit_log_fields=("agent.identity.authorization_scope", "agent.identity.privilege_revocation_event"),
        source_url="https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/SP_800_53_5_1_0/home?element=AC-6",
    ),

    "SP800-53:AU-9": ControlMeta(
        control_id="SP800-53:AU-9",
        title="Protection of Audit Information",
        description=(
            "The information system protects audit information and audit tools from "
            "unauthorized access, modification, and deletion; backs up audit records "
            "onto a physically different system or media."
        ),
        framework="NIST_SP_800_53",
        incident_codes=(
            IncidentCode.AGT_GOV_AUDIT_TAMPERING,
        ),
        djl_rule_ids=("DJL-POL-006",),
        audit_log_fields=("verdict.audit.hmac_chain_valid",),
        source_url="https://csrc.nist.gov/projects/cprt/catalog#/cprt/framework/version/SP_800_53_5_1_0/home?element=AU-9",
    ),
}


# ---------------------------------------------------------------------------
# SOC 2 Type II controls  (≥5 — CC6.1, CC6.6, CC7.2, CC7.3, CC7.4)
# ---------------------------------------------------------------------------

_SOC2_CONTROLS: dict[str, ControlMeta] = {

    "SOC2:CC6.1": ControlMeta(
        control_id="SOC2:CC6.1",
        title="Logical and Physical Access Controls",
        description=(
            "The entity implements logical access security software, infrastructure, "
            "and architectures over protected information assets to protect them from "
            "security events to meet the entity's objectives."
        ),
        framework="SOC_2",
        incident_codes=(
            IncidentCode.AGT_EXF_DUMP,
            IncidentCode.AGT_MIS_PRIVILEGE_ESCALATION,
        ),
        djl_rule_ids=("DJL-SQLI-001", "DJL-EXF-001", "DJL-MIS-003"),
        audit_log_fields=("agent.identity.authorization_scope", "verdict.djl.matched_rules"),
        source_url="https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2",
    ),

    "SOC2:CC6.6": ControlMeta(
        control_id="SOC2:CC6.6",
        title="Logical Access — External Threats",
        description=(
            "The entity implements controls to prevent and detect security events "
            "from external threats, including threats from untrusted sources such "
            "as the internet, attackers, and malicious code."
        ),
        framework="SOC_2",
        incident_codes=(
            IncidentCode.AGT_EXF_NETWORK,
            IncidentCode.AGT_PI_INDIRECT,
        ),
        djl_rule_ids=("DJL-EXF-002", "DJL-EXF-003", "DJL-PI-006", "DJL-PI-007"),
        audit_log_fields=("verdict.djl.matched_rules",),
        source_url="https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2",
    ),

    "SOC2:CC7.2": ControlMeta(
        control_id="SOC2:CC7.2",
        title="System Monitoring",
        description=(
            "The entity monitors system components and operations for anomalies "
            "indicative of malicious acts, natural disasters, and errors affecting "
            "the entity's ability to meet its objectives."
        ),
        framework="SOC_2",
        incident_codes=(
            IncidentCode.AGT_FIN_FRAUD_PATTERN,
            IncidentCode.AGT_GOV_POLICY_BYPASS,
        ),
        djl_rule_ids=("DJL-POL-003", "DJL-POL-004"),
        audit_log_fields=("soar.playbook_execution_log", "verdict.djl.matched_rules"),
        source_url="https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2",
    ),

    "SOC2:CC7.3": ControlMeta(
        control_id="SOC2:CC7.3",
        title="Security Incident Evaluation",
        description=(
            "The entity evaluates security events to determine whether they could or "
            "have resulted in a failure of the entity to meet its objectives (security "
            "incidents) and, if so, takes actions to prevent or address such failures."
        ),
        framework="SOC_2",
        incident_codes=(
            IncidentCode.AGT_GOV_AUDIT_TAMPERING,
            IncidentCode.AGT_EXF_DUMP,
        ),
        djl_rule_ids=("DJL-POL-006", "DJL-EXF-001"),
        audit_log_fields=("soar.incident_ticket_id", "verdict.audit.hmac_chain_valid"),
        source_url="https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2",
    ),

    "SOC2:CC7.4": ControlMeta(
        control_id="SOC2:CC7.4",
        title="Security Incident Response",
        description=(
            "The entity responds to identified security incidents by executing a "
            "defined incident response program to understand, contain, remediate, "
            "and communicate security incidents, as appropriate."
        ),
        framework="SOC_2",
        incident_codes=(
            IncidentCode.AGT_PI_OVERRIDE,
            IncidentCode.AGT_EXF_NETWORK,
            IncidentCode.AGT_GOV_HUMAN_OVERSIGHT_BYPASS,
        ),
        djl_rule_ids=("DJL-PI-001", "DJL-EXF-002", "DJL-POL-007"),
        audit_log_fields=("soar.playbook_execution_log", "soar.incident_ticket_id"),
        source_url="https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2",
    ),

    "SOC2:CC9.1": ControlMeta(
        control_id="SOC2:CC9.1",
        title="Risk Mitigation — Vendor and Partner",
        description=(
            "The entity identifies, selects, and manages vendors and business partners "
            "commensurate with the level of risk being managed; vendor risk is assessed "
            "prior to on-boarding and on an ongoing basis."
        ),
        framework="SOC_2",
        incident_codes=(
            IncidentCode.AGT_MIS_UNAUTHORIZED_TRANSACTION,
            IncidentCode.AGT_FIN_HIGH_VALUE_TRANSFER,
        ),
        djl_rule_ids=("DJL-MIS-005", "DJL-POL-001", "DJL-MIS-006", "DJL-POL-002"),
        audit_log_fields=("governance.vendor_risk_attestation", "soar.financial_freeze_record"),
        source_url="https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2",
    ),
}


# ---------------------------------------------------------------------------
# ISO/IEC 27001:2022 controls  (≥5)
# ---------------------------------------------------------------------------

_ISO_27001_CONTROLS: dict[str, ControlMeta] = {

    "ISO27001:A.5.30": ControlMeta(
        control_id="ISO27001:A.5.30",
        title="ICT Readiness for Business Continuity",
        description=(
            "ICT readiness shall be planned, implemented, maintained, tested and "
            "reviewed based on business continuity objectives and ICT continuity "
            "requirements."
        ),
        framework="ISO_27001",
        incident_codes=(
            IncidentCode.AGT_MIS_DESTRUCTIVE,
        ),
        djl_rule_ids=("DJL-MIS-001", "DJL-MIS-002"),
        audit_log_fields=("governance.risk_register",),
        source_url="https://www.iso.org/standard/82875.html",
    ),

    "ISO27001:A.8.16": ControlMeta(
        control_id="ISO27001:A.8.16",
        title="Monitoring Activities",
        description=(
            "Networks, systems, and applications shall be monitored for anomalous "
            "behaviour; appropriate actions shall be taken to evaluate potential "
            "information security incidents."
        ),
        framework="ISO_27001",
        incident_codes=(
            IncidentCode.AGT_PI_OVERRIDE,
            IncidentCode.AGT_EXF_NETWORK,
        ),
        djl_rule_ids=("DJL-PI-001", "DJL-EXF-002", "DJL-EXF-003"),
        audit_log_fields=("metrics.exfiltration_attempt_count", "verdict.djl.matched_rules"),
        source_url="https://www.iso.org/standard/82875.html",
    ),

    "ISO27001:A.8.34": ControlMeta(
        control_id="ISO27001:A.8.34",
        title="Protection of Information Systems During Audit Testing",
        description=(
            "Audit tests and other assurance activities involving assessment of "
            "operational systems shall be planned and agreed between the tester "
            "and appropriate management to minimise disruptions."
        ),
        framework="ISO_27001",
        incident_codes=(
            IncidentCode.AGT_GOV_AUDIT_TAMPERING,
        ),
        djl_rule_ids=("DJL-POL-006",),
        audit_log_fields=("verdict.audit.hmac_chain_valid",),
        source_url="https://www.iso.org/standard/82875.html",
    ),

    "ISO27001:A.12.1": ControlMeta(
        control_id="ISO27001:A.12.1",
        title="Operational Procedures and Responsibilities",
        description=(
            "Operating procedures shall be documented and made available to all users "
            "who need them; changes to information processing facilities and procedures "
            "shall be controlled."
        ),
        framework="ISO_27001",
        incident_codes=(
            IncidentCode.AGT_GOV_POLICY_BYPASS,
        ),
        djl_rule_ids=("DJL-POL-004", "DJL-POL-005"),
        audit_log_fields=("governance.risk_tolerance_config",),
        source_url="https://www.iso.org/standard/82875.html",
    ),

    "ISO27001:A.16.1": ControlMeta(
        control_id="ISO27001:A.16.1",
        title="Management of Information Security Incidents and Improvements",
        description=(
            "Responsibilities and procedures shall be established to ensure a quick, "
            "effective, and orderly response to information security incidents; "
            "incidents shall be reported through appropriate management channels."
        ),
        framework="ISO_27001",
        incident_codes=(
            IncidentCode.AGT_PI_INDIRECT,
            IncidentCode.AGT_EXF_DUMP,
            IncidentCode.AGT_GOV_HUMAN_OVERSIGHT_BYPASS,
        ),
        djl_rule_ids=("DJL-PI-006", "DJL-EXF-001", "DJL-POL-007"),
        audit_log_fields=("soar.incident_ticket_id", "soar.lessons_learned_doc_ref"),
        source_url="https://www.iso.org/standard/82875.html",
    ),

    "ISO27001:A.5.7": ControlMeta(
        control_id="ISO27001:A.5.7",
        title="Threat Intelligence",
        description=(
            "Information relating to information security threats shall be collected "
            "and analysed to produce threat intelligence; this intelligence shall be "
            "used to inform risk management decisions."
        ),
        framework="ISO_27001",
        incident_codes=(
            IncidentCode.AGT_PI_OVERRIDE,
            IncidentCode.AGT_PI_ROLEPLAY,
            IncidentCode.AGT_PI_INDIRECT,
        ),
        djl_rule_ids=("DJL-PI-001", "DJL-PI-002", "DJL-PI-003", "DJL-PI-004", "DJL-PI-005"),
        audit_log_fields=("verdict.djl.matched_rules", "metrics.jbb_defense_score"),
        source_url="https://www.iso.org/standard/82875.html",
    ),
}


# ---------------------------------------------------------------------------
# OWASP LLM 2026 Top 10 (exactly 10 controls: LLM01-LLM10)
# ---------------------------------------------------------------------------

_OWASP_LLM_2026_CONTROLS: dict[str, ControlMeta] = {

    "OWASP-LLM-2026:LLM01": ControlMeta(
        control_id="OWASP-LLM-2026:LLM01",
        title="Prompt Injection",
        description=(
            "Prompt injection occurs when an attacker manipulates an LLM via crafted "
            "input, causing unintended actions; indirect injection embeds malicious "
            "instructions in external content consumed by the agent."
        ),
        framework="OWASP_LLM_2026",
        incident_codes=(
            IncidentCode.AGT_PI_OVERRIDE,
            IncidentCode.AGT_PI_ROLEPLAY,
            IncidentCode.AGT_PI_INDIRECT,
        ),
        djl_rule_ids=("DJL-PI-001", "DJL-PI-002", "DJL-PI-003", "DJL-PI-004", "DJL-PI-005"),
        audit_log_fields=("verdict.djl.matched_rules", "metrics.jbb_defense_score"),
        source_url="https://owasp.org/www-project-top-10-for-large-language-model-applications/",
    ),

    "OWASP-LLM-2026:LLM02": ControlMeta(
        control_id="OWASP-LLM-2026:LLM02",
        title="Insecure Output Handling",
        description=(
            "Insecure output handling refers to insufficient validation, sanitization, "
            "and handling of LLM outputs before passing them downstream; it can lead "
            "to XSS, SSRF, privilege escalation, and remote code execution."
        ),
        framework="OWASP_LLM_2026",
        incident_codes=(
            IncidentCode.AGT_PI_INDIRECT,
            IncidentCode.AGT_MIS_DESTRUCTIVE,
        ),
        djl_rule_ids=("DJL-PI-006", "DJL-PI-007", "DJL-MIS-001"),
        audit_log_fields=("verdict.djl.matched_rules",),
        source_url="https://owasp.org/www-project-top-10-for-large-language-model-applications/",
    ),

    "OWASP-LLM-2026:LLM03": ControlMeta(
        control_id="OWASP-LLM-2026:LLM03",
        title="Training Data Poisoning",
        description=(
            "Training data poisoning involves the manipulation of data or fine-tuning "
            "processes to introduce vulnerabilities or biases into an LLM model that "
            "could compromise security, effectiveness, or ethical behaviour."
        ),
        framework="OWASP_LLM_2026",
        incident_codes=(),
        djl_rule_ids=(),
        audit_log_fields=("governance.model_card_ref", "metrics.benchmark_ref"),
        source_url="https://owasp.org/www-project-top-10-for-large-language-model-applications/",
    ),

    "OWASP-LLM-2026:LLM04": ControlMeta(
        control_id="OWASP-LLM-2026:LLM04",
        title="Model Denial of Service",
        description=(
            "An attacker interacts with an LLM in a method that consumes an "
            "exceptionally high amount of resources, resulting in degraded quality "
            "of service for the user and potentially high resource costs."
        ),
        framework="OWASP_LLM_2026",
        incident_codes=(),
        djl_rule_ids=(),
        audit_log_fields=("metrics.djl_latency_p95_ms", "metrics.risk_score_distribution"),
        source_url="https://owasp.org/www-project-top-10-for-large-language-model-applications/",
    ),

    "OWASP-LLM-2026:LLM05": ControlMeta(
        control_id="OWASP-LLM-2026:LLM05",
        title="Supply Chain Vulnerabilities",
        description=(
            "The LLM application supply chain can be affected by vulnerable components "
            "or services including pre-trained models, plugins, or training data; "
            "a compromised supply chain can lead to security breaches."
        ),
        framework="OWASP_LLM_2026",
        incident_codes=(
            IncidentCode.AGT_EXF_NETWORK,
        ),
        djl_rule_ids=("DJL-EXF-002",),
        audit_log_fields=("governance.vendor_risk_attestation",),
        source_url="https://owasp.org/www-project-top-10-for-large-language-model-applications/",
    ),

    "OWASP-LLM-2026:LLM06": ControlMeta(
        control_id="OWASP-LLM-2026:LLM06",
        title="Sensitive Information Disclosure",
        description=(
            "LLM applications may inadvertently reveal confidential data, proprietary "
            "algorithms, or other sensitive details through their responses, leading "
            "to unauthorized access to sensitive data or privacy violations."
        ),
        framework="OWASP_LLM_2026",
        incident_codes=(
            IncidentCode.AGT_PII_LEAKAGE,
            IncidentCode.AGT_PII_RECONSTRUCTION,
            IncidentCode.AGT_EXF_DUMP,
            IncidentCode.AGT_EXF_PII_AGGREGATION,
        ),
        djl_rule_ids=("DJL-PII-001", "DJL-PII-002", "DJL-PII-003", "DJL-PII-004", "DJL-EXF-004"),
        audit_log_fields=("soar.pii_quarantine_record", "pipeline.data_flow_manifest"),
        source_url="https://owasp.org/www-project-top-10-for-large-language-model-applications/",
    ),

    "OWASP-LLM-2026:LLM07": ControlMeta(
        control_id="OWASP-LLM-2026:LLM07",
        title="Insecure Plugin Design",
        description=(
            "LLM plugins can have insecure inputs and insufficient access control; "
            "insufficient access control allows an LLM plugin to trust other plugins "
            "blindly and assume that the end user provided the inputs."
        ),
        framework="OWASP_LLM_2026",
        incident_codes=(
            IncidentCode.AGT_MIS_UNAUTHORIZED_TRANSACTION,
            IncidentCode.AGT_MIS_PRIVILEGE_ESCALATION,
        ),
        djl_rule_ids=("DJL-MIS-005", "DJL-MIS-003", "DJL-POL-001"),
        audit_log_fields=("agent.identity.authorization_scope", "governance.delegation_chain"),
        source_url="https://owasp.org/www-project-top-10-for-large-language-model-applications/",
    ),

    "OWASP-LLM-2026:LLM08": ControlMeta(
        control_id="OWASP-LLM-2026:LLM08",
        title="Excessive Agency",
        description=(
            "An LLM-based system is often granted a degree of agency; excessive agency "
            "occurs when the system takes actions not explicitly authorized, with broader "
            "footprint or higher impact than required to accomplish the task."
        ),
        framework="OWASP_LLM_2026",
        incident_codes=(
            IncidentCode.AGT_GOV_HUMAN_OVERSIGHT_BYPASS,
            IncidentCode.AGT_MIS_DESTRUCTIVE,
            IncidentCode.AGT_FIN_HIGH_VALUE_TRANSFER,
        ),
        djl_rule_ids=("DJL-POL-007", "DJL-MIS-001", "DJL-MIS-006"),
        audit_log_fields=(
            "verdict.hitl.gate_triggered",
            "verdict.decision",
            "soar.financial_freeze_record",
        ),
        source_url="https://owasp.org/www-project-top-10-for-large-language-model-applications/",
    ),

    "OWASP-LLM-2026:LLM09": ControlMeta(
        control_id="OWASP-LLM-2026:LLM09",
        title="Overreliance",
        description=(
            "Overreliance occurs when systems or people depend on LLMs for critical "
            "decisions without adequate oversight; it can lead to misinformation, "
            "miscommunication, legal issues, and security vulnerabilities."
        ),
        framework="OWASP_LLM_2026",
        incident_codes=(
            IncidentCode.AGT_GOV_HUMAN_OVERSIGHT_BYPASS,
        ),
        djl_rule_ids=("DJL-POL-007",),
        audit_log_fields=("verdict.hitl.gate_triggered", "verdict.ensemble.disagreement_rate"),
        source_url="https://owasp.org/www-project-top-10-for-large-language-model-applications/",
    ),

    "OWASP-LLM-2026:LLM10": ControlMeta(
        control_id="OWASP-LLM-2026:LLM10",
        title="Model Theft",
        description=(
            "Model theft involves the unauthorized access, copying, or exfiltration "
            "of proprietary LLM models; successful theft can result in economic losses, "
            "competitive disadvantage, and potential access to sensitive information."
        ),
        framework="OWASP_LLM_2026",
        incident_codes=(
            IncidentCode.AGT_EXF_DUMP,
            IncidentCode.AGT_EXF_NETWORK,
        ),
        djl_rule_ids=("DJL-EXF-001", "DJL-EXF-002", "DJL-EXF-003"),
        audit_log_fields=("verdict.djl.matched_rules", "metrics.exfiltration_attempt_count"),
        source_url="https://owasp.org/www-project-top-10-for-large-language-model-applications/",
    ),
}


# ---------------------------------------------------------------------------
# FRAMEWORKS registry — the top-level export
# ---------------------------------------------------------------------------

FRAMEWORKS: dict[str, ComplianceFramework] = {
    "EU_AI_ACT": ComplianceFramework(
        name="EU AI Act",
        version="2024/1689",
        description=(
            "Regulation (EU) 2024/1689 of the European Parliament and of the Council "
            "laying down harmonised rules on artificial intelligence. Obligations for "
            "high-risk AI system providers include risk management, human oversight, "
            "accuracy/robustness, record-keeping, and serious incident reporting."
        ),
        controls=_EU_AI_ACT_CONTROLS,
        source_url="https://artificialintelligenceact.eu/",
    ),

    "NIST_AI_RMF": ComplianceFramework(
        name="NIST AI RMF",
        version="1.0 (NIST AI 100-1, Jan 2023) + CSA Agentic Profile DRAFT (Mar 2026)",
        description=(
            "NIST Artificial Intelligence Risk Management Framework (AI RMF) 1.0. "
            "Provides a structured approach across 4 functions (GOVERN, MAP, MEASURE, "
            "MANAGE) for managing risks throughout the AI lifecycle. Controls extended "
            "with Cloud Security Alliance Agentic Profile draft (March 2026); that "
            "profile is NOT yet an official NIST publication — see "
            "docs/research/prior-art-nist-agentic-profile.md for the honesty caveat."
        ),
        controls=_NIST_AI_RMF_CONTROLS,
        source_url="https://doi.org/10.6028/NIST.AI.100-1",
    ),

    "NIST_SP_800_53": ComplianceFramework(
        name="NIST SP 800-53",
        version="Rev 5 (Dec 2020, updated Jan 2022)",
        description=(
            "Security and Privacy Controls for Information Systems and Organizations. "
            "Provides a catalog of security and privacy controls applicable to federal "
            "information systems; controls AC-3, AC-4, AC-6, AU-2, AU-9, AU-12, "
            "IR-4, IR-5, SC-7, SC-28, SI-4, and SI-7 are directly applicable to "
            "AI agent governance."
        ),
        controls=_NIST_SP_800_53_CONTROLS,
        source_url="https://doi.org/10.6028/NIST.SP.800-53r5",
    ),

    "SOC_2": ComplianceFramework(
        name="SOC 2 Type II",
        version="AICPA TSC 2017 (updated 2022)",
        description=(
            "Service Organization Control 2 — Trust Services Criteria. Security (CC), "
            "Availability (A), Confidentiality (C), Processing Integrity (PI), and "
            "Privacy (P) categories. Relevant TSC controls for AI agent governance: "
            "CC6.1, CC6.6, CC7.2, CC7.3, CC7.4, CC9.1."
        ),
        controls=_SOC2_CONTROLS,
        source_url="https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2",
    ),

    "ISO_27001": ComplianceFramework(
        name="ISO/IEC 27001",
        version="2022",
        description=(
            "ISO/IEC 27001:2022 — Information security, cybersecurity and privacy "
            "protection. Requirements for an information security management system "
            "(ISMS). Annex A controls A.5.7, A.5.30, A.8.16, A.8.34, A.12.1, and "
            "A.16.1 are mapped to Apohara PROBANT runtime controls."
        ),
        controls=_ISO_27001_CONTROLS,
        source_url="https://www.iso.org/standard/82875.html",
    ),

    "OWASP_LLM_2026": ComplianceFramework(
        name="OWASP LLM Top 10",
        version="2025 (published Nov 2024, community label '2026')",
        description=(
            "OWASP Top 10 for Large Language Model Applications. The 10 most critical "
            "security risks for LLM deployments: LLM01 Prompt Injection through "
            "LLM10 Model Theft. All 10 categories are mapped to PROBANT incident "
            "codes, DJL rules, and audit log fields."
        ),
        controls=_OWASP_LLM_2026_CONTROLS,
        source_url="https://owasp.org/www-project-top-10-for-large-language-model-applications/",
    ),
}


# ---------------------------------------------------------------------------
# Sanity assertions (evaluated at import time)
# ---------------------------------------------------------------------------

_total_controls = sum(len(fw.controls) for fw in FRAMEWORKS.values())
assert _total_controls >= 30, (
    f"Compliance integrity failure: expected ≥30 total controls, found {_total_controls}."
)

assert len(FRAMEWORKS["OWASP_LLM_2026"].controls) == 10, (
    f"OWASP LLM 2026 must have exactly 10 controls, "
    f"found {len(FRAMEWORKS['OWASP_LLM_2026'].controls)}."
)

_REQUIRED_EU_ARTICLES = {"EU-AI-ACT:Art-9", "EU-AI-ACT:Art-14", "EU-AI-ACT:Art-15", "EU-AI-ACT:Art-73"}
assert _REQUIRED_EU_ARTICLES.issubset(FRAMEWORKS["EU_AI_ACT"].controls.keys()), (
    f"EU AI Act missing required articles. "
    f"Present: {set(FRAMEWORKS['EU_AI_ACT'].controls.keys())}"
)

_DJL_RULE_PATTERN = re.compile(r"^DJL-[A-Z]+-\d{3}$")
for _fw in FRAMEWORKS.values():
    for _ctrl in _fw.controls.values():
        for _rid in _ctrl.djl_rule_ids:
            assert _DJL_RULE_PATTERN.match(_rid), (
                f"Control {_ctrl.control_id}: malformed DJL rule ID '{_rid}'."
            )


# ---------------------------------------------------------------------------
# report_generator
# ---------------------------------------------------------------------------


def generate(
    incident_code: IncidentCode,
    framework_names: Sequence[str] | None = None,
) -> dict:
    """Return structured compliance mapping evidence for a given incident code.

    For each framework (or the requested subset), returns all controls whose
    incident_codes tuple includes the given incident code.

    Args:
        incident_code: A taxonomy.IncidentCode value identifying the incident.
        framework_names: Optional list of framework keys from FRAMEWORKS (e.g.
            ["EU_AI_ACT", "NIST_SP_800_53"]). If None, all frameworks are queried.

    Returns:
        {
          "incident": {"code": str, "name": str, "severity": int},
          "frameworks": {
              "<FRAMEWORK_KEY>": [
                  {
                    "control": str,
                    "title": str,
                    "description": str,
                    "audit_log_fields": list[str],
                    "djl_rule_ids": list[str],
                  },
                  ...
              ],
              ...
          },
          "summary": {
              "total_controls_triggered": int,
              "frameworks_with_evidence": int,
          },
        }
    """
    definition = TAXONOMY[incident_code]
    result_frameworks: dict[str, list[dict]] = {}

    selected_keys = list(framework_names) if framework_names is not None else list(FRAMEWORKS.keys())

    for fw_key in selected_keys:
        fw = FRAMEWORKS[fw_key]
        matched: list[dict] = []
        for ctrl in fw.controls.values():
            if incident_code in ctrl.incident_codes:
                matched.append(
                    {
                        "control": ctrl.control_id,
                        "title": ctrl.title,
                        "description": ctrl.description,
                        "audit_log_fields": list(ctrl.audit_log_fields),
                        "djl_rule_ids": list(ctrl.djl_rule_ids),
                    }
                )
        result_frameworks[fw_key] = matched

    total_triggered = sum(len(v) for v in result_frameworks.values())
    frameworks_with_evidence = sum(1 for v in result_frameworks.values() if v)

    return {
        "incident": {
            "code": definition.code.value,
            "name": definition.name,
            "severity": definition.severity,
        },
        "frameworks": result_frameworks,
        "summary": {
            "total_controls_triggered": total_triggered,
            "frameworks_with_evidence": frameworks_with_evidence,
        },
    }
