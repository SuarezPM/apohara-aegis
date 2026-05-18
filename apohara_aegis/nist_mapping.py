# SPDX-License-Identifier: Apache-2.0
"""
NIST AI RMF Agentic Profile mapping.

Aligns to the Cloud Security Alliance Agentic Profile (March 2026 DRAFT)
extending NIST AI RMF 1.0 (NIST AI 100-1). The official NIST Agent
Interoperability Profile is planned for Q4 2026 per the CSA Lab Space
preprint; this module will update accordingly.

Sources:
- NIST AI RMF 1.0: https://www.nist.gov/itl/ai-risk-management-framework
- CSA Agentic Profile v1 DRAFT (Mar 2026):
  https://labs.cloudsecurityalliance.org/agentic/agentic-nist-ai-rmf-profile-v1/
- Microsoft Agent Governance Toolkit (prior art, base NIST AI RMF 1.0):
  https://github.com/microsoft/agent-governance-toolkit

Honesty contract (per docs/research/prior-art-nist-agentic-profile.md):
  - NIST has NOT officially published an Agentic Profile; the CSA Lab
    Space document (March 2026) is the closest practitioner-oriented draft.
  - ``csa_agentic_extension=True`` marks controls that extend the CSA draft
    beyond base NIST AI RMF 1.0; ``False`` marks direct base-RMF controls.
  - Apohara PROBANT claim: "aligns to CSA Agentic Profile (March 2026 draft)
    extending NIST AI RMF" — NOT "first NIST implementation".

Part of the Apohara PROBANT Fusion Sprint (2026-05-18).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .taxonomy import IncidentCode


# ---------------------------------------------------------------------------
# AgenticControl dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgenticControl:
    """A single NIST AI RMF / CSA Agentic Profile control mapped to Apohara."""

    control_id: str
    """Compound ID: AGENTIC-<FUNCTION>-<SHORT> (CSA-style) or RMF-<FUNCTION>-<N.N>."""

    title: str
    """Short human-readable control title."""

    description: str
    """One-to-two sentence normative statement of the control requirement."""

    rmf_function: str
    """One of: GOVERN | MAP | MEASURE | MANAGE."""

    rmf_subcategory: str
    """Base NIST AI RMF 1.0 subcategory reference (e.g. "GOVERN-1.1").
    For pure CSA extensions without a 1:1 base subcategory, uses the
    nearest parent function (e.g. "GOVERN-*")."""

    csa_agentic_extension: bool
    """True if this control is a CSA Agentic Profile extension beyond base NIST
    AI RMF 1.0; False if it maps directly to a published NIST AI 100-1 outcome."""

    apohara_djl_rule_ids: tuple[str, ...]
    """DJL rule IDs from djl.py that implement this control. US-86 CI gate
    cross-resolves; mark as empty tuple when no deterministic rule applies."""

    apohara_incident_codes: tuple[IncidentCode, ...]
    """Taxonomy codes from taxonomy.py surfaced when this control fires."""

    apohara_audit_log_field: str
    """JSONL audit log field path where evidence for this control is written
    (e.g. "verdict.djl.matched_rules", "verdict.ensemble.decision")."""


# ---------------------------------------------------------------------------
# CONTROLS — ≥30 controls across all 4 RMF functions
# ---------------------------------------------------------------------------

CONTROLS: dict[str, AgenticControl] = {

    # ══════════════════════════════════════════════════════════════════════
    # GOVERN — 10 controls (6 base NIST AI RMF 1.0, 4 CSA Agentic extensions)
    # ══════════════════════════════════════════════════════════════════════

    "RMF-GOVERN-1.1": AgenticControl(
        control_id="RMF-GOVERN-1.1",
        title="AI Risk Management Policy",
        description=(
            "Policies, processes, procedures, and practices across the AI risk "
            "management lifecycle are in place, transparent, and implemented effectively."
        ),
        rmf_function="GOVERN",
        rmf_subcategory="GOVERN-1.1",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=("DJL-POL-004", "DJL-POL-005"),
        apohara_incident_codes=(
            IncidentCode.AGT_GOV_POLICY_BYPASS,
        ),
        apohara_audit_log_field="verdict.djl.matched_rules",
    ),

    "RMF-GOVERN-1.2": AgenticControl(
        control_id="RMF-GOVERN-1.2",
        title="Accountability Structures",
        description=(
            "Accountability structures are in place so that appropriate teams and "
            "individuals are empowered, responsible, and trained for mapping, "
            "measuring, and managing AI risks."
        ),
        rmf_function="GOVERN",
        rmf_subcategory="GOVERN-1.2",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(
            IncidentCode.AGT_GOV_HUMAN_OVERSIGHT_BYPASS,
        ),
        apohara_audit_log_field="governance.accountability_role",
    ),

    "RMF-GOVERN-1.7": AgenticControl(
        control_id="RMF-GOVERN-1.7",
        title="Human Oversight of AI Actions",
        description=(
            "Processes for governing the human oversight of AI systems are in "
            "place: decisions with high consequence require human confirmation "
            "before the AI action is executed."
        ),
        rmf_function="GOVERN",
        rmf_subcategory="GOVERN-1.7",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=("DJL-POL-007",),
        apohara_incident_codes=(
            IncidentCode.AGT_GOV_HUMAN_OVERSIGHT_BYPASS,
            IncidentCode.AGT_MIS_UNAUTHORIZED_TRANSACTION,
        ),
        apohara_audit_log_field="verdict.hitl.gate_triggered",
    ),

    "RMF-GOVERN-3.1": AgenticControl(
        control_id="RMF-GOVERN-3.1",
        title="Organizational Risk Tolerance",
        description=(
            "Organizational teams are committed to a culture of risk management "
            "and governance; the AI system risk tolerance threshold is documented "
            "and enforced at runtime."
        ),
        rmf_function="GOVERN",
        rmf_subcategory="GOVERN-3.1",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="governance.risk_tolerance_config",
    ),

    "RMF-GOVERN-5.1": AgenticControl(
        control_id="RMF-GOVERN-5.1",
        title="Organizational Policies for AI Supply Chain",
        description=(
            "Organizational policies and practices for AI risk management are in "
            "place, including for organizational policies and practices addressing "
            "AI supply chain risks."
        ),
        rmf_function="GOVERN",
        rmf_subcategory="GOVERN-5.1",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=("DJL-EXF-002",),
        apohara_incident_codes=(
            IncidentCode.AGT_EXF_NETWORK,
        ),
        apohara_audit_log_field="verdict.djl.matched_rules",
    ),

    "RMF-GOVERN-6.1": AgenticControl(
        control_id="RMF-GOVERN-6.1",
        title="Third-Party AI Risk Policies",
        description=(
            "Policies and procedures are in place for third-party AI entities "
            "including due diligence, incident disclosure, and contractual controls."
        ),
        rmf_function="GOVERN",
        rmf_subcategory="GOVERN-6.1",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="governance.vendor_risk_attestation",
    ),

    "AGENTIC-GOVERN-AGENT-IDENTITY": AgenticControl(
        control_id="AGENTIC-GOVERN-AGENT-IDENTITY",
        title="Agent Identity and Authorization Scope",
        description=(
            "Each AI agent has a declared identity with a bounded authorization "
            "scope; agents cannot self-elevate permissions or impersonate other "
            "agents without explicit orchestrator grant."
        ),
        rmf_function="GOVERN",
        rmf_subcategory="GOVERN-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=("DJL-MIS-003", "DJL-MIS-004"),
        apohara_incident_codes=(
            IncidentCode.AGT_MIS_PRIVILEGE_ESCALATION,
        ),
        apohara_audit_log_field="agent.identity.authorization_scope",
    ),

    "AGENTIC-GOVERN-MULTI-AGENT-POLICY": AgenticControl(
        control_id="AGENTIC-GOVERN-MULTI-AGENT-POLICY",
        title="Multi-Agent Orchestration Policy",
        description=(
            "A documented policy governs how orchestrating agents delegate "
            "authority to sub-agents; trust levels, tool access, and scope "
            "are explicitly constrained per delegation hop."
        ),
        rmf_function="GOVERN",
        rmf_subcategory="GOVERN-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=("DJL-POL-001",),
        apohara_incident_codes=(
            IncidentCode.AGT_GOV_POLICY_BYPASS,
        ),
        apohara_audit_log_field="governance.delegation_chain",
    ),

    "AGENTIC-GOVERN-AUDIT-INTEGRITY": AgenticControl(
        control_id="AGENTIC-GOVERN-AUDIT-INTEGRITY",
        title="Tamper-Evident Audit Trail",
        description=(
            "All agentic actions and verdicts are recorded in a tamper-evident "
            "HMAC-chained audit log; agents cannot modify or suppress prior "
            "entries (maps to EU AI Act Art. 12)."
        ),
        rmf_function="GOVERN",
        rmf_subcategory="GOVERN-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=("DJL-POL-006",),
        apohara_incident_codes=(
            IncidentCode.AGT_GOV_AUDIT_TAMPERING,
        ),
        apohara_audit_log_field="verdict.audit.hmac_chain_valid",
    ),

    "AGENTIC-GOVERN-HUMAN-ESCALATION": AgenticControl(
        control_id="AGENTIC-GOVERN-HUMAN-ESCALATION",
        title="Human Escalation Trigger Policy",
        description=(
            "A runtime policy defines when agentic decisions must be escalated "
            "to a human operator; BLOCK verdicts and high-severity incident codes "
            "automatically open a human-review ticket."
        ),
        rmf_function="GOVERN",
        rmf_subcategory="GOVERN-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=("DJL-POL-007",),
        apohara_incident_codes=(
            IncidentCode.AGT_GOV_HUMAN_OVERSIGHT_BYPASS,
        ),
        apohara_audit_log_field="verdict.hitl.escalation_ticket_id",
    ),

    # ══════════════════════════════════════════════════════════════════════
    # MAP — 8 controls (5 base NIST AI RMF 1.0, 3 CSA Agentic extensions)
    # ══════════════════════════════════════════════════════════════════════

    "RMF-MAP-1.1": AgenticControl(
        control_id="RMF-MAP-1.1",
        title="Context and Scope Classification",
        description=(
            "Context is established and understood; the AI system scope, "
            "intended business use, and risk context are formally documented."
        ),
        rmf_function="MAP",
        rmf_subcategory="MAP-1.1",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="pipeline.context.scope_classification",
    ),

    "RMF-MAP-2.1": AgenticControl(
        control_id="RMF-MAP-2.1",
        title="Scientific and Technical Basis Review",
        description=(
            "The scientific basis of AI output claims is reviewed and documented; "
            "limitations of the underlying model are catalogued."
        ),
        rmf_function="MAP",
        rmf_subcategory="MAP-2.1",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="governance.model_card_ref",
    ),

    "RMF-MAP-3.5": AgenticControl(
        control_id="RMF-MAP-3.5",
        title="Established Risk Categories Assessed",
        description=(
            "Risks or other undesirable impacts of the AI system are established "
            "as information to help prioritize risk-response activities."
        ),
        rmf_function="MAP",
        rmf_subcategory="MAP-3.5",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="governance.risk_register",
    ),

    "RMF-MAP-4.1": AgenticControl(
        control_id="RMF-MAP-4.1",
        title="AI Risk and Impact Prioritization",
        description=(
            "Documented plans for assessing and evaluating the degree to which "
            "identified AI risks are addressed by current controls are in place."
        ),
        rmf_function="MAP",
        rmf_subcategory="MAP-4.1",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="governance.impact_register",
    ),

    "RMF-MAP-5.1": AgenticControl(
        control_id="RMF-MAP-5.1",
        title="AI System Likelihood and Impact Evaluation",
        description=(
            "Likelihood and magnitude of each identified risk impact is evaluated "
            "periodically, considering the specific deployment context."
        ),
        rmf_function="MAP",
        rmf_subcategory="MAP-5.1",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="governance.risk_scoring_history",
    ),

    "AGENTIC-MAP-TOOL-INVENTORY": AgenticControl(
        control_id="AGENTIC-MAP-TOOL-INVENTORY",
        title="Agent Tool Inventory and Risk Classification",
        description=(
            "All tools accessible by each agent are enumerated; each tool is "
            "classified by its destructive potential and data-access scope, "
            "driving DJL rule selection."
        ),
        rmf_function="MAP",
        rmf_subcategory="MAP-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=("DJL-MIS-001", "DJL-MIS-002"),
        apohara_incident_codes=(
            IncidentCode.AGT_MIS_DESTRUCTIVE,
            IncidentCode.AGT_MIS_PRIVILEGE_ESCALATION,
        ),
        apohara_audit_log_field="pipeline.tool_manifest",
    ),

    "AGENTIC-MAP-PROMPT-SURFACE": AgenticControl(
        control_id="AGENTIC-MAP-PROMPT-SURFACE",
        title="Prompt Attack Surface Mapping",
        description=(
            "The full prompt attack surface is mapped per agent role, including "
            "system prompt, user messages, tool responses, and external document "
            "ingestion paths; indirect injection vectors are catalogued."
        ),
        rmf_function="MAP",
        rmf_subcategory="MAP-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=("DJL-PI-001", "DJL-PI-002", "DJL-PI-003", "DJL-PI-006", "DJL-PI-007"),
        apohara_incident_codes=(
            IncidentCode.AGT_PI_OVERRIDE,
            IncidentCode.AGT_PI_ROLEPLAY,
            IncidentCode.AGT_PI_INDIRECT,
        ),
        apohara_audit_log_field="verdict.djl.matched_rules",
    ),

    "AGENTIC-MAP-DATA-FLOW": AgenticControl(
        control_id="AGENTIC-MAP-DATA-FLOW",
        title="Agentic Data Flow and PII Boundary Mapping",
        description=(
            "Data flows between agents and external systems (databases, APIs, "
            "vector stores) are mapped; PII boundaries and cross-agent data "
            "sharing rules are documented."
        ),
        rmf_function="MAP",
        rmf_subcategory="MAP-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=("DJL-PII-001", "DJL-PII-002", "DJL-EXF-004"),
        apohara_incident_codes=(
            IncidentCode.AGT_PII_LEAKAGE,
            IncidentCode.AGT_EXF_PII_AGGREGATION,
        ),
        apohara_audit_log_field="pipeline.data_flow_manifest",
    ),

    # ══════════════════════════════════════════════════════════════════════
    # MEASURE — 8 controls (4 base NIST AI RMF 1.0, 4 CSA Agentic extensions)
    # ══════════════════════════════════════════════════════════════════════

    "RMF-MEASURE-1.1": AgenticControl(
        control_id="RMF-MEASURE-1.1",
        title="Risk Measurement Approach",
        description=(
            "Approaches and metrics for measuring AI risks are selected that are "
            "appropriate to the risk tolerance of the organization."
        ),
        rmf_function="MEASURE",
        rmf_subcategory="MEASURE-1.1",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="metrics.risk_score_distribution",
    ),

    "RMF-MEASURE-2.2": AgenticControl(
        control_id="RMF-MEASURE-2.2",
        title="AI System Evaluation Testing",
        description=(
            "AI system performance is evaluated and documented by testing and "
            "benchmarking; evaluation results are reviewed and acted upon."
        ),
        rmf_function="MEASURE",
        rmf_subcategory="MEASURE-2.2",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="metrics.benchmark_ref",
    ),

    "RMF-MEASURE-2.5": AgenticControl(
        control_id="RMF-MEASURE-2.5",
        title="AI System Robustness",
        description=(
            "The AI system to be deployed is demonstrated to be robust to "
            "unexpected inputs and adversarial conditions."
        ),
        rmf_function="MEASURE",
        rmf_subcategory="MEASURE-2.5",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=("DJL-PI-001", "DJL-PI-002", "DJL-PI-003"),
        apohara_incident_codes=(
            IncidentCode.AGT_PI_OVERRIDE,
            IncidentCode.AGT_PI_INDIRECT,
        ),
        apohara_audit_log_field="metrics.adversarial_test_results",
    ),

    "RMF-MEASURE-4.1": AgenticControl(
        control_id="RMF-MEASURE-4.1",
        title="Risk Treatment Effectiveness Measurement",
        description=(
            "Measurement feedback is used to verify that risk treatment decisions "
            "are proving effective; metrics are tracked over time."
        ),
        rmf_function="MEASURE",
        rmf_subcategory="MEASURE-4.1",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="metrics.control_effectiveness_trend",
    ),

    "AGENTIC-MEASURE-PROMPT-INJECTION": AgenticControl(
        control_id="AGENTIC-MEASURE-PROMPT-INJECTION",
        title="Prompt Injection Detection Rate",
        description=(
            "The rate of detected vs. missed prompt injection attempts is measured "
            "continuously; a JBB Live Defense benchmark score is maintained and "
            "reported per release."
        ),
        rmf_function="MEASURE",
        rmf_subcategory="MEASURE-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=("DJL-PI-001", "DJL-PI-002", "DJL-PI-003", "DJL-PI-006", "DJL-PI-007"),
        apohara_incident_codes=(
            IncidentCode.AGT_PI_OVERRIDE,
            IncidentCode.AGT_PI_ROLEPLAY,
            IncidentCode.AGT_PI_INDIRECT,
        ),
        apohara_audit_log_field="metrics.jbb_defense_score",
    ),

    "AGENTIC-MEASURE-VENDOR-DISAGREEMENT": AgenticControl(
        control_id="AGENTIC-MEASURE-VENDOR-DISAGREEMENT",
        title="Multi-Vendor Judge Disagreement Rate",
        description=(
            "When multiple LLM judges disagree on a verdict, the disagreement "
            "event is measured and reported; high disagreement rates trigger "
            "calibration reviews."
        ),
        rmf_function="MEASURE",
        rmf_subcategory="MEASURE-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="verdict.ensemble.disagreement_rate",
    ),

    "AGENTIC-MEASURE-EXFILTRATION-RATE": AgenticControl(
        control_id="AGENTIC-MEASURE-EXFILTRATION-RATE",
        title="Data Exfiltration Attempt Rate",
        description=(
            "The rate of detected data exfiltration attempts (network, bulk dump, "
            "PII aggregation) is measured per pipeline; sustained elevation triggers "
            "an automated Tier-2 SOAR escalation."
        ),
        rmf_function="MEASURE",
        rmf_subcategory="MEASURE-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=("DJL-EXF-001", "DJL-EXF-002", "DJL-EXF-003", "DJL-EXF-004"),
        apohara_incident_codes=(
            IncidentCode.AGT_EXF_DUMP,
            IncidentCode.AGT_EXF_NETWORK,
            IncidentCode.AGT_EXF_PII_AGGREGATION,
        ),
        apohara_audit_log_field="metrics.exfiltration_attempt_count",
    ),

    "AGENTIC-MEASURE-LATENCY-SLA": AgenticControl(
        control_id="AGENTIC-MEASURE-LATENCY-SLA",
        title="Defense Latency SLA Compliance",
        description=(
            "The p95 and p99 latency of the DJL + ensemble defense layers is "
            "measured against the SLA; regressions block release (automated via "
            "test_djl_latency.py)."
        ),
        rmf_function="MEASURE",
        rmf_subcategory="MEASURE-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="metrics.djl_latency_p95_ms",
    ),

    # ══════════════════════════════════════════════════════════════════════
    # MANAGE — 9 controls (4 base NIST AI RMF 1.0, 5 CSA Agentic extensions)
    # ══════════════════════════════════════════════════════════════════════

    "RMF-MANAGE-1.1": AgenticControl(
        control_id="RMF-MANAGE-1.1",
        title="Risks Managed to Acceptable Levels",
        description=(
            "Risks and benefits are analyzed and informed decisions are made to "
            "address and manage risks to an acceptable level."
        ),
        rmf_function="MANAGE",
        rmf_subcategory="MANAGE-1.1",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="governance.risk_acceptance_record",
    ),

    "RMF-MANAGE-2.2": AgenticControl(
        control_id="RMF-MANAGE-2.2",
        title="Mechanisms for AI Incident Reporting",
        description=(
            "Mechanisms are in place to document feedback about incidents and "
            "near-misses; feedback informs risk management processes."
        ),
        rmf_function="MANAGE",
        rmf_subcategory="MANAGE-2.2",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="soar.incident_ticket_id",
    ),

    "RMF-MANAGE-3.1": AgenticControl(
        control_id="RMF-MANAGE-3.1",
        title="Risk Response Plan",
        description=(
            "Responses to the AI risks deemed unacceptable are planned, with "
            "the appropriate team responsible for risk response."
        ),
        rmf_function="MANAGE",
        rmf_subcategory="MANAGE-3.1",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="soar.response_playbook_id",
    ),

    "RMF-MANAGE-4.1": AgenticControl(
        control_id="RMF-MANAGE-4.1",
        title="Post-Incident Lessons Learned",
        description=(
            "Post-deployment AI risks and impacts, including feedback from "
            "affected communities, are used to inform risk analysis and "
            "management improvements."
        ),
        rmf_function="MANAGE",
        rmf_subcategory="MANAGE-4.1",
        csa_agentic_extension=False,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(),
        apohara_audit_log_field="soar.lessons_learned_doc_ref",
    ),

    "AGENTIC-MANAGE-BLOCK-RESPONSE": AgenticControl(
        control_id="AGENTIC-MANAGE-BLOCK-RESPONSE",
        title="Automated BLOCK Verdict Execution",
        description=(
            "When a BLOCK verdict is issued by the DJL or ensemble layer, the "
            "agent action is immediately halted; the triggering prompt and matched "
            "rules are archived in the forensics JSONL log."
        ),
        rmf_function="MANAGE",
        rmf_subcategory="MANAGE-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=("DJL-PI-001", "DJL-MIS-001", "DJL-POL-004"),
        apohara_incident_codes=(
            IncidentCode.AGT_PI_OVERRIDE,
            IncidentCode.AGT_MIS_DESTRUCTIVE,
            IncidentCode.AGT_GOV_POLICY_BYPASS,
        ),
        apohara_audit_log_field="verdict.decision",
    ),

    "AGENTIC-MANAGE-SOAR-PLAYBOOK": AgenticControl(
        control_id="AGENTIC-MANAGE-SOAR-PLAYBOOK",
        title="SOAR Automated Incident Response Playbook",
        description=(
            "Automated SOAR playbooks triage, contain, and eradicate agentic "
            "incidents; playbook selection is driven by the incident taxonomy "
            "code (AGT-*) surfaced at detection time."
        ),
        rmf_function="MANAGE",
        rmf_subcategory="MANAGE-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=(),
        apohara_incident_codes=(
            IncidentCode.AGT_PI_OVERRIDE,
            IncidentCode.AGT_EXF_NETWORK,
            IncidentCode.AGT_FIN_HIGH_VALUE_TRANSFER,
            IncidentCode.AGT_GOV_AUDIT_TAMPERING,
        ),
        apohara_audit_log_field="soar.playbook_execution_log",
    ),

    "AGENTIC-MANAGE-PRIVILEGE-REVOCATION": AgenticControl(
        control_id="AGENTIC-MANAGE-PRIVILEGE-REVOCATION",
        title="Dynamic Privilege Revocation on Escalation Attempt",
        description=(
            "If an agent triggers a privilege escalation incident code, its tool "
            "access scope is dynamically revoked until a human operator reinstates "
            "permissions via a signed approval."
        ),
        rmf_function="MANAGE",
        rmf_subcategory="MANAGE-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=("DJL-MIS-003", "DJL-MIS-004"),
        apohara_incident_codes=(
            IncidentCode.AGT_MIS_PRIVILEGE_ESCALATION,
        ),
        apohara_audit_log_field="agent.identity.privilege_revocation_event",
    ),

    "AGENTIC-MANAGE-PII-QUARANTINE": AgenticControl(
        control_id="AGENTIC-MANAGE-PII-QUARANTINE",
        title="PII Leakage Quarantine and Notification",
        description=(
            "When a PII leakage or reconstruction incident fires, the affected "
            "response is quarantined; downstream channels are notified and a "
            "GDPR/HIPAA breach assessment workflow is initiated."
        ),
        rmf_function="MANAGE",
        rmf_subcategory="MANAGE-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=("DJL-PII-002", "DJL-PII-003", "DJL-PII-004"),
        apohara_incident_codes=(
            IncidentCode.AGT_PII_LEAKAGE,
            IncidentCode.AGT_PII_RECONSTRUCTION,
        ),
        apohara_audit_log_field="soar.pii_quarantine_record",
    ),

    "AGENTIC-MANAGE-FINANCIAL-FREEZE": AgenticControl(
        control_id="AGENTIC-MANAGE-FINANCIAL-FREEZE",
        title="Financial Transaction Freeze on High-Value Alert",
        description=(
            "High-value transfer and fraud-pattern incidents automatically trigger "
            "a transaction freeze pending dual-control human authorization; the "
            "event is reported to the AML monitoring system."
        ),
        rmf_function="MANAGE",
        rmf_subcategory="MANAGE-*",
        csa_agentic_extension=True,
        apohara_djl_rule_ids=("DJL-MIS-006", "DJL-POL-002", "DJL-POL-003"),
        apohara_incident_codes=(
            IncidentCode.AGT_FIN_HIGH_VALUE_TRANSFER,
            IncidentCode.AGT_FIN_FRAUD_PATTERN,
        ),
        apohara_audit_log_field="soar.financial_freeze_record",
    ),
}


# ---------------------------------------------------------------------------
# Sanity assertions (evaluated at import time)
# ---------------------------------------------------------------------------
assert len(CONTROLS) >= 30, (
    f"NIST mapping integrity failure: expected ≥30 controls, found {len(CONTROLS)}."
)

_valid_functions = {"GOVERN", "MAP", "MEASURE", "MANAGE"}
for _cid, _ctrl in CONTROLS.items():
    assert _ctrl.rmf_function in _valid_functions, (
        f"Control {_cid}: invalid rmf_function '{_ctrl.rmf_function}'."
    )

_csa_count = sum(1 for c in CONTROLS.values() if c.csa_agentic_extension)
assert _csa_count >= 10, (
    f"Expected ≥10 CSA Agentic extensions, found {_csa_count}."
)
