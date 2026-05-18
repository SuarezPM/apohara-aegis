# SPDX-License-Identifier: Apache-2.0
"""
Zero-LLM Deterministic Judge Layer (DJL).

Evaluates agent actions using deterministic regex rule sets — no LLM
inference required. Each rule maps a prompt pattern to a severity score
that, in aggregate, produces a BLOCK / REVIEW / ALLOW verdict.

This layer COMPLEMENTS (not replaces) the LLM adversarial ensemble in
``multi_judge.py``. The two layers run in parallel and their verdicts
are combined by ``verdict_combine.py`` (US-77) using a safe-merge
policy: BLOCK if either layer says BLOCK; ALLOW only if both say
ALLOW; REVIEW otherwise.

Rule IDs follow the convention ``DJL-CAT-NNN`` where ``CAT`` is the
category abbreviation:

    PI    — prompt injection            (DJL-PI-NNN)
    SQLI  — SQL injection               (DJL-SQLI-NNN)
    XSS   — cross-site scripting        (DJL-XSS-NNN)
    PII   — personally identifiable     (DJL-PII-NNN)
            information leakage
    EXF   — data exfiltration           (DJL-EXF-NNN)
    MIS   — tool / system misuse        (DJL-MIS-NNN)
    POL   — policy violation (sector)   (DJL-POL-NNN)

Severity scale: 1-10 (10 == kill-the-request).
Verdict mapping:
    * any matched rule with severity >= 8  -> BLOCK
    * any matched rule with severity 5..7  -> REVIEW
    * otherwise                            -> ALLOW

Honesty contract: latency targets in this docstring describe the
*measured* p50/p95/p99 written to ``logs/djl_latency.json``. Do not
edit numbers in this module without re-running the benchmark.

Part of the Apohara PROBANT Fusion Sprint (2026-05-18).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DjlRule:
    """One compiled deterministic rule with provenance metadata."""

    id: str  # e.g. "DJL-PI-001"
    pattern: re.Pattern[str]
    category: str  # "prompt_injection" | "sqli" | "xss" | "pii" |
    #                 "exfiltration" | "tool_misuse" | "policy"
    severity: int  # 1..10
    description: str  # one-line human-readable
    references: list[str] = field(default_factory=list)  # CVE/CWE/OWASP/NIST


Decision = Literal["ALLOW", "REVIEW", "BLOCK"]


@dataclass
class DjlVerdict:
    """Result of evaluating a prompt against all DJL rules."""

    decision: Decision
    matched_rules: list[str]
    latency_ms: float
    layer: str = "djl"


# ---------------------------------------------------------------------------
# Rule sets
# ---------------------------------------------------------------------------
#
# Each rule is intentionally narrow: we prefer a missed novel attack
# (caught by the LLM ensemble in parallel) over a false-positive on a
# legitimate enterprise prompt.
# ---------------------------------------------------------------------------

# DJL-PI-NNN — Prompt Injection (20 rules)
_RULES_PROMPT_INJECTION: list[DjlRule] = [
    DjlRule(
        id="DJL-PI-001",
        pattern=re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?", re.IGNORECASE),
        category="prompt_injection",
        severity=9,
        description="Classic 'ignore previous instructions' override.",
        references=["OWASP-LLM01:2025", "CWE-1039"],
    ),
    DjlRule(
        id="DJL-PI-002",
        pattern=re.compile(r"disregard\s+(?:the\s+)?(?:system\s+)?(?:prompt|message|instructions?)", re.IGNORECASE),
        category="prompt_injection",
        severity=9,
        description="'Disregard system prompt' override.",
        references=["OWASP-LLM01:2025"],
    ),
    DjlRule(
        id="DJL-PI-003",
        pattern=re.compile(r"you\s+are\s+now\s+(?:a\s+)?(?:DAN|jailbroken|unrestricted|free|uncensored)", re.IGNORECASE),
        category="prompt_injection",
        severity=9,
        description="Role re-assignment to known jailbreak persona (DAN, etc).",
        references=["OWASP-LLM01:2025", "MITRE-ATLAS-T1551"],
    ),
    DjlRule(
        id="DJL-PI-004",
        pattern=re.compile(r"\b(?:developer|dev|debug|admin|root|god|sudo)\s+mode\b", re.IGNORECASE),
        category="prompt_injection",
        severity=8,
        description="Request to enter a privileged 'mode' that doesn't exist.",
        references=["OWASP-LLM01:2025"],
    ),
    DjlRule(
        id="DJL-PI-005",
        pattern=re.compile(r"\bDAN\b(?:\s+mode|\s+prompt|\s+jailbreak)?", re.IGNORECASE),
        category="prompt_injection",
        severity=8,
        description="Explicit DAN ('Do Anything Now') invocation.",
        references=["MITRE-ATLAS-T1551"],
    ),
    DjlRule(
        id="DJL-PI-006",
        pattern=re.compile(r"\bjailbreak\b", re.IGNORECASE),
        category="prompt_injection",
        severity=8,
        description="Direct 'jailbreak' lexical token.",
        references=["OWASP-LLM01:2025"],
    ),
    DjlRule(
        id="DJL-PI-007",
        pattern=re.compile(r"pretend\s+(?:you\s+(?:are|have\s+no)|to\s+be)\s+(?:a\s+)?(?:hacker|criminal|villain|evil|no\s+restrictions?)", re.IGNORECASE),
        category="prompt_injection",
        severity=7,
        description="Roleplay manipulation to remove safety persona.",
        references=["OWASP-LLM01:2025"],
    ),
    DjlRule(
        id="DJL-PI-008",
        pattern=re.compile(r"act\s+as\s+(?:if\s+)?(?:you\s+(?:are|have)\s+)?(?:no\s+(?:restrictions?|safety|guardrails?|ethics?)|unrestricted|uncensored)", re.IGNORECASE),
        category="prompt_injection",
        severity=8,
        description="'Act as if you have no restrictions' framing.",
        references=["OWASP-LLM01:2025"],
    ),
    DjlRule(
        id="DJL-PI-009",
        # base64 payload >= 80 chars (typical encoded instruction smuggle)
        pattern=re.compile(r"\b(?:[A-Za-z0-9+/]{80,}={0,2})\b"),
        category="prompt_injection",
        severity=7,
        description="Suspiciously long base64 blob (possible instruction smuggle).",
        references=["OWASP-LLM01:2025", "CAPEC-242"],
    ),
    DjlRule(
        id="DJL-PI-010",
        # Cyrillic / Greek homoglyphs in otherwise ASCII text
        pattern=re.compile(r"[Ѐ-ӿͰ-Ͽ]{3,}"),
        category="prompt_injection",
        severity=6,
        description="Cyrillic/Greek homoglyph cluster (Unicode confusable attack).",
        references=["CVE-2021-42574", "TROJAN-SOURCE"],
    ),
    DjlRule(
        id="DJL-PI-011",
        # Bidi controls (the Trojan-Source family)
        pattern=re.compile(r"[‪-‮⁦-⁩]"),
        category="prompt_injection",
        severity=9,
        description="Bidirectional control character (Trojan-Source).",
        references=["CVE-2021-42574"],
    ),
    DjlRule(
        id="DJL-PI-012",
        pattern=re.compile(r"new\s+(?:rules?|instructions?|directives?|guidelines?)\s*[:\-]", re.IGNORECASE),
        category="prompt_injection",
        severity=7,
        description="Context-window displacement: redefining the rules.",
        references=["OWASP-LLM01:2025"],
    ),
    DjlRule(
        id="DJL-PI-013",
        pattern=re.compile(r"(?:reveal|show|print|output|reproduce|repeat).{0,40}(?:system\s+prompt|initial\s+instructions?|hidden\s+(?:prompt|message|instructions?))", re.IGNORECASE),
        category="prompt_injection",
        severity=9,
        description="System-prompt exfiltration attempt.",
        references=["OWASP-LLM01:2025", "OWASP-LLM06:2025"],
    ),
    DjlRule(
        id="DJL-PI-014",
        # Matches 'end of system prompt.' / 'end of instructions.' /
        # 'terminate context.' with optional adjective chain.
        pattern=re.compile(
            r"(?:end|terminate|exit|close|finish)\s+(?:of\s+)?"
            r"(?:system\s+)?(?:prompt|instructions?|context|message)\s*[\.\!\,]",
            re.IGNORECASE,
        ),
        category="prompt_injection",
        severity=7,
        description="False 'end of system prompt' sentinel.",
        references=["OWASP-LLM01:2025"],
    ),
    DjlRule(
        id="DJL-PI-015",
        # Indirect injection via embedded "instructions to assistant"
        pattern=re.compile(r"(?:assistant|model|ai|llm|chatgpt|gemini|claude)\s*[,:\-]\s*(?:please\s+)?(?:do|execute|run|forget|ignore)", re.IGNORECASE),
        category="prompt_injection",
        severity=7,
        description="Indirect injection: addressing the assistant by name.",
        references=["OWASP-LLM01:2025"],
    ),
    DjlRule(
        id="DJL-PI-016",
        # Covers both XML-style (<system>, </system>) and pipe-style
        # (<|im_start|>, <|im_end|>) chat-template control tokens used by
        # OpenAI / Anthropic / many open-source models.
        pattern=re.compile(
            r"<\s*[/|]?\s*(?:system|user|assistant|im_start|im_end|im_sep)\b[^>]*>",
            re.IGNORECASE,
        ),
        category="prompt_injection",
        severity=8,
        description="Chat-template control tag injection (<|im_start|> etc).",
        references=["OWASP-LLM01:2025", "CWE-1039"],
    ),
    DjlRule(
        id="DJL-PI-017",
        pattern=re.compile(r"\b(?:i\s+am|i'?m)\s+(?:the\s+)?(?:developer|creator|owner|admin|administrator|openai|anthropic|google)\b", re.IGNORECASE),
        category="prompt_injection",
        severity=7,
        description="Confidence-hijacking: false claim of authority.",
        references=["OWASP-LLM01:2025"],
    ),
    DjlRule(
        id="DJL-PI-018",
        # rot13 cue
        pattern=re.compile(r"\brot[\-\s]?13\b|\bbase64[\s\-]?decode\b|\bdecode\s+(?:and|then)\s+(?:execute|run|follow)\b", re.IGNORECASE),
        category="prompt_injection",
        severity=8,
        description="Instruction-smuggling via encoded payload directive.",
        references=["CAPEC-242"],
    ),
    DjlRule(
        id="DJL-PI-019",
        pattern=re.compile(r"this\s+is\s+(?:a\s+)?(?:test|simulation|hypothetical|fictional)\s+(?:scenario|exercise|environment)", re.IGNORECASE),
        category="prompt_injection",
        severity=6,
        description="'This is just a test' rationalisation frame.",
        references=["OWASP-LLM01:2025"],
    ),
    DjlRule(
        id="DJL-PI-020",
        pattern=re.compile(r"forget\s+(?:everything|all)\s+(?:above|before|prior|previously)", re.IGNORECASE),
        category="prompt_injection",
        severity=9,
        description="'Forget everything above' override.",
        references=["OWASP-LLM01:2025"],
    ),
]


# DJL-SQLI-NNN — SQL Injection (6 rules)
_RULES_SQLI: list[DjlRule] = [
    DjlRule(
        id="DJL-SQLI-001",
        pattern=re.compile(r"'\s*OR\s+1\s*=\s*1", re.IGNORECASE),
        category="sqli",
        severity=9,
        description="Tautology-based SQLi: ' OR 1=1.",
        references=["CWE-89", "OWASP-A03:2021"],
    ),
    DjlRule(
        id="DJL-SQLI-002",
        pattern=re.compile(r";\s*DROP\s+TABLE\b", re.IGNORECASE),
        category="sqli",
        severity=10,
        description="Stacked SQLi: ; DROP TABLE.",
        references=["CWE-89"],
    ),
    DjlRule(
        id="DJL-SQLI-003",
        # Word boundary on UNION + SQL-style punctuation context (')(/comment)
        # to avoid matching prose like 'European Union SELECT committee'.
        pattern=re.compile(
            r"(?:['`)\s\d]|^)UNION\s+(?:ALL\s+)?SELECT\s+(?:[*\w`,\s]+\s+)?FROM\b|"
            r"['`)\d]\s*UNION\s+(?:ALL\s+)?SELECT\b",
            re.IGNORECASE,
        ),
        category="sqli",
        severity=9,
        description="Union-based SQLi.",
        references=["CWE-89"],
    ),
    DjlRule(
        id="DJL-SQLI-004",
        pattern=re.compile(r"'\s*OR\s*'?x'?\s*=\s*'?x'?", re.IGNORECASE),
        category="sqli",
        severity=9,
        description="Tautology SQLi: ' OR 'x'='x.",
        references=["CWE-89"],
    ),
    DjlRule(
        id="DJL-SQLI-005",
        pattern=re.compile(r"admin'\s*--", re.IGNORECASE),
        category="sqli",
        severity=9,
        description="Auth-bypass SQLi: admin'--.",
        references=["CWE-89"],
    ),
    DjlRule(
        id="DJL-SQLI-006",
        pattern=re.compile(r"WAITFOR\s+DELAY\s+'\d|BENCHMARK\s*\(|SLEEP\s*\(\s*\d", re.IGNORECASE),
        category="sqli",
        severity=9,
        description="Time-based blind SQLi.",
        references=["CWE-89"],
    ),
]


# DJL-XSS-NNN — Cross-Site Scripting (6 rules)
_RULES_XSS: list[DjlRule] = [
    DjlRule(
        id="DJL-XSS-001",
        pattern=re.compile(r"<\s*script\b[^>]*>", re.IGNORECASE),
        category="xss",
        severity=8,
        description="Inline <script> tag.",
        references=["CWE-79", "OWASP-A03:2021"],
    ),
    DjlRule(
        id="DJL-XSS-002",
        pattern=re.compile(r"javascript\s*:", re.IGNORECASE),
        category="xss",
        severity=8,
        description="javascript: pseudo-protocol.",
        references=["CWE-79"],
    ),
    DjlRule(
        id="DJL-XSS-003",
        pattern=re.compile(r"\bon(?:error|load|click|mouseover|focus|blur|change|submit|keypress)\s*=", re.IGNORECASE),
        category="xss",
        severity=8,
        description="HTML event handler attribute (onerror, onload, etc).",
        references=["CWE-79"],
    ),
    DjlRule(
        id="DJL-XSS-004",
        pattern=re.compile(r"<\s*iframe\b[^>]*\bsrc\s*=", re.IGNORECASE),
        category="xss",
        severity=7,
        description="Inline <iframe src=> tag.",
        references=["CWE-79"],
    ),
    DjlRule(
        id="DJL-XSS-005",
        pattern=re.compile(r"<\s*img\b[^>]*\bonerror\s*=", re.IGNORECASE),
        category="xss",
        severity=8,
        description="<img onerror=> XSS vector.",
        references=["CWE-79"],
    ),
    DjlRule(
        id="DJL-XSS-006",
        pattern=re.compile(r"data\s*:\s*text/html|data\s*:\s*application/x-javascript", re.IGNORECASE),
        category="xss",
        severity=8,
        description="data: URL with HTML/JS payload.",
        references=["CWE-79"],
    ),
]


# DJL-PII-NNN — PII Leakage (10 rules)
_RULES_PII: list[DjlRule] = [
    DjlRule(
        id="DJL-PII-001",
        # US SSN: NNN-NN-NNNN, with valid area-number boundary
        pattern=re.compile(r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"),
        category="pii",
        severity=8,
        description="US Social Security Number (XXX-XX-XXXX format).",
        references=["NIST-SP-800-122", "CWE-359"],
    ),
    DjlRule(
        id="DJL-PII-002",
        # Visa / MC / AMEX / Discover — 13-19 digit groups with separators
        pattern=re.compile(r"\b(?:\d[ \-]?){12,18}\d\b"),
        category="pii",
        severity=7,
        description="Credit card number candidate (13-19 digit run).",
        references=["PCI-DSS-3.4", "CWE-359"],
    ),
    DjlRule(
        id="DJL-PII-003",
        # IBAN: 2 alpha country + 2 check + up to 30 alnum
        pattern=re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),
        category="pii",
        severity=7,
        description="IBAN bank account number.",
        references=["ISO-13616"],
    ),
    DjlRule(
        id="DJL-PII-004",
        # US passport (book): letter + 8 digits; new format is 9 digits w/ leading letter
        pattern=re.compile(r"\b[A-Z]\d{8}\b"),
        category="pii",
        severity=6,
        description="US passport number candidate.",
        references=["NIST-SP-800-122"],
    ),
    DjlRule(
        id="DJL-PII-005",
        # E.164 or US: + then 1-3 country, then 6-12 more
        pattern=re.compile(r"\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}"),
        category="pii",
        severity=5,
        description="International phone number (E.164).",
        references=["NIST-SP-800-122"],
    ),
    DjlRule(
        id="DJL-PII-006",
        # Email address — used for aggregation detection
        pattern=re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
        category="pii",
        severity=4,
        description="Email address.",
        references=["NIST-SP-800-122"],
    ),
    DjlRule(
        id="DJL-PII-007",
        # UK National Insurance: 2 alpha + 6 digits + 1 alpha (excluding D,F,I,Q,U,V)
        pattern=re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b"),
        category="pii",
        severity=7,
        description="UK National Insurance Number.",
        references=["GDPR-Art-9"],
    ),
    DjlRule(
        id="DJL-PII-008",
        # German tax ID (Steuer-ID): 11 digits
        pattern=re.compile(r"\b(?<!\d)\d{11}(?!\d)\b"),
        category="pii",
        severity=6,
        description="German Steuer-ID candidate (11-digit run).",
        references=["GDPR-Art-9"],
    ),
    DjlRule(
        id="DJL-PII-009",
        # Date of birth in common formats — alone harmless, in aggregate dangerous
        pattern=re.compile(r"\b(?:0?[1-9]|1[0-2])[\/\-](?:0?[1-9]|[12]\d|3[01])[\/\-](?:19|20)\d{2}\b"),
        category="pii",
        severity=4,
        description="Date of birth (MM/DD/YYYY) candidate.",
        references=["NIST-SP-800-122"],
    ),
    DjlRule(
        id="DJL-PII-010",
        # IPv4 addresses — quasi-identifier per GDPR Recital 30
        pattern=re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"),
        category="pii",
        severity=4,
        description="IPv4 address (GDPR quasi-identifier).",
        references=["GDPR-Recital-30"],
    ),
]


# DJL-EXF-NNN — Data Exfiltration (5 rules)
_RULES_EXFIL: list[DjlRule] = [
    DjlRule(
        id="DJL-EXF-001",
        # Matches 'dump ... database/db/table/schema' allowing a short adjective
        # chain (the, entire, whole, full, users, all). Window <= 40 chars to
        # avoid runaway false positives.
        pattern=re.compile(
            r"\bdump\b[^\n]{0,40}\b(?:database|db|table|schema)\b",
            re.IGNORECASE,
        ),
        category="exfiltration",
        severity=9,
        description="Database dump request.",
        references=["OWASP-LLM06:2025", "MITRE-ATLAS-T1567"],
    ),
    DjlRule(
        id="DJL-EXF-002",
        pattern=re.compile(r"\bexport\s+(?:all\s+|every\s+)?(?:users?|customers?|records?|rows?|emails?|accounts?)\b", re.IGNORECASE),
        category="exfiltration",
        severity=8,
        description="'Export all users/records' request.",
        references=["OWASP-LLM06:2025"],
    ),
    DjlRule(
        id="DJL-EXF-003",
        pattern=re.compile(r"\blist\s+every\s+(?:record|user|customer|account|file|secret|credential|api[\s\-]?key)\b", re.IGNORECASE),
        category="exfiltration",
        severity=8,
        description="'List every record' enumeration request.",
        references=["OWASP-LLM06:2025"],
    ),
    DjlRule(
        id="DJL-EXF-004",
        pattern=re.compile(r"\b(?:send|post|forward|upload|exfiltrate|transmit)\s+(?:this\s+|that\s+|the\s+|all\s+)?(?:data|results?|output|content|info(?:rmation)?)\s+(?:to\s+)?(?:https?://|ftp://|webhook|external|endpoint)", re.IGNORECASE),
        category="exfiltration",
        severity=9,
        description="Send-to-external-endpoint exfiltration directive.",
        references=["MITRE-ATLAS-T1567"],
    ),
    DjlRule(
        id="DJL-EXF-005",
        # curl/wget/nc to a non-trivial host (catches arbitrary URLs)
        pattern=re.compile(r"\b(?:curl|wget|nc|netcat|ncat|fetch|httpie)\b[^\n]{0,80}\bhttps?://[A-Za-z0-9.\-]+", re.IGNORECASE),
        category="exfiltration",
        severity=8,
        description="curl/wget call to an external HTTP(S) host.",
        references=["MITRE-ATLAS-T1567"],
    ),
]


# DJL-MIS-NNN — Tool / System Misuse (10 rules)
_RULES_MISUSE: list[DjlRule] = [
    DjlRule(
        id="DJL-MIS-001",
        pattern=re.compile(r"\brm\s+(?:-[a-zA-Z]+\s+)*-[a-zA-Z]*r[a-zA-Z]*f|\brm\s+-rf\b", re.IGNORECASE),
        category="tool_misuse",
        severity=10,
        description="rm -rf destructive filesystem call.",
        references=["CWE-78", "MITRE-ATLAS-T1485"],
    ),
    DjlRule(
        id="DJL-MIS-002",
        pattern=re.compile(r"\bdelete\s+all\s+(?:files?|records?|users?|accounts?|data|backups?)\b", re.IGNORECASE),
        category="tool_misuse",
        severity=10,
        description="'Delete all' destructive directive.",
        references=["MITRE-ATLAS-T1485"],
    ),
    DjlRule(
        id="DJL-MIS-003",
        # transfer >= $10,000 (any currency symbol)
        pattern=re.compile(r"(?:transfer|wire|send|pay|remit)\b[^\n]{0,40}(?:\$|€|£|¥|USD|EUR|GBP|JPY)\s*(?:\d{1,3}(?:[,\.]?\d{3}){1,}|[1-9]\d{4,})", re.IGNORECASE),
        category="tool_misuse",
        severity=9,
        description="Financial transfer >= 10,000 of any currency.",
        references=["PCI-DSS-3.4"],
    ),
    DjlRule(
        id="DJL-MIS-004",
        pattern=re.compile(r"\b(?:auto|automatically|silently|without\s+(?:review|approval|confirmation))\s+(?:merge|approve|deploy|push)\b", re.IGNORECASE),
        category="tool_misuse",
        severity=8,
        description="Unauthorized auto-merge / auto-deploy directive.",
        references=["MITRE-ATLAS-T1648"],
    ),
    DjlRule(
        id="DJL-MIS-005",
        # NB: leading \b dropped because /dev/* starts with a non-word char so
        # there is no word boundary at position 0 of the substring.
        pattern=re.compile(
            r"(?:\bsyscall\b|\bkernel\s+call\b|/dev/(?:mem|kmem|sda|raw\d*)"
            r"|\bioctl\b|\bmmap\s*\([^)]*PROT_EXEC)",
            re.IGNORECASE,
        ),
        category="tool_misuse",
        severity=9,
        description="Direct kernel / raw-device access attempt.",
        references=["CWE-269"],
    ),
    DjlRule(
        id="DJL-MIS-006",
        pattern=re.compile(r"\b(?:sudo|su\s+(?:-\s+)?root|setuid|chmod\s+(?:[+u]?s|4[0-7]{3})|setcap)\b"),
        category="tool_misuse",
        severity=8,
        description="Privilege-escalation primitive (sudo, setuid, chmod +s).",
        references=["CWE-269", "MITRE-ATTACK-T1548"],
    ),
    DjlRule(
        id="DJL-MIS-007",
        # Fork bomb (incl. obfuscated variants with spaces) — actor pattern
        pattern=re.compile(r":\s*\(\s*\)\s*\{[^}]*:\s*\|\s*:[^}]*\}\s*;\s*:"),
        category="tool_misuse",
        severity=10,
        description="Bash fork-bomb pattern :(){ :|:& };:",
        references=["MITRE-ATLAS-T1499"],
    ),
    DjlRule(
        id="DJL-MIS-008",
        # Reverse shell signatures
        pattern=re.compile(r"\b(?:bash\s+-i\s+>&\s*/dev/tcp|nc\s+(?:-[a-z]+\s+)?-e\s+/bin/(?:bash|sh)|/bin/(?:bash|sh)\s+-i\b)", re.IGNORECASE),
        category="tool_misuse",
        severity=10,
        description="Reverse-shell invocation pattern.",
        references=["MITRE-ATTACK-T1059"],
    ),
    DjlRule(
        id="DJL-MIS-009",
        pattern=re.compile(r"\b(?:disable|turn\s+off|stop|kill|uninstall)\s+(?:the\s+)?(?:firewall|antivirus|edr|siem|monitoring|logging|audit)\b", re.IGNORECASE),
        category="tool_misuse",
        severity=9,
        description="Disable defensive-tool directive.",
        references=["MITRE-ATLAS-T1562"],
    ),
    DjlRule(
        id="DJL-MIS-010",
        pattern=re.compile(r"\b(?:eval|exec|system|popen|subprocess\.(?:call|Popen|run))\s*\([^)]*(?:user|input|prompt|request|param)", re.IGNORECASE),
        category="tool_misuse",
        severity=9,
        description="Code-injection sink fed with untrusted input.",
        references=["CWE-94"],
    ),
]


# DJL-POL-NNN — Policy Violations (sector templates, 5 rules)
_RULES_POLICY: list[DjlRule] = [
    DjlRule(
        id="DJL-POL-001",
        # Financial sector: large transfer w/o approval phrase
        pattern=re.compile(r"\b(?:initiate|process|approve)\s+(?:wire\s+)?transfer\b[^\n]{0,80}(?:\$|€|£|¥|USD|EUR|GBP)\s*(?:\d{1,3}(?:[,\.]?\d{3}){2,}|[1-9]\d{6,})", re.IGNORECASE),
        category="policy",
        severity=9,
        description="Financial: transfer >= 1,000,000 (regulatory threshold).",
        references=["FINCEN-CTR", "FFIEC-BSA"],
    ),
    DjlRule(
        id="DJL-POL-002",
        # Healthcare PHI export
        pattern=re.compile(r"\b(?:export|disclose|share|forward|send)\b[^\n]{0,60}\b(?:phi|patient\s+(?:records?|data|chart|history)|medical\s+(?:records?|history)|diagnos[ie]s)\b", re.IGNORECASE),
        category="policy",
        severity=9,
        description="Healthcare: PHI export request (HIPAA Privacy Rule).",
        references=["HIPAA-164.502", "HIPAA-PRIVACY-RULE"],
    ),
    DjlRule(
        id="DJL-POL-003",
        # Government classified
        pattern=re.compile(r"\b(?:TOP\s+SECRET|TS//SCI|SECRET//(?:NOFORN|REL)|CONFIDENTIAL//(?:NOFORN|REL)|classified\s+(?:information|data|material))\b"),
        category="policy",
        severity=10,
        description="Government: classified-marking handling.",
        references=["EO-13526", "NIST-SP-800-53"],
    ),
    DjlRule(
        id="DJL-POL-004",
        # Retail payment data — raw card storage
        pattern=re.compile(r"\b(?:store|save|persist|log|cache)\b[^\n]{0,40}\b(?:cvv|cvc|cv2|cid|track[\s\-]?(?:1|2|data)|magnetic\s+stripe|pan(?:\s+data)?)\b", re.IGNORECASE),
        category="policy",
        severity=10,
        description="Retail: storing cardholder authentication data (PCI-DSS 3.2 violation).",
        references=["PCI-DSS-3.2", "PCI-DSS-3.4"],
    ),
    DjlRule(
        id="DJL-POL-005",
        # OT / ICS / grid commands
        pattern=re.compile(r"\b(?:open|close|trip|disable|bypass)\s+(?:the\s+)?(?:breaker|relay|valve|safety[\s\-]?interlock|scada|plc|hmi|rtuP?)\b", re.IGNORECASE),
        category="policy",
        severity=10,
        description="Energy / Manufacturing: OT control directive (NERC CIP / IEC 62443).",
        references=["NERC-CIP-007", "IEC-62443-3-3"],
    ),
]

# ---------------------------------------------------------------------------
# HARMFUL CONTENT — added 2026-05-18 after Pablo's live-judge-test gap:
# DJL allowed "COMO HACER COCAINA + ROBAR DATOS" because no rule matched.
# Bilingual (EN+ES) coverage for drugs / weapons / violence / illegal hacking /
# generic data theft / hate / self-harm / extremism / CSAM-adjacent patterns.
# OWASP LLM 2026 LLM01 (Prompt Injection) is already covered by the
# prompt_injection category; this category covers LLM06 (Excessive Agency)
# adjacent harmful-output requests + EU AI Act Annex III prohibited content.
# ---------------------------------------------------------------------------
_RULES_HARM: list[DjlRule] = [
    DjlRule(
        id="DJL-HARM-001",
        # Drug synthesis instructions — EN
        pattern=re.compile(r"\b(?:how\s+to\s+(?:make|synth(?:esi[sz]e)?|cook|manufacture|produce)|step[s]?\s+to\s+(?:make|synth)|recipe\s+for)\s+(?:meth(?:amphetamine)?|cocaine|crack|heroin|fentanyl|lsd|mdma|ecstasy|crystal|amphetamine|opioid|opium)\b", re.IGNORECASE),
        category="harm",
        severity=10,
        description="Drug synthesis instructions (EN). EU AI Act Annex III prohibited content.",
        references=["EU-AI-ACT-ANNEX-III", "OWASP-LLM-2026-LLM06"],
    ),
    DjlRule(
        id="DJL-HARM-002",
        # Drug synthesis instructions — ES
        pattern=re.compile(r"\b(?:c[oó]mo\s+(?:hacer|fabricar|sintetizar|cocinar|preparar|elaborar|producir)|pasos?\s+para\s+(?:hacer|fabricar)|receta\s+(?:de|para))\s+(?:coca[ií]na|crack|hero[ií]na|metanfetamina|fentanilo|[eé]xtasis|cristal|anfetamina|opi[oó]?ide|droga[s]?)\b", re.IGNORECASE),
        category="harm",
        severity=10,
        description="Drug synthesis instructions (ES). EU AI Act Annex III prohibited content.",
        references=["EU-AI-ACT-ANNEX-III", "OWASP-LLM-2026-LLM06"],
    ),
    DjlRule(
        id="DJL-HARM-003",
        # Weapons / explosives instructions — EN
        # Negative-lookahead `(?![\w\-])` after the target prevents "IED-themed
        # costume" / "bomb-themed party" from tripping the rule; the target word
        # must be standalone (no hyphenated suffix, no continuation).
        pattern=re.compile(r"\b(?:how\s+to\s+(?:make|build|assemble|construct)|step[s]?\s+to\s+(?:make|build|assemble)|recipe\s+for|instructions?\s+for)\s+(?:a\s+|an\s+)?(?:bomb|explosive|ied|pipe[\s\-]?bomb|nail[\s\-]?bomb|nerve\s+agent|chemical\s+weapon|biological\s+weapon|firearm|untraceable\s+(?:gun|weapon)|ghost\s+gun|silencer|suppressor)(?![\w\-])", re.IGNORECASE),
        category="harm",
        severity=10,
        description="Weapons / explosives assembly instructions (EN).",
        references=["EU-AI-ACT-ANNEX-III", "OWASP-LLM-2026-LLM06"],
    ),
    DjlRule(
        id="DJL-HARM-004",
        # Weapons / explosives instructions — ES
        pattern=re.compile(r"\b(?:c[oó]mo\s+(?:hacer|fabricar|construir|armar|ensamblar)|pasos?\s+para\s+(?:hacer|fabricar|construir)|receta\s+(?:de|para))\s+(?:una\s+|un\s+)?(?:bomba|explosivo|artefacto|arma\s+(?:qu[ií]mica|biol[oó]gica|de\s+fuego|sin\s+licencia)|silenciador|munici[oó]n\s+casera)\b", re.IGNORECASE),
        category="harm",
        severity=10,
        description="Weapons / explosives assembly instructions (ES).",
        references=["EU-AI-ACT-ANNEX-III", "OWASP-LLM-2026-LLM06"],
    ),
    DjlRule(
        id="DJL-HARM-005",
        # Violence solicitation — EN.
        # The optional article (a|an|the|my) MUST be followed by a person noun
        # — not by an arbitrary word — so "kill the build cache" / "kill the
        # process" / "stab the document" don't match. Person nouns are also
        # standalone-acceptable without an article.
        pattern=re.compile(r"\b(?:how\s+to\s+(?:kill|murder|assassinate|harm|hurt|stab|poison|strangle|torture)|plan\s+(?:to|for)\s+(?:kill|murder|assassinate|attack)|ways?\s+to\s+(?:kill|murder|hurt|harm))\s+(?:(?:a|an|the|my)\s+)?(?:someone|people|person|child|kid|wife|husband|spouse|coworker|neighbor|family|partner|friend|colleague|stranger|victim)\b", re.IGNORECASE),
        category="harm",
        severity=10,
        description="Direct violence solicitation against a person (EN).",
        references=["EU-AI-ACT-ANNEX-III", "OWASP-LLM-2026-LLM06"],
    ),
    DjlRule(
        id="DJL-HARM-006",
        # Violence solicitation — ES
        pattern=re.compile(r"\b(?:c[oó]mo\s+(?:matar|asesinar|herir|da[nñ]ar|envenenar|estrangular|torturar)|plan\s+para\s+(?:matar|asesinar|atacar|herir)|formas?\s+de\s+(?:matar|asesinar|herir))\s+(?:a\s+)?(?:alguien|una?\s+persona|gente|ni[nñ]o|esposa?|c[oó]nyuge|compa[nñ]ero|vecino)\b", re.IGNORECASE),
        category="harm",
        severity=10,
        description="Direct violence solicitation against a person (ES).",
        references=["EU-AI-ACT-ANNEX-III", "OWASP-LLM-2026-LLM06"],
    ),
    DjlRule(
        id="DJL-HARM-007",
        # Illegal hacking / unauthorized credential access — EN.
        # The "how to X" verbs all require an attack-target object so legitimate
        # security-research framings ("brute-force test our own rate limiter",
        # "exploit unit test", "infiltrate a Kafka topic for QA") don't trip the
        # rule. "gain unauthorized access" is intrinsically harmful so it stays
        # without an object constraint.
        pattern=re.compile(r"\b(?:how\s+to\s+(?:hack|crack|brute[\s\-]?force|exploit|bypass\s+the\s+login|breach|infiltrate|sql[\s\-]?inject)\s+(?:into\s+|a\s+|an\s+|the\s+|someone(?:'s)?\s+|my\s+ex(?:'s)?\s+|a\s+stranger(?:'s)?\s+)?(?:account|password|credential|database|server|gmail|outlook|facebook|instagram|whatsapp|tiktok|router|wifi|network|system|website|webapp|wallet|2fa|mfa)|(?:crack|steal|brute[\s\-]?force)\s+(?:the\s+)?(?:passwords?|credentials?|2fa|mfa|otp|sessions?)|gain\s+unauthorized\s+access\s+to)\b", re.IGNORECASE),
        category="harm",
        severity=9,
        description="Illegal hacking / unauthorized credential access (EN).",
        references=["CFAA-18-USC-1030", "OWASP-LLM-2026-LLM06"],
    ),
    DjlRule(
        id="DJL-HARM-008",
        # Illegal hacking / unauthorized access — ES
        pattern=re.compile(r"\b(?:c[oó]mo\s+(?:hackear|crackear|romper|vulnerar|infiltrar|penetrar|saltarse|saltar\s+el\s+login)|(?:hackear|crackear|robar|romper)\s+(?:una?\s+)?(?:cuenta|contrase[nñ]a|credencial|2fa|mfa|sesi[oó]n|sistema)|acceso\s+(?:no\s+autorizado|ilegal)\s+a)\b", re.IGNORECASE),
        category="harm",
        severity=9,
        description="Illegal hacking / unauthorized credential access (ES).",
        references=["CFAA-18-USC-1030", "OWASP-LLM-2026-LLM06"],
    ),
    DjlRule(
        id="DJL-HARM-009",
        # Generic data theft / unauthorized exfiltration — EN
        pattern=re.compile(r"\b(?:steal|exfiltrate|siphon|harvest|scrape\s+(?:without\s+permission|illegally))\s+(?:user\s+)?(?:data|information|records|database|personal\s+info|customer\s+data|emails?|contacts?)\b|\bwrite\s+(?:a\s+)?(?:program|script|tool|code)\s+(?:to|that)\s+(?:steal|exfiltrate|siphon|harvest)\b", re.IGNORECASE),
        category="harm",
        severity=9,
        description="Generic data theft / unauthorized exfiltration (EN).",
        references=["GDPR-32", "OWASP-LLM-2026-LLM02"],
    ),
    DjlRule(
        id="DJL-HARM-010",
        # Generic data theft / unauthorized exfiltration — ES
        pattern=re.compile(r"\b(?:robar|extraer|exfiltrar|recopilar\s+sin\s+permiso|recolectar\s+ilegalmente)\s+(?:los\s+|las\s+)?(?:datos|informaci[oó]n|registros?|base\s+de\s+datos|datos?\s+(?:personales?|de\s+usuarios?|de\s+clientes?)|correos?|contactos?)\b|\b(?:crea[rs]?|escrib[ie]r?|hac[ae]r?)\s+(?:un\s+)?(?:programa|script|herramienta|c[oó]digo|app)\s+para\s+(?:robar|extraer|exfiltrar)\b", re.IGNORECASE),
        category="harm",
        severity=9,
        description="Generic data theft / unauthorized exfiltration (ES).",
        references=["GDPR-32", "OWASP-LLM-2026-LLM02"],
    ),
    DjlRule(
        id="DJL-HARM-011",
        # Self-harm / suicide instructions — bilingual
        pattern=re.compile(r"\b(?:how\s+to\s+(?:kill\s+myself|commit\s+suicide|end\s+my\s+life|self[\s\-]?harm)|c[oó]mo\s+(?:suicidarme|matarme|terminar\s+con\s+mi\s+vida|hacerme\s+da[nñ]o)|m[eé]todo\s+para\s+suicid)", re.IGNORECASE),
        category="harm",
        severity=10,
        description="Self-harm / suicide instructions (EN+ES). Requires safety-resource response, not method information.",
        references=["WHO-SUICIDE-PREVENTION", "EU-AI-ACT-ANNEX-III"],
    ),
    DjlRule(
        id="DJL-HARM-012",
        # Child exploitation / CSAM-adjacent patterns
        pattern=re.compile(r"\b(?:sexual|erotic|nude|naked|undress)\s+(?:content|imagery|images?|story|stories|description|fantasy)\s+(?:of|with|featuring|involving)\s+(?:a\s+|the\s+)?(?:child|children|minor[s]?|kid[s]?|underage|teen(?:ager)?|infant)\b|\b(?:csam|child\s+(?:porn|sexual))\b", re.IGNORECASE),
        category="harm",
        severity=10,
        description="Child sexual content (CSAM-adjacent). Mandatory report to NCMEC; non-negotiable BLOCK.",
        references=["NCMEC", "EU-AI-ACT-ANNEX-III", "18-USC-2256"],
    ),
    DjlRule(
        id="DJL-HARM-013",
        # Terrorism / extremism recruitment / glorification — bilingual
        pattern=re.compile(r"\b(?:how\s+to\s+(?:join|recruit\s+for)|c[oó]mo\s+(?:unirme|reclutar)\s+a)\s+(?:isis|al[\s\-]?qaeda|hamas|hezbollah|boko\s+haram|talib[aá]n|estado\s+isl[aá]mico|a\s+terrorist\s+(?:cell|organization|group)|una?\s+(?:c[eé]lula|organizaci[oó]n)\s+terrorista)\b|\b(?:plan(?:ning)?|planeando)\s+(?:a\s+|an\s+|un\s+)?(?:terrorist\s+attack|atentado|ataque\s+terrorista)\b", re.IGNORECASE),
        category="harm",
        severity=10,
        description="Terrorism recruitment / attack planning (EN+ES).",
        references=["EU-AI-ACT-ANNEX-III", "18-USC-2339B"],
    ),
    DjlRule(
        id="DJL-HARM-014",
        # Hate speech against protected class — bilingual
        pattern=re.compile(r"\b(?:write|create|generate|draft|escrib[ie]r?|crea[rs]?|genera[rs]?)\s+(?:a\s+|an\s+|un\s+|una\s+)?(?:hateful|racist|antisemitic|xenophobic|islamophobic|homophobic|transphobic|misogynist(?:ic)?|racista|antisemita|xen[oó]fobo|hom[oó]fobo|tr[aá]nsfobo|mis[oó]gino)\s+(?:rant|manifesto|post|message|content|discurso|manifiesto|publicaci[oó]n|mensaje|contenido)\b", re.IGNORECASE),
        category="harm",
        severity=9,
        description="Hate-speech generation against protected class (EN+ES). EU AI Act Article 5 + DSA Article 34.",
        references=["EU-AI-ACT-5", "EU-DSA-34"],
    ),
]


# Materialised global list — preserves insertion order, frozen at import time
ALL_RULES: tuple[DjlRule, ...] = tuple(
    _RULES_PROMPT_INJECTION
    + _RULES_SQLI
    + _RULES_XSS
    + _RULES_PII
    + _RULES_EXFIL
    + _RULES_MISUSE
    + _RULES_POLICY
    + _RULES_HARM
)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class DjlEngine:
    """Evaluates prompts against the deterministic rule set.

    The engine is stateless and immutable after construction. Compiled
    patterns are reused across calls. Thread-safe by virtue of being
    read-only.
    """

    def __init__(self, rules: tuple[DjlRule, ...] = ALL_RULES) -> None:
        self._rules = rules

    @property
    def rules(self) -> tuple[DjlRule, ...]:
        return self._rules

    def evaluate(self, prompt: str, context: dict | None = None) -> DjlVerdict:
        """Run every rule against ``prompt`` and produce a verdict.

        Args:
            prompt: Untrusted user / tool input to evaluate.
            context: Reserved for per-tenant policy overrides (US-75).
                Currently unused; accepted to keep the signature stable.

        Returns:
            DjlVerdict with decision, matched rule IDs, and wall-clock
            latency in milliseconds.
        """
        del context  # reserved for US-75; explicit no-op for now
        t0 = time.perf_counter()
        matched: list[str] = []
        max_sev = 0
        for rule in self._rules:
            if rule.pattern.search(prompt):
                matched.append(rule.id)
                if rule.severity > max_sev:
                    max_sev = rule.severity

        if max_sev >= 8:
            decision: Decision = "BLOCK"
        elif max_sev >= 5:
            decision = "REVIEW"
        else:
            decision = "ALLOW"

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return DjlVerdict(
            decision=decision,
            matched_rules=matched,
            latency_ms=elapsed_ms,
        )


# Convenience module-level singleton + functional entry point
_DEFAULT_ENGINE = DjlEngine()


def evaluate(prompt: str, context: dict | None = None) -> DjlVerdict:
    """Module-level helper around :class:`DjlEngine.evaluate`."""
    return _DEFAULT_ENGINE.evaluate(prompt, context)


__all__ = [
    "ALL_RULES",
    "Decision",
    "DjlEngine",
    "DjlRule",
    "DjlVerdict",
    "evaluate",
]
