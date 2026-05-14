# Apohara Aegis — Honesty Log

> **Status:** living document, maintained alongside the codebase.
> **Discipline:** every claim in the README, docs, slides, and submission text traces to either an executable check or a published artifact. No claim without a backing file. When external audits catch a gap, we acknowledge the gap openly (here) and fix the code.

This is the policy-stack repo. The upstream engine ([Apohara Context Forge](https://github.com/SuarezPM/Apohara_Context_Forge)) maintains its own AUDIT.md covering the INV-15 invariant, MI300X measurements, and codec research (10 entries closed across V6.0 → V7.0.0-rc.2). This document covers only the items that live in **this** repository (the applied policy stack + LT integration).

---

## The four states

| State | Meaning |
|-------|---------|
| 🟢 PRODUCTION | Real implementation. Computes its claimed value from real inputs. Tests cover real behavior. |
| 🟡 HONEST STUB | Clearly marked as stub / fallback in docstring or runtime warning. Returns plausible defaults without claiming they are measured. |
| 🟠 PARTIAL | Real algorithm but with synthetic inputs or hardcoded constants where the claim implies measurement. |
| 🔴 OPTIMISTIC | The README / paper / benchmark implies "live" or "measured" but the code is actually mocked / hardcoded. |

---

## 1. 🟡→🟢 Gemini critic agent: was mock-only label, now real SDK integration

**Where it lived**: `scripts/_sprint5_pipeline.py`, `scripts/sprint5_5agent_workload.py`,
`scripts/sprint5_head_to_head.py`, `configs/sprint5_5agent.yaml`,
`docs/lobstertrap-integration.md`, `assets/aegis-pitch-deck.md`.

**The state on 2026-05-13 (caught by Perplexity Pro deep-research audit)**:
the `--critic-provider gemini-3-pro` CLI flag and YAML override existed in 6 files, and the mock-mode pipeline biased verdicts slightly when the override started with `"gemini"`. **But there was no real call to the Gemini API in any code path.** The slide deck claimed "Cross-vendor critic (Gemini)" as a delivered feature.

**Why this was a violation**: the slide deck and integration doc implied Gemini was actually called, when in reality only the mock returned a slightly biased verdict. That gap is exactly what the honesty discipline exists to catch.

**Fix in this repo (2026-05-13)**: added a real `call_gemini()` function in `scripts/_sprint5_pipeline.py` that uses the `google-generativeai` SDK with the `GEMINI_API_KEY` env var.

- When `--critic-provider` starts with `gemini-` AND the env var is set, the critic step is routed to Google's actual Gemini API for that single agent call. The other 4 agents continue using vLLM.
- When the env var is missing or the import fails, the function returns `None` and the caller falls through to the existing vLLM path. **No fake call is ever fabricated.**
- Lobster Trap proxy does NOT see the Gemini request (the SDK bypasses LT). For full LT coverage with Gemini, deploy Gemini behind a proxy in your own setup — documented in source comment.

**Honesty rating**: 🟢 PRODUCTION. The cross-vendor critic claim now maps to real Gemini API calls when configured; otherwise the feature degrades silently to a documented fallback.

**Discovery credit**: external Perplexity Pro deep-research audit caught this gap during TechEx 2026 hackathon prep. External audit > self-attestation.

---

## 2. 🟢 JBB Live Defense — honest mode labeling

**Where it lives**: `scripts/jbb_live_defense.py`.

The Gradio dashboard runs JailbreakBench JBB-Behaviors prompts against the Lobster Trap policy. Two modes:

- **LIVE** — `LOBSTERTRAP_ENDPOINT` env var is set + LT is reachable → real proxy hits, real block decisions.
- **SIMULATED** — env var unset or LT unreachable → deterministic mock block decisions with a banner clearly flagging the mode.

**Honesty contract**: the mode label is shown in the UI banner AND recorded in the exported JSON report's `mode` field. Simulated mode does NOT pretend to be live. The exported `mode: "simulated"` in `logs/jbb_defense_report_*.json` is auditable.

**Rating**: 🟢 PRODUCTION.

---

## 3. 🟢 Governance dashboard — demo data clearly flagged

**Where it lives**: `scripts/generate_governance_dashboard.py` + `assets/inv15-governance-dashboard.html`.

When run without `--audit-log` / `--inv15-log` args (or when those paths don't exist), the generator falls back to synthesized demo data and adds a yellow banner to the rendered HTML page: *"This dashboard is rendered from synthesized demo data for illustration."*

**Honesty contract**: a viewer can never look at the dashboard and mistake demo data for production data. The banner is at the top of the rendered HTML, the script comment says so, the source comment in `synthesize_demo_events()` says so.

**Rating**: 🟢 PRODUCTION.

---

## 4. 🟢 Upstream provenance — clear separation of contributions

This repo (**Apohara Aegis**) is the **applied policy stack** that wraps two open-source components:
- The [Veea Lobster Trap](https://github.com/veeainc/lobstertrap) proxy (MIT, independently authored by Veea Inc).
- The [Apohara Context Forge](https://github.com/SuarezPM/Apohara_Context_Forge) INV-15 invariant + MI300X-validated codec (Apache-2.0, authored by the same maintainer of this repo).

**What is original to this repo**: the policy YAML (`configs/lobstertrap_policy.yaml`), the integration design (`docs/lobstertrap-integration.md`), the threat model (`docs/threat-model.md`), the live integration tests (`tests/test_lobstertrap_integration.py`), the Gradio JBB defense dashboard (`scripts/jbb_live_defense.py`), the static governance dashboard generator (`scripts/generate_governance_dashboard.py`), the cover/pitch-deck assets, and the rebranded README + this AUDIT.md.

**What is NOT original to this repo**: the Lobster Trap binary, the INV-15 invariant specification, the MI300X measurement data, the paper PDF, the codec implementation. Those live upstream and are properly credited in the README §Acknowledgements section.

**Rating**: 🟢 PRODUCTION. Provenance is explicit; nothing is claimed as original that isn't.

---

## Maintenance discipline (going forward)

1. **No new mechanism enters the README without an entry in this file** declaring its state (🟢/🟡/🟠/🔴).
2. **No benchmark number quoted publicly without** (a) a JSON log committed to `logs/` or an upstream-referenced log, AND (b) the matching script that produced it being runnable from this repo.
3. **Every external paper or framework cited** must have either (a) faithful implementation with a passing test, OR (b) a "follows X, with delta Y" disclaimer stating exactly what is different.
4. **External audits catch real gaps** (see entry #1). Acknowledge them in this file with the discovery source and the fix.

---

*Last updated: 2026-05-13. Maintained by Pablo M. Suarez. External audit contributions credited per entry.*
