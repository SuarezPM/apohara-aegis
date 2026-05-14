<p align="center">
  <img src="assets/aegis-cover.png" alt="apohara-aegis" width="720">
</p>

<h1 align="center">apohara-aegis</h1>

<p align="center">
  <strong>Governed context in. Inspected prompts out. Agents enterprises actually trust.</strong>
</p>

<p align="center">
  The defense-in-depth trust layer for multi-agent LLM workflows.
  <br>
  <em><a href="https://github.com/veeainc/lobstertrap">Veea Lobster Trap</a> (perimeter)
  + <a href="https://doi.org/10.5281/zenodo.20114594">Apohara INV-15</a> (behavioral).</em>
</p>

<!-- Row 1 — academic + license -->
<p align="center">
  <a href="https://doi.org/10.5281/zenodo.20114594"><img src="https://img.shields.io/badge/Paper%20DOI-10.5281%2Fzenodo.20114594-1A73E8?style=flat-square&logo=doi&logoColor=white"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-2ECC71.svg?style=flat-square"></a>
  <a href="https://github.com/veeainc/lobstertrap"><img src="https://img.shields.io/badge/depends%20on-Lobster%20Trap%20(MIT)-FF6B00.svg?style=flat-square"></a>
  <a href="https://jailbreakbench.github.io/"><img src="https://img.shields.io/badge/benchmark-JailbreakBench%20(NeurIPS%202024)-8B5CF6.svg?style=flat-square"></a>
</p>

<!-- Row 2 — TechEx submission -->
<p align="center">
  <strong>🦞 TechEx 2026 · Track 1 · Agent Security &amp; AI Governance · Veea-sponsored</strong><br>
  <a href="docs/threat-model.md">Threat model</a> ·
  <a href="docs/lobstertrap-integration.md">Integration design</a> ·
  <a href="configs/lobstertrap_policy.yaml">Policy YAML (9 rules)</a> ·
  <a href="assets/inv15-governance-dashboard.html">Governance dashboard</a> ·
  <a href="tests/test_lobstertrap_integration.py">Live tests (4/4 PASS)</a>
</p>

---

## 👋 For judges: 60-second path

If you are reviewing this submission and have limited time:

1. **The headline metrics** (real, hardware-validated, MI300X-measured upstream):
   `0 / 1,210` INV-15 violations on the exhaustive sweep · `3.55×` INT4 KV reduction constant 4K-262K context · `11 / 11` Lobster Trap adversarial PASS on our custom policy.
