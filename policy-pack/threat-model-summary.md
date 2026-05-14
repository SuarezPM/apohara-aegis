# Threat Model Summary — Apohara Aegis

> One-page compliance summary extracted from `docs/threat-model.md` (v1.0,
> 2026-05-13). Full document includes threat actor analysis (§1), 6 detailed
> scenarios (§2), and verification artifacts (§6). This summary covers what
> compliance reviewers typically request first.

---

## Layer-by-layer mitigation table (§3)

| Threat | Lobster Trap layer | ContextForge INV-15 layer | Deployment owner |
| ------ | :----------------: | :-----------------------: | :---------------: |
| Prompt injection (known patterns) | DENY | — (perimeter blocks first) | — |
| Credential exposure in prompt | DENY | — | — |
| Credential leak in model response | DENY (egress) | — | — |
| PII request in prompt | DENY | — | — |
| PII leak in model response | DENY (egress) | — | — |
| Data exfiltration patterns | DENY | — | Network egress allowlist |
| Role impersonation | HUMAN_REVIEW | — | Human approval queue |
| Dangerous shell commands | DENY | — | Sandbox / no-shell env |
| Sensitive filesystem path access | DENY | — | OS-level path ACLs |
| **Silent JCR drift under KV reuse** | cannot see | **INV-15 GATE** (formal) | Configure judge_roles |
| Cross-agent context poisoning (known pattern) | partial | partial | Both layers stacked |
| Cross-agent context poisoning (subtle paraphrase) | no | no | TrustLayer-class output verification |
| Audit trail tampering | no (not signed) | no (not signed) | Append-only FS / WORM storage |
| Novel obfuscation patterns | regex coverage limited | no | Model and policy updates |
| Supply-chain attacks (compromised model weights) | no | no | SLSA / sigstore model provenance |

**Reading the table.** Threats with "no" in both layers require the deployment
owner to add the listed mitigation. The honest answer to "is this enough?" is:
for threats marked with a check or DENY/GATE, yes. For the rest, additional
deployment-time controls are required.

---

## Compliance mapping (§4)

### NIST AI Risk Management Framework

| Function | Requirement | Apohara artifact |
| -------- | ----------- | ---------------- |
| GOVERN | Documented policy + accountability | `policy.yaml` (policy); `AUDIT.md` (accountability) |
| MAP | Identify AI-system risks | `docs/threat-model.md` (this is the MAP artifact) |
| MEASURE | Quantitative risk measurement | INV-15 risk score (0–1); LT risk_score (0–1); 1,210-decision sweep: 0 violations |
| MANAGE | Risk mitigation + monitoring | INV-15 gate + LT policy enforcement at runtime; JSONL audit log |

Reference: https://www.nist.gov/itl/ai-risk-management-framework

### EU AI Act (Articles 9–15, enforcement deadline: 2 August 2026)

| Article | Requirement | Apohara artifact |
| ------- | ----------- | ---------------- |
| 9 | Risk management system | `docs/threat-model.md` + `AUDIT.md` |
| 10 | Data and data governance | `logs/*.json` raw measurement logs; `AUDIT.md` honesty discipline |
| 11 | Technical documentation | Paper v2.0.1, Zenodo DOI `10.5281/zenodo.20114594` |
| 12 | Record-keeping | JSONL audit log from Lobster Trap + INV-15 firings |
| 13 | Transparency to deployers | `docs/threat-model.md` + README "60-second judge path" |
| 14 | Human oversight | `HUMAN_REVIEW` policy action (rule: `review_role_impersonation`, priority 88) |
| 15 | Accuracy, robustness, cybersecurity | Adversarial test suite: 11/11 PASS; 1,210-decision exhaustive sweep |

### ISO/IEC 42001:2024 AI Management System

| Clause | Apohara artifact |
| ------ | ---------------- |
| A.6 Leadership | `AUDIT.md` public honesty statement |
| A.7 Planning | `docs/threat-model.md` |
| A.8 Support | `docs/lobstertrap-integration.md` |
| A.9 Operation | `tests/test_lobstertrap_integration.py` 4/4 PASS; LT adversarial suite 11/11 PASS |
| A.10 Performance evaluation | JCR delta measurements (mock baseline 0.23; MI300X 3.55x reduction) |
| A.11 Improvement | `AUDIT.md` entries 1–11: documented improvement record V6.0 → V7.0.0-rc.2 |

---

## Acknowledged unknowns (§5 — honesty contract)

These gaps are documented here explicitly so a regulator who asks "what do you
not cover?" gets a direct answer.

1. **Novel jailbreak patterns** not yet in the regex set. Policy refreshed per
   release. Recommended: periodic sweeps with JailbreakBench / HarmBench /
   CyberSecEval 4 corpora.

2. **Semantic PII leakage** (paraphrased SSNs, contextually-inferred personal
   data). Out of regex scope. Requires output-side factuality tooling
   (TrustLayer-class) stacked downstream.

3. **Audit trail cryptographic integrity.** Logs are append-only files today;
   entries are not signed. Recommended deployment: `chattr +a` (Linux) or
   WORM-mode storage. SHA-256 chaining is future work.

4. **Multi-tenant context isolation.** This stack is scoped to single-tenant
   deployments. Multi-tenant adds risks (request hash collision, KV-cache bleed
   across tenants) not yet measured.

5. **Adversarial sweep coverage of judge-only failure modes.** The 1,210-decision
   sweep covered the INV-15 invariant. Full coverage of cross-agent
   judge-poison scenarios is open work.

6. **Long-context (>262K) JCR behavior.** Measurements validated up to 262K
   context on MI300X. JCR behavior at 1M+ context windows is open work.

---

*Full threat model: `docs/threat-model.md`. Apohara Aegis Apache-2.0.*
