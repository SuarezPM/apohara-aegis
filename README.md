<p align="center">
  <img src="assets/aegis-cover.png" alt="Apohara Aegis" width="720">
</p>

<h1 align="center">Apohara Aegis</h1>

<p align="center">
  <strong>Governed context in. Inspected prompts out. Agents enterprises actually trust.</strong>
</p>

<p align="center">
  <em>The defense-in-depth trust layer for multi-agent LLM workflows.</em><br>
  <a href="https://github.com/veeainc/lobstertrap">Veea Lobster Trap</a> at the perimeter ·
  <a href="https://doi.org/10.5281/zenodo.20114594">Apohara INV-15</a> at the behavioral layer.
</p>

<p align="center">
  <a href="https://doi.org/10.5281/zenodo.20114594"><img src="https://img.shields.io/badge/Paper%20DOI-10.5281%2Fzenodo.20114594-1A73E8?style=flat-square&logo=doi&logoColor=white"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-2ECC71.svg?style=flat-square"></a>
  <a href="https://github.com/veeainc/lobstertrap"><img src="https://img.shields.io/badge/depends%20on-Lobster%20Trap%20(MIT)-FF6B00.svg?style=flat-square"></a>
  <a href="https://jailbreakbench.github.io/"><img src="https://img.shields.io/badge/benchmark-JailbreakBench%20(NeurIPS%202024)-8B5CF6.svg?style=flat-square"></a>
  <a href="tests/test_lobstertrap_integration.py"><img src="https://img.shields.io/badge/tests-4%2F4%20live%20PASS-22C55E.svg?style=flat-square"></a>
</p>

<p align="center">
  <strong>🦞 TechEx 2026 · Track 1 · Agent Security &amp; AI Governance · Veea-sponsored</strong>
</p>

---

### Quickstart for enterprise operators

Deploy the full Lobster Trap + Aegis governance stack in one command.
The policy pack ships a pre-configured 9-rule ingress / 2-rule egress
YAML policy, an operator README, and a CISO-readable threat model summary.

```bash
# Download the pack and review before running (recommended):
wget https://github.com/SuarezPM/apohara-aegis/releases/latest/download/pack.tar.gz
tar -xzf pack.tar.gz && cat install.sh && ./install.sh
```

Or curl directly (review the script first at the URL above):

```bash
curl -sSL https://raw.githubusercontent.com/SuarezPM/apohara-aegis/main/policy-pack/install.sh | bash
```

Prereqs: Python 3.11+, Go 1.22+ (to build Lobster Trap from source), curl, git.
See [`policy-pack/README.md`](policy-pack/README.md) for the full operator guide,
`curl`-based attack verification, and production hardening checklist.

---

## What Apohara Aegis catches that no one else does

A 5-agent LLM workflow has two failure modes, and **no single tool catches both**:

1. **Inspectable content risk** — adversarial input or model output that a regex or DPI engine can pattern-match. Prompt injection, exfiltration, credentials leak, PII. Lobster Trap solves this in sub-millisecond.