2. **The paper with permanent DOI** (peer-reviewable evidence): [Zenodo 10.5281/zenodo.20114594](https://doi.org/10.5281/zenodo.20114594), v2.0.1 IEEE format, 12 references, MI300X-grounded — published as upstream **Apohara Context Forge**.
3. **The integration we built for this hackathon**: [`docs/lobstertrap-integration.md`](docs/lobstertrap-integration.md) + [`configs/lobstertrap_policy.yaml`](configs/lobstertrap_policy.yaml) (9 rules, NeurIPS-aligned).
4. **The threat model** (Track 1 scoring requirement): [`docs/threat-model.md`](docs/threat-model.md) — 7 sections, NIST AI RMF + EU AI Act + ISO/IEC 42001 mapping, 6 acknowledged unknowns.
5. **The honesty discipline** (what makes this regulator-readable): see §**Honesty** below — entry #11 acknowledges an external Perplexity Pro audit catch from 2026-05-13.

**One-command local verification (CPU-only, no GPU required):**

```bash
git clone https://github.com/SuarezPM/apohara-aegis.git
cd apohara-aegis
pip install -r requirements.txt
PYTHONPATH=. pytest tests/ -q                                    # ~3 seconds
PYTHONPATH=. python3 scripts/sprint5_head_to_head.py \           # ~1 second
    --mock --mode apohara_on --n-requests 200 --out /tmp/h2h.json
# Expected: jcr=1.0, inv15_fires_total=200
```

**One-command JBB live defense dashboard:**

```bash
PYTHONPATH=. python3 scripts/jbb_live_defense.py    # http://localhost:7860
```

---

## What this is

**apohara-aegis** is a **policy stack**, not a model. It wraps two open-source components:

| Layer | Component | License | Owns which threats |
| ----- | --------- | ------- | ------------------ |
| **Perimeter** | [Veea Lobster Trap](https://github.com/veeainc/lobstertrap) — sub-millisecond regex DPI proxy | MIT | Prompt injection · credential exposure · PII leakage · exfiltration · role impersonation · sensitive paths · dangerous shell commands |
| **Behavioral** | [Apohara Context Forge INV-15](https://github.com/SuarezPM/Apohara_Context_Forge) — formal invariant for judge-agent KV-cache reuse | Apache-2.0 | Silent Judge Consistency Rate (JCR) drift under aggressive KV-cache reuse — *the failure mode no output-side hallucination check can see* |

The two layers solve **orthogonal** failure modes. Either one alone is insufficient. Together they are auditable end-to-end with a correlated `request_id` across the JSONL audit trails.

This repository is the **applied policy pack** (the YAML rules, the Gradio dashboards, the integration tests, the threat model). The underlying INV-15 invariant + the MI300X measurements are published as **upstream [Apohara Context Forge](https://github.com/SuarezPM/Apohara_Context_Forge)** with Zenodo DOI 10.5281/zenodo.20114594.

---

## 🆚 How is this different from TrustLayer / hallucination-detection tools?

**Short answer:** TrustLayer scores OUTPUTS. apohara-aegis enforces PROCESS.

| Category | What it checks | When it runs |
| -------- | -------------- | ------------ |
| TrustLayer · Patronus Lynx · Galileo · Cleanlab TLM · Vectara HHEM | Whether a single LLM output is factually grounded against source documents (hallucination scoring) | After generation |
| **apohara-aegis** | Whether every agent step in a multi-agent workflow followed the same documented, enforceable, auditable governance process | Before, during, and after execution |

These are **orthogonal layers**, not competitors. A production deployment could (and arguably should) run both — TrustLayer as a downstream content auditor, apohara-aegis as the upstream and runtime process governance layer that makes the entire workflow regulator-readable.

The specific failure mode apohara-aegis catches that **none of the output-side tools see**: silent Judge Consistency Rate (JCR) drift under aggressive KV-cache reuse (Liang et al. 2026, [arXiv:2601.08343](https://arxiv.org/abs/2601.08343)). When you reuse cache across agents in a pipeline, the critic agent silently flips verdicts for identical inputs — and every output-side hallucination check passes individually. The system still ships a silent bug. INV-15 is the formal invariant that prevents this.

---

## Architecture

```
[Client / Agent App]
        │
        ▼
[Lobster Trap :8080]  ← perimeter DPI · regex policy · sub-millisecond
        │                 contains_injection_patterns · contains_credentials
        │                 contains_pii · contains_exfiltration · risk_score
        │
        ▼ (only requests that passed perimeter policy)
[5-agent ContextForge pipeline]
   retriever → reranker → summarizer → CRITIC → responder
                                           │
                                           ▼
                          [INV-15 gate] · formal invariant
                          risk_score > τ ?
                          └─► dense prefill (no KV reuse)
        │
        ▼
[LLM backend: vLLM / Llama / Gemini (optional cross-vendor critic)]
        │
        ▼
[Response] + correlated JSONL audit trail
```

See [`docs/lobstertrap-integration.md`](docs/lobstertrap-integration.md) for the full architecture diagram, data flow, layer-by-layer responsibility table, and the failure-modes section.

---

## Compliance mapping

Every claim in this repo maps to a 2026 governance framework. Three citations strategically (more than three is compliance theater).

- **NIST AI RMF** — apohara-aegis provides the **MEASURE** function (INV-15 risk score 0-1, Lobster Trap risk_score 0-1, JCR delta 0-1) and the **MANAGE** function (policy enforcement at runtime, JSONL audit log).
- **EU AI Act** — enforcement starts 2 August 2026. apohara-aegis delivers Article 9 (risk management: see `docs/threat-model.md`), Article 12 (record-keeping: JSONL), Article 14 (human oversight: `HUMAN_REVIEW` policy action), Article 15 (cybersecurity: 11/11 LT adversarial PASS).
- **ISO/IEC 42001:2024** — apohara-aegis provides the operational evidence for sections A.7-A.11 (planning, support, operation, performance evaluation, improvement).

Full mapping in [`docs/threat-model.md`](docs/threat-model.md#4-compliance-mapping).

---

## Honesty

Every claim in this repo traces to either an executable check (see `tests/`) or a published artifact (paper DOI, AUDIT.md, JSONL log). No claim without a backing file.

A specific entry worth surfacing: during the TechEx 2026 prep work, an **external Perplexity Pro deep-research audit** (2026-05-13) caught that 18 mentions of "Gemini" across docs/scripts/configs/pitch were not backed by any real `google-generativeai` or `vertex-ai` import — the mock-mode pipeline biased verdicts when the override started with `"gemini"`, but no real Gemini API call was made anywhere.

We accepted the finding, implemented real Gemini SDK integration with the `google-generativeai` package, and documented both the original gap and the fix in [`AUDIT.md`](AUDIT.md). Without `GEMINI_API_KEY` env var, the function returns `None` and the caller falls through to the existing vLLM path — **no fake Gemini call is fabricated**.

This is the kind of honesty discipline a regulator can actually use. **External audit > self-attestation.**

---

## Stack

- **Python 3.11+** (CPU-only for the policy stack; the upstream MI300X-validated measurements live in the [Apohara Context Forge](https://github.com/SuarezPM/Apohara_Context_Forge) repository).
- **Lobster Trap** (Go binary, MIT) — build from [veeainc/lobstertrap](https://github.com/veeainc/lobstertrap) with `make build`. See `docs/lobstertrap-integration.md` §E for the setup checklist.
- **Gradio** for the JBB Live Defense dashboard.
- **JailbreakBench JBB-Behaviors** (NeurIPS 2024 Datasets and Benchmarks Track, MIT) — 100 categorized adversarial prompts loaded via the HuggingFace `datasets` library.
- **google-generativeai** SDK for the optional cross-vendor critic path.

---

## Acknowledgements

- **Veea Inc** for open-sourcing Lobster Trap under MIT and sponsoring TechEx 2026 Track 1.
- **Liang et al. 2026** ([arXiv:2601.08343](https://arxiv.org/abs/2601.08343)) for the JCR drift paper that motivated INV-15.
- **JailbreakBench team** ([jailbreakbench.github.io](https://jailbreakbench.github.io/)) for the NeurIPS-cited adversarial benchmark used in the live defense demo.
- **Perplexity Pro deep-research** (2026-05-13) for the external audit that caught the Gemini overclaim before submission.
- **Apohara Context Forge** ([SuarezPM/Apohara_Context_Forge](https://github.com/SuarezPM/Apohara_Context_Forge)) — the upstream engine where INV-15 is formally specified and hardware-validated on AMD Instinct MI300X.

---

## License

[Apache-2.0](LICENSE). Compatible with the MIT-licensed Lobster Trap dependency.

---

<p align="center">
  <em>Built by <a href="mailto:suarezpm@csnat.unt.edu.ar">Pablo M. Suarez</a> at the Universidad Nacional de Tucumán, Argentina.</em>
</p>
