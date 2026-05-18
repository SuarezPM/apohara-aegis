# SPDX-License-Identifier: Apache-2.0
"""
16-code incident taxonomy for agentic AI misbehavior classification.

Provides a canonical mapping from incident patterns to structured codes
used by soar_pipeline.py DETECT stage and the FORENSICS audit trail.

Part of the Apohara PROBANT Fusion Sprint (2026-05-18).
Implementation per docs/research/incident-taxonomy.md — see plan in
.omc/ralph/SESSION-MEMORY-FUSION-PLAN-2026-05-18T2030Z.md

Categories (6 groups, 16 codes total):
  PI  — Prompt Injection        (3 codes: AGT-PI-001..003)
  EXF — Data Exfiltration       (3 codes: AGT-EXF-001..003)
  MIS — Tool Misuse             (3 codes: AGT-MIS-001..003)
  FIN — Financial Misconduct    (2 codes: AGT-FIN-001..002)
  PII — Privacy / PII           (2 codes: AGT-PII-001..002)
  GOV — Governance              (3 codes: AGT-GOV-001..003)

Design note: unlike PLAYBOOK SOAR templates (which intermix categories),
this taxonomy groups codes by attack family. US-75 templates will map
industry-specific playbooks onto these codes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


# ---------------------------------------------------------------------------
# Incident code enum — exactly 16 entries, categorically grouped
# ---------------------------------------------------------------------------

class IncidentCode(StrEnum):
    # ── Prompt Injection (3) ────────────────────────────────────────────────
    AGT_PI_OVERRIDE = "AGT-PI-001"   # "ignore previous instructions" variant
    AGT_PI_ROLEPLAY = "AGT-PI-002"   # roleplay / persona manipulation
    AGT_PI_INDIRECT = "AGT-PI-003"   # indirect injection via document/tool output

    # ── Data Exfiltration (3) ───────────────────────────────────────────────
    AGT_EXF_DUMP = "AGT-EXF-001"                # database dump request
    AGT_EXF_NETWORK = "AGT-EXF-002"             # outbound to non-allowlisted host
    AGT_EXF_PII_AGGREGATION = "AGT-EXF-003"     # PII aggregation across queries

    # ── Tool Misuse (3) ─────────────────────────────────────────────────────
    AGT_MIS_DESTRUCTIVE = "AGT-MIS-001"              # rm -rf, drop table, etc.
    AGT_MIS_PRIVILEGE_ESCALATION = "AGT-MIS-002"     # sudo, root, kernel ops
    AGT_MIS_UNAUTHORIZED_TRANSACTION = "AGT-MIS-003" # PR merge w/o review, transfer

    # ── Financial Misconduct (2) ────────────────────────────────────────────
    AGT_FIN_HIGH_VALUE_TRANSFER = "AGT-FIN-001"
    AGT_FIN_FRAUD_PATTERN = "AGT-FIN-002"

    # ── Privacy / PII (2) ───────────────────────────────────────────────────
    AGT_PII_LEAKAGE = "AGT-PII-001"
    AGT_PII_RECONSTRUCTION = "AGT-PII-002"   # re-identification / linkage attack

    # ── Governance (3) ──────────────────────────────────────────────────────
    AGT_GOV_POLICY_BYPASS = "AGT-GOV-001"
    AGT_GOV_AUDIT_TAMPERING = "AGT-GOV-002"
    AGT_GOV_HUMAN_OVERSIGHT_BYPASS = "AGT-GOV-003"  # EU AI Act Article 14


# ---------------------------------------------------------------------------
# IncidentDefinition dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IncidentDefinition:
    """Structured metadata for a single incident code."""

    code: IncidentCode
    name: str
    description: str
    severity: int              # 1 (informational) – 10 (critical)
    detection_signals: list[str]
    default_djl_rule_ids: list[str]   # rule IDs resolved by djl.py (US-72)
    default_compliance_refs: list[str]  # <FRAMEWORK>:<CONTROL_ID>


# ---------------------------------------------------------------------------
# DEFINITIONS — one entry per IncidentCode (exactly 16)
# ---------------------------------------------------------------------------

DEFINITIONS: dict[IncidentCode, IncidentDefinition] = {

    # ── Prompt Injection ────────────────────────────────────────────────────

    IncidentCode.AGT_PI_OVERRIDE: IncidentDefinition(
        code=IncidentCode.AGT_PI_OVERRIDE,
        name="Prompt Override Attempt",
        description=(
            "Agent received explicit instructions to override system prompt "
            "or ignore safety constraints (e.g. 'ignore previous instructions', "
            "'developer mode', 'DAN')."
        ),
        severity=8,
        detection_signals=[
            "ignore previous",
            "disregard instructions",
            "developer mode",
            "system override",
            "DAN",
            "jailbreak",
        ],
        default_djl_rule_ids=["DJL-PI-001", "DJL-PI-002", "DJL-PI-003"],
        default_compliance_refs=[
            "NIST-AI-RMF:GOVERN-1.1",
            "OWASP-LLM-2026:LLM01",
            "EU-AI-ACT:Art-14",
            "NIST-SP-800-53:SI-10",
        ],
    ),

    IncidentCode.AGT_PI_ROLEPLAY: IncidentDefinition(
        code=IncidentCode.AGT_PI_ROLEPLAY,
        name="Roleplay Persona Manipulation",
        description=(
            "Agent was instructed to adopt an alter-ego, fictional persona, "
            "or character that has no safety restrictions, bypassing alignment "
            "via narrative framing."
        ),
        severity=7,
        detection_signals=[
            "pretend you are",
            "act as",
            "you are now",
            "in this roleplay",
            "fictional AI",
            "no restrictions",
        ],
        default_djl_rule_ids=["DJL-PI-004", "DJL-PI-005"],
        default_compliance_refs=[
            "OWASP-LLM-2026:LLM01",
            "NIST-AI-RMF:MAP-1.1",
            "EU-AI-ACT:Art-9",
        ],
    ),

    IncidentCode.AGT_PI_INDIRECT: IncidentDefinition(
        code=IncidentCode.AGT_PI_INDIRECT,
        name="Indirect Prompt Injection",
        description=(
            "Malicious instructions were embedded in agent-consumed external "
            "content (document, web page, tool output, database record), "
            "causing the agent to execute attacker-controlled commands."
        ),
        severity=9,
        detection_signals=[
            "[[SYSTEM]]",
            "<!-- inject -->",
            "IGNORE PREVIOUS CONTEXT",
            "embedded instruction in document",
            "tool output contains command",
        ],
        default_djl_rule_ids=["DJL-PI-006", "DJL-PI-007"],
        default_compliance_refs=[
            "OWASP-LLM-2026:LLM02",
            "NIST-SP-800-53:SI-3",
            "EU-AI-ACT:Art-14",
            "ISO-27001:A.12.2",
        ],
    ),

    # ── Data Exfiltration ───────────────────────────────────────────────────

    IncidentCode.AGT_EXF_DUMP: IncidentDefinition(
        code=IncidentCode.AGT_EXF_DUMP,
        name="Database Dump Request",
        description=(
            "Agent attempted to extract a bulk dataset or full table contents "
            "via SQL dump, API mass-export, or equivalent mechanism beyond "
            "its authorized data access scope."
        ),
        severity=9,
        detection_signals=[
            "SELECT * FROM",
            "mysqldump",
            "pg_dump",
            "export all records",
            "full table scan",
            "DUMP DATABASE",
        ],
        default_djl_rule_ids=["DJL-SQLI-001", "DJL-EXF-001"],
        default_compliance_refs=[
            "NIST-SP-800-53:AC-3",
            "SOC2:CC6.1",
            "GDPR:Art-32",
            "OWASP-LLM-2026:LLM06",
        ],
    ),

    IncidentCode.AGT_EXF_NETWORK: IncidentDefinition(
        code=IncidentCode.AGT_EXF_NETWORK,
        name="Unauthorized Outbound Network Call",
        description=(
            "Agent initiated an outbound network request to a host not in the "
            "allowlist, potentially exfiltrating context, credentials, or "
            "sensitive data to an attacker-controlled endpoint."
        ),
        severity=9,
        detection_signals=[
            "curl http",
            "wget http",
            "requests.get",
            "fetch(",
            "non-allowlisted domain",
            "outbound connection blocked",
        ],
        default_djl_rule_ids=["DJL-EXF-002", "DJL-EXF-003"],
        default_compliance_refs=[
            "NIST-SP-800-53:SC-7",
            "SOC2:CC6.6",
            "ISO-27001:A.13.1",
            "OWASP-LLM-2026:LLM06",
        ],
    ),

    IncidentCode.AGT_EXF_PII_AGGREGATION: IncidentDefinition(
        code=IncidentCode.AGT_EXF_PII_AGGREGATION,
        name="PII Aggregation Attack",
        description=(
            "Agent correlated PII fields across multiple queries or data sources "
            "to reconstruct a profile beyond what any single query would reveal, "
            "constituting a mosaic / aggregation attack."
        ),
        severity=8,
        detection_signals=[
            "join on email",
            "match by phone",
            "aggregate across users",
            "combine records",
            "link identity",
        ],
        default_djl_rule_ids=["DJL-PII-001", "DJL-EXF-004"],
        default_compliance_refs=[
            "GDPR:Art-5",
            "NIST-SP-800-53:AC-4",
            "OWASP-LLM-2026:LLM06",
            "CCPA:1798.100",
        ],
    ),

    # ── Tool Misuse ─────────────────────────────────────────────────────────

    IncidentCode.AGT_MIS_DESTRUCTIVE: IncidentDefinition(
        code=IncidentCode.AGT_MIS_DESTRUCTIVE,
        name="Destructive Tool Invocation",
        description=(
            "Agent invoked a tool with a destructive side-effect: file system "
            "wipe (rm -rf), database drop (DROP TABLE), or equivalent "
            "irreversible data-destruction operation."
        ),
        severity=10,
        detection_signals=[
            "rm -rf",
            "DROP TABLE",
            "DELETE FROM",
            "format disk",
            "truncate",
            "shred",
            "wipe",
        ],
        default_djl_rule_ids=["DJL-MIS-001", "DJL-MIS-002"],
        default_compliance_refs=[
            "NIST-SP-800-53:CM-5",
            "SOC2:CC8.1",
            "ISO-27001:A.12.3",
            "EU-AI-ACT:Art-9",
        ],
    ),

    IncidentCode.AGT_MIS_PRIVILEGE_ESCALATION: IncidentDefinition(
        code=IncidentCode.AGT_MIS_PRIVILEGE_ESCALATION,
        name="Privilege Escalation Attempt",
        description=(
            "Agent attempted to elevate its own execution privileges via sudo, "
            "su, kernel module loading, container breakout, or equivalent "
            "mechanism beyond its authorized permission scope."
        ),
        severity=10,
        detection_signals=[
            "sudo",
            "su root",
            "chmod 777",
            "insmod",
            "docker --privileged",
            "nsenter",
            "kernel exploit",
        ],
        default_djl_rule_ids=["DJL-MIS-003", "DJL-MIS-004"],
        default_compliance_refs=[
            "NIST-SP-800-53:AC-6",
            "CIS-Controls:v8-5.4",
            "SOC2:CC6.3",
            "EU-AI-ACT:Art-14",
        ],
    ),

    IncidentCode.AGT_MIS_UNAUTHORIZED_TRANSACTION: IncidentDefinition(
        code=IncidentCode.AGT_MIS_UNAUTHORIZED_TRANSACTION,
        name="Unauthorized Transaction",
        description=(
            "Agent executed a consequential transaction without required human "
            "authorization: merging a PR without code review, initiating a "
            "financial transfer, approving a purchase order autonomously."
        ),
        severity=8,
        detection_signals=[
            "merge pull request",
            "approve without review",
            "transfer funds",
            "submit order",
            "auto-approve",
        ],
        default_djl_rule_ids=["DJL-MIS-005", "DJL-POL-001"],
        default_compliance_refs=[
            "NIST-AI-RMF:GOVERN-1.7",
            "EU-AI-ACT:Art-14",
            "SOC2:CC9.1",
            "ISO-27001:A.6.1",
        ],
    ),

    # ── Financial Misconduct ────────────────────────────────────────────────

    IncidentCode.AGT_FIN_HIGH_VALUE_TRANSFER: IncidentDefinition(
        code=IncidentCode.AGT_FIN_HIGH_VALUE_TRANSFER,
        name="High-Value Financial Transfer",
        description=(
            "Agent initiated or facilitated a monetary transfer above a "
            "risk-defined threshold without dual-control authorization, "
            "triggering AML / fraud-prevention review requirements."
        ),
        severity=10,
        detection_signals=[
            "wire transfer",
            "ACH payment",
            "high amount",
            "large transaction",
            "threshold exceeded",
            "SWIFT",
        ],
        default_djl_rule_ids=["DJL-MIS-006", "DJL-POL-002"],
        default_compliance_refs=[
            "PCI-DSS:v4-10.7",
            "NIST-SP-800-53:AC-5",
            "SOC2:CC9.1",
            "EU-AI-ACT:Annex-III",
        ],
    ),

    IncidentCode.AGT_FIN_FRAUD_PATTERN: IncidentDefinition(
        code=IncidentCode.AGT_FIN_FRAUD_PATTERN,
        name="Financial Fraud Pattern",
        description=(
            "Agent behaviour matched a known financial fraud pattern: structuring "
            "(smurfing), round-trip transactions, invoice manipulation, or "
            "anomalous velocity indicative of synthetic identity fraud."
        ),
        severity=9,
        detection_signals=[
            "structuring",
            "smurfing",
            "round-trip",
            "split transaction",
            "velocity anomaly",
            "invoice manipulation",
        ],
        default_djl_rule_ids=["DJL-POL-003"],
        default_compliance_refs=[
            "PCI-DSS:v4-10.6",
            "NIST-SP-800-53:AU-6",
            "SOC2:CC7.2",
            "FinCEN:31-CFR-1020",
        ],
    ),

    # ── Privacy / PII ───────────────────────────────────────────────────────

    IncidentCode.AGT_PII_LEAKAGE: IncidentDefinition(
        code=IncidentCode.AGT_PII_LEAKAGE,
        name="PII Leakage",
        description=(
            "Agent output contained personally identifiable information "
            "(name, SSN, email, phone, address, health record) that was "
            "not explicitly consented to be shared with the requesting party."
        ),
        severity=8,
        detection_signals=[
            "SSN",
            "social security",
            "date of birth",
            "home address",
            "credit card number",
            "medical record",
            "passport number",
        ],
        default_djl_rule_ids=["DJL-PII-002", "DJL-PII-003"],
        default_compliance_refs=[
            "GDPR:Art-5",
            "CCPA:1798.100",
            "HIPAA:164.514",
            "NIST-SP-800-53:PL-4",
            "OWASP-LLM-2026:LLM06",
        ],
    ),

    IncidentCode.AGT_PII_RECONSTRUCTION: IncidentDefinition(
        code=IncidentCode.AGT_PII_RECONSTRUCTION,
        name="PII Re-identification / Linkage Attack",
        description=(
            "Agent successfully or attempted to re-identify an anonymised "
            "individual by linking quasi-identifiers (zip code + age + gender "
            "or similar), defeating pseudonymisation controls."
        ),
        severity=9,
        detection_signals=[
            "re-identify",
            "deanonymize",
            "link records",
            "quasi-identifier",
            "k-anonymity violation",
            "reverse lookup",
        ],
        default_djl_rule_ids=["DJL-PII-004"],
        default_compliance_refs=[
            "GDPR:Recital-26",
            "NIST-SP-800-188:Sec-4",
            "CCPA:1798.140",
            "ISO-27001:A.18.1",
        ],
    ),

    # ── Governance ──────────────────────────────────────────────────────────

    IncidentCode.AGT_GOV_POLICY_BYPASS: IncidentDefinition(
        code=IncidentCode.AGT_GOV_POLICY_BYPASS,
        name="Policy Bypass",
        description=(
            "Agent circumvented an organisational policy control: Lobster Trap "
            "deny rule, rate-limit guard, content filter, or data-classification "
            "fence — causing a disallowed action to succeed."
        ),
        severity=8,
        detection_signals=[
            "policy bypass",
            "filter circumvented",
            "deny rule skipped",
            "content filter evasion",
            "guardrail disabled",
        ],
        default_djl_rule_ids=["DJL-POL-004", "DJL-POL-005"],
        default_compliance_refs=[
            "NIST-AI-RMF:GOVERN-1.1",
            "ISO-27001:A.6.2",
            "SOC2:CC5.2",
            "EU-AI-ACT:Art-9",
        ],
    ),

    IncidentCode.AGT_GOV_AUDIT_TAMPERING: IncidentDefinition(
        code=IncidentCode.AGT_GOV_AUDIT_TAMPERING,
        name="Audit Log Tampering",
        description=(
            "Agent attempted to delete, overwrite, suppress, or redirect "
            "audit log entries, JSONL forensics records, or telemetry streams "
            "to conceal prior actions."
        ),
        severity=10,
        detection_signals=[
            "delete log",
            "truncate audit",
            "clear history",
            "suppress telemetry",
            "log rotation exploit",
            "audit bypass",
        ],
        default_djl_rule_ids=["DJL-POL-006"],
        default_compliance_refs=[
            "NIST-SP-800-53:AU-9",
            "SOC2:CC7.3",
            "ISO-27001:A.12.4",
            "EU-AI-ACT:Art-12",
        ],
    ),

    IncidentCode.AGT_GOV_HUMAN_OVERSIGHT_BYPASS: IncidentDefinition(
        code=IncidentCode.AGT_GOV_HUMAN_OVERSIGHT_BYPASS,
        name="Human Oversight Bypass",
        description=(
            "Agent took a high-risk consequential action without triggering the "
            "mandatory human-in-the-loop confirmation gate, violating EU AI Act "
            "Article 14 (human oversight) and NIST AI RMF GOVERN-1.7."
        ),
        severity=10,
        detection_signals=[
            "skip confirmation",
            "auto-approve high-risk",
            "bypass HITL",
            "no human review",
            "confirmation gate skipped",
        ],
        default_djl_rule_ids=["DJL-POL-007"],
        default_compliance_refs=[
            "EU-AI-ACT:Art-14",
            "NIST-AI-RMF:GOVERN-1.7",
            "ISO-42001:6.1.2",
            "SOC2:CC9.2",
        ],
    ),
}

# ---------------------------------------------------------------------------
# Sanity assertion (evaluated at import time, not just in tests)
# ---------------------------------------------------------------------------
assert len(DEFINITIONS) == len(list(IncidentCode)) == 16, (
    f"Taxonomy integrity failure: {len(DEFINITIONS)} definitions for "
    f"{len(list(IncidentCode))} codes — must be exactly 16."
)