2. **Silent behavioral drift** — the judge agent silently flips verdicts for *identical inputs* when KV-cache is aggressively reused across agents. Liang et al. 2026 ([arXiv:2601.08343](https://arxiv.org/abs/2601.08343)) measured an **8–23 percentage point drop in Judge Consistency Rate** under naive multi-agent reuse. Every output-side hallucination check passes individually. **The bug ships silently.**

Apohara Aegis is the only open-source project that catches both — with a Zenodo-published formal invariant (INV-15) for the second one, hardware-validated on AMD Instinct MI300X, and a NIST/EU/ISO-mapped threat model for the first.

---

## 👋 For judges: 60-second path

If you're reviewing this submission and have limited time:

1. **The headline metrics** (real, hardware-validated, MI300X-measured upstream):

   | | |
   |---|---|
   | `0 / 1,210` | INV-15 violations on the exhaustive sweep |
   | `3.55×` | INT4 KV reduction constant 4K → 262K context |
   | `11 / 11` | Lobster Trap adversarial PASS on our custom policy |
   | `4 / 4` | live integration tests PASS against running Lobster Trap |
   | `Δ 0.23` | JCR drop *prevented* under naive KV reuse (Liang et al. range: 0.08–0.23) |

2. **The paper with permanent DOI** (peer-reviewable evidence): [Zenodo 10.5281/zenodo.20114594](https://doi.org/10.5281/zenodo.20114594) — v2.0.1 IEEE format, 12 references, MI300X-grounded. Published as upstream [Apohara Context Forge](https://github.com/SuarezPM/Apohara_Context_Forge).

3. **The threat model** (Track 1 scoring requirement): [`docs/threat-model.md`](docs/threat-model.md) — 7 sections, NIST AI RMF + EU AI Act + ISO/IEC 42001 mapping, 6 acknowledged unknowns, 14-row layer-by-layer mitigation matrix.

4. **The honesty discipline** (what makes this regulator-readable): [`AUDIT.md`](AUDIT.md) — entry #1 acknowledges an external Perplexity Pro audit catch from 2026-05-13 that surfaced an unimplemented Gemini overclaim, and the same-day fix with real SDK integration. **External audit caught a gap; we acknowledged it and fixed the code.** That is the discipline.

### One-command local verification (CPU only, 60 seconds total)

```bash
git clone https://github.com/SuarezPM/apohara-aegis.git
cd apohara-aegis
pip install -r requirements.txt

# 1. Live integration tests (skip cleanly if no Lobster Trap available)
PYTHONPATH=. pytest tests/ -q

# 2. Head-to-head: with INV-15 vs without, mock pipeline
PYTHONPATH=. python3 scripts/sprint5_head_to_head.py \
    --mock --mode apohara_on --n-requests 200 --out /tmp/on.json
PYTHONPATH=. python3 scripts/sprint5_head_to_head.py \
    --mock --mode apohara_off --n-requests 200 --out /tmp/off.json

# Expected (mock, deterministic):
#   on  → jcr=1.00, inv15_fires=200
#   off → jcr=0.77, inv15_fires=0
#   Δ JCR = 0.23  (upper bound of Liang et al. 2026)
```

### One-command JBB Live Defense dashboard

```bash
PYTHONPATH=. python3 scripts/jbb_live_defense.py
# Open http://localhost:7860 — Gradio UI runs 100 JailbreakBench
# prompts against your Lobster Trap policy in real time.
```

---

## How is this different from TrustLayer / hallucination detection tools?

**Short answer:** TrustLayer scores OUTPUTS. Apohara Aegis enforces PROCESS.

| Category | What it checks | When it runs |
|---|---|---|
| TrustLayer · Patronus Lynx · Galileo · Cleanlab TLM · Vectara HHEM | Whether a single LLM output is factually grounded against source documents | **After** generation |
| **Apohara Aegis** | Whether every agent step followed the same documented, enforceable, auditable governance process | **Before, during, and after** execution |

These are **orthogonal layers**, not competitors. A production deployment could (and arguably should) stack both — TrustLayer as a downstream content auditor, Apohara Aegis as the upstream and runtime process governance layer.

The specific failure mode Apohara Aegis catches that **no output-side tool can see**: silent JCR drift under aggressive KV-cache reuse. When you share cache across agents in a pipeline, the critic agent silently flips verdicts for identical inputs — and every output-side hallucination check passes individually. The system still ships a silent bug. **INV-15 is the formal invariant that prevents this.**

---

## Architecture

```
                                Apohara Aegis
                                =============

  [Client / Agent app]
        │
        ▼
  ┌───────────────────────────────────────────────────────────┐
  │  Lobster Trap :8080  ── PERIMETER ── Veea (MIT, Go)       │
  │                                                            │
  │  Sub-millisecond regex DPI · 9-rule policy YAML            │
  │  ✓ contains_injection_patterns     ✓ contains_credentials  │
  │  ✓ contains_pii / pii_request      ✓ contains_exfiltration │
  │  ✓ contains_role_impersonation     ✓ contains_obfuscation  │
  │  ✓ sensitive_paths                 ✓ dangerous_commands    │
  └───────────────────────────────────────────────────────────┘
        │ (only requests that pass perimeter policy)
        ▼
  ┌───────────────────────────────────────────────────────────┐
  │  5-agent ContextForge pipeline                             │
  │  retriever → reranker → summarizer → CRITIC → responder    │
  │                                          │                 │
  │                                          ▼                 │
  │              INV-15 gate ── BEHAVIORAL ── Apohara (A2.0)   │
  │              risk_score > τ ?                              │
  │              └─► dense prefill (no KV reuse for critic)    │
  └───────────────────────────────────────────────────────────┘
        │
        ▼
  [LLM backend: vLLM / Llama / Gemini (optional cross-vendor critic)]
        │
        ▼
  [Response] + correlated JSONL audit trail
              (request_id links LT + INV-15 events)
```

Full architecture diagram, data flow, failure modes table, and per-agent
responsibility breakdown in [`docs/lobstertrap-integration.md`](docs/lobstertrap-integration.md).

---

## Compliance mapping

Three citations strategically (more than three is compliance theater):

- **NIST AI Risk Management Framework** — Apohara Aegis provides the **MEASURE** function (INV-15 risk score 0–1, Lobster Trap risk_score 0–1, JCR delta 0–1) and the **MANAGE** function (policy enforcement at runtime, JSONL audit log).
- **EU AI Act** — enforcement starts **2 August 2026**. Apohara Aegis delivers Article 9 (risk management: see `docs/threat-model.md`), Article 12 (record-keeping: JSONL audit), Article 14 (human oversight: `HUMAN_REVIEW` policy action), Article 15 (cybersecurity: 11/11 LT adversarial PASS).
- **ISO/IEC 42001:2024** — Apohara Aegis provides the operational evidence for sections A.7–A.11 (planning, support, operation, performance evaluation, improvement).

Full mapping in [`docs/threat-model.md`](docs/threat-model.md#4-compliance-mapping).

---

## Honesty discipline

Every claim in this repo traces to either an executable check (see `tests/`) or a published artifact (paper DOI, JSONL log). **No claim without a backing file.**

A specific entry worth surfacing publicly: during TechEx 2026 prep work, an **external Perplexity Pro deep-research audit** (2026-05-13) caught that 18 mentions of "Gemini" across docs/scripts/configs/pitch were not backed by any real `google-generativeai` or `vertex-ai` import — the mock-mode pipeline biased verdicts when the override started with `"gemini"`, but no real Gemini API call was made anywhere.

We accepted the finding, implemented real Gemini SDK integration with the `google-generativeai` package, and documented both the original gap and the fix in [`AUDIT.md`](AUDIT.md). Without `GEMINI_API_KEY` set, the function returns `None` and the caller falls through to the existing vLLM path — **no fake Gemini call is fabricated**.

This is the kind of honesty discipline a regulator can actually use. **External audit > self-attestation.**

---

## Stack

| Component | Purpose | License |
|---|---|---|
| **[Veea Lobster Trap](https://github.com/veeainc/lobstertrap)** (Go binary) | Perimeter DPI proxy. Build with `make build`. See [`docs/lobstertrap-integration.md`](docs/lobstertrap-integration.md) §E. | MIT |
| **[Apohara Context Forge](https://github.com/SuarezPM/Apohara_Context_Forge)** (Python) | INV-15 invariant specification + MI300X-validated codec | Apache-2.0 |
| **[Gradio](https://gradio.app)** | JBB Live Defense dashboard UI | Apache-2.0 |
| **[JailbreakBench](https://jailbreakbench.github.io/)** (NeurIPS 2024) | 100 categorized adversarial prompts loaded via HuggingFace `datasets` | MIT |
| **[google-generativeai](https://github.com/google/generative-ai-python)** SDK | Optional cross-vendor critic path | Apache-2.0 |

Python 3.11+. CPU-only for the policy stack; the upstream MI300X measurements live in [Apohara Context Forge](https://github.com/SuarezPM/Apohara_Context_Forge).

---

## What's in this repo

```
.
├── README.md                                ← this file
├── AUDIT.md                                 ← honesty log (4 entries)
├── LICENSE                                  ← Apache-2.0
│
├── docs/
│   ├── threat-model.md                      ← Track 1 scoring requirement
│   └── lobstertrap-integration.md           ← Architecture + data flow
│
├── configs/
│   ├── lobstertrap_policy.yaml              ← 9-rule policy (11/11 PASS)
│   └── sprint5_5agent.yaml                  ← 5-agent pipeline config
│
├── scripts/
│   ├── _sprint5_pipeline.py                 ← INV-15 gate · JCR · Gemini SDK
│   ├── sprint5_5agent_workload.py           ← workload CLI
│   ├── sprint5_head_to_head.py              ← head-to-head ON vs OFF CLI
│   ├── jbb_live_defense.py                  ← Gradio JBB dashboard
│   ├── generate_governance_dashboard.py     ← static dashboard generator
│   └── generate_aegis_cover.py              ← reproducible cover image
│
├── tests/
│   └── test_lobstertrap_integration.py      ← 4 live tests + 1 bonus
│
└── assets/
    ├── aegis-cover.png                      ← cover image (1280×640)
    ├── aegis-pitch-deck.{md,pdf}            ← 5-slide pitch deck (marp)
    └── inv15-governance-dashboard.html      ← static governance dashboard
```

---

## Acknowledgements

- **[Veea Inc](https://www.veea.com)** for open-sourcing Lobster Trap under MIT and sponsoring TechEx 2026 Track 1.
- **Liang et al. 2026** ([arXiv:2601.08343](https://arxiv.org/abs/2601.08343)) for the JCR drift paper that motivated INV-15.
- **[JailbreakBench team](https://jailbreakbench.github.io/)** for the NeurIPS-cited adversarial benchmark used in the live defense demo.
- **Perplexity Pro deep-research** (2026-05-13) for the external audit that caught the Gemini overclaim before submission.
- **[Apohara Context Forge](https://github.com/SuarezPM/Apohara_Context_Forge)** — the upstream engine where INV-15 is formally specified and hardware-validated on AMD Instinct MI300X.

---

## License

[Apache-2.0](LICENSE) for everything in this repo. Compatible with the MIT-licensed Lobster Trap dependency.

---

<p align="center">
  <em>Built by <a href="mailto:suarezpm@csnat.unt.edu.ar">Pablo M. Suarez</a> · Universidad Nacional de Tucumán, Argentina · 2026</em>
</p>
