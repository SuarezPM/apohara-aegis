# Changelog

All notable changes to **apohara-aegis** are documented here. Format
loosely follows [Keep a Changelog](https://keepachangelog.com/). Older
day-by-day measurements live in [`AUDIT.md`](AUDIT.md) and the
[`README.md`](README.md) milestone sections.

## [Unreleased]

### Added — Fusion Sprint Tier-2: SDK middleware packages (2026-05-18, US-91)

- **Two new SDK middleware packages** — `apohara-langchain` (LangChain callback) and `apohara-crewai` (tool decorator) — intercept agent prompts via POST `/v1/soar/judge/evaluate` and BLOCK on DJL/LLM ensemble veto. Both packages live under `integrations/`. `apohara-langchain` installs on Python 3.10–3.14; `apohara-crewai` requires Python 3.10–3.13 (crewai>=0.30 constraint). Fail-open by default; REVIEW escalation configurable via `block_on_review=True`.

### Added — Fusion Sprint Tier-2: STIX 2.1 export (2026-05-18, US-90)

- **STIX export endpoint** — `GET /v1/soar/incidents/{incident_id}/stix` returns a STIX 2.1 bundle (6 SDOs: identity, indicator, sighting, observed-data, course-of-action, note) for any incident in the HMAC verdict vault ledger; HMAC `signed_hash` preserved in indicator `external_references` for chain-of-custody. Backed by `stix2>=3.0`; 5 standalone tests in `apohara-aegis/tests/test_stix_export.py`.

### Added — Fusion Sprint Tier-1: PLAYBOOK SOAR features (2026-05-18, US-71 → US-80)

Ten new inline modules under `apohara_aegis/` (no `v2/` subdir per
single-product naming directive — see Apohara PROBANT
[`AUDIT.md` §12](https://github.com/SuarezPM/apohara-probant/blob/main/AUDIT.md)):

- **`djl.py`** — Zero-LLM Deterministic Judge Layer (US-72). 62 regex
  rules across 6 categories (PI 20 / SQLI 6 / XSS 6 / PII 10 / EXF 5 /
  MIS 10 / POL 5). `DjlRule` frozen dataclass with id / pattern /
  category / severity / description / references. `evaluate(prompt,
  context) -> DjlVerdict`. Bench: p99 **0.114 ms** (44× under the
  5 ms budget), TPR/TNR **1.000**, Wilson 95% accuracy CI
  **[0.9962, 1.0000]** on 124-prompt corpus × 1000 iterations
  (`logs/djl_latency.json`). 130 parametrized tests.
- **`soar_pipeline.py`** — 4-stage SOAR pipeline (US-73).
  DETECT → JUDGE → ENFORCE → FORENSICS as async stages with inline
  `_HMACChain` byte-compatible with `verdict_vault.VerdictVault`.
  Lifecycle p99 **10.6 ms** (19× under 200 ms target,
  `logs/lifecycle_latency.json`). 17 e2e tests + benchmark.
- **`taxonomy.py`** — 16 incident codes (US-74) grouped as 3 PI + 3 EXF
  + 3 MIS + 2 FIN + 2 PII + 3 GOV. `IncidentCode` StrEnum +
  `IncidentDefinition` frozen dataclass + `DEFINITIONS` dict. 16 tests.
- **`templates.py`** — 6 industry templates (US-75): Finance /
  Healthcare / Government / Retail / Manufacturing / Energy. Each
  template binds regulatory refs, default DJL rule subset, mandatory
  incident codes, and a forensics policy.
- **`nist_mapping.py`** — 35 NIST controls (US-75): 19 base NIST AI
  RMF 1.0 subcategories + 16 CSA Agentic Profile extensions
  (March 2026 draft). Each control carries `id`, `title`,
  `category`, `tier`, `apohara_evidence_path` for cross-reference.
- **`compliance.py`** — 5-framework suite (US-76): EU AI Act (5
  controls), NIST AI RMF (10), NIST SP 800-53 (12), SOC 2 (6),
  ISO 27001 (6), OWASP LLM 2026 (10) = 49 total controls.
  `generate(incident_code, framework_names)` returns a per-incident
  report. 22 tests.
- **`verdict_combine.py`** — Dual-layer DJL + LLM ensemble combine
  (US-77). `LlmEnsembleVerdict` + `CombinedVerdict` frozen
  dataclasses. `async combine(...)` runs both layers in parallel via
  `asyncio.gather`. Safe-merge: `BLOCK ∨ BLOCK = BLOCK`,
  `ALLOW ∧ ALLOW = ALLOW`, else `REVIEW`. Both layers retain
  independent veto power. 25 tests covering the 3×3 verdict matrix +
  parallelism asserts.
- **`mythos_slot.py`** — `MythosAttackerAdapter` reserved slot
  (US-78). Subclasses `VendorAdapter` directly (NOT
  `FallbackVendorAdapter`, which is a routing wrapper). Overrides
  `_available()` to return `False` unless `APOHARA_MYTHOS_ENABLED=1`
  AND a credential env var is set
  (`ANTHROPIC_MYTHOS_API_KEY` | `AWS_BEDROCK_MYTHOS_CREDS`).
  Returns `_unavailable_verdict("not_configured")` without raising.
  Apohara has NOT been granted Mythos access — see
  [`MYTHOS_READY.md`](https://github.com/SuarezPM/apohara-probant/blob/main/MYTHOS_READY.md)
  for boundary text contract. 14 tests.
- **`health_profile.py`** — `AgentProfile` dataclass + Wilson CI
  (Newcombe 1998 Eq. 3, z=1.96) + `_compute_health_score()` =
  `100 − (incidents × 10) − (lie_rate × 30)` clipped to [0, 100].
- **`simulator.py`** — 3 demo agents (FxTraderAgent / DataAnalystAgent /
  SupportBotAgent) × 9 misbehavior scenarios + CLI
  `python -m apohara_aegis.simulator --agent X --scenario Y`. 93 tests.

### Changed

- `make_default_adapters()` now returns **14 seats**: Day-4's 10
  frontier + Phase-3 priority A's 3 OpenRouter additions + 1 reserved
  `MythosAttackerAdapter` at index 13. INACTIVE in production until
  Claude for Open Source / Glasswing approval.
- `_scale_thresholds_for_adapter_count(14)` → `{high: 14, med: 10,
  human_review: 4}`. `DEFAULT_VOTE_THRESHOLDS` (N=10 Day-4 ladder)
  unchanged for back-compat.
- `tests/test_ensemble.py::test_default_ensemble_is_14_seat_frontier`
  (renamed from `..._is_13_seat_frontier`) asserts the full
  14-seat composition: 13 `FallbackVendorAdapter` wrappers + 1
  `MythosAttackerAdapter` at index 13. Seat labels list grows from
  13 to 13 + Mythos identity check.
- `tests/test_mythos_slot.py::test_make_default_adapters_has_fourteen_seats`
  (renamed from `..._has_eleven_seats`) tracks the post-rebase
  14-seat contract.

### Verified — 500/500 fusion-test pass (1 skipped, pre-existing)

`tests/test_{djl_latency,djl_rules,soar_pipeline,soar_routes,verdict_combine,mythos_slot,ensemble,compliance,incident_taxonomy,industry_templates,nist_mapping,agent_health,simulator}.py`
all green. Honesty CI gate
([`scripts/check_honesty_fusion.sh`](https://github.com/SuarezPM/apohara-probant/blob/main/scripts/check_honesty_fusion.sh))
+ brand CI gate
([`scripts/check_brand_fusion.sh`](https://github.com/SuarezPM/apohara-probant/blob/main/scripts/check_brand_fusion.sh))
exit 0.

### Added — Phase 3 priority A: 12-vendor ensemble expansion (2026-05-18)

- Three new `OpenRouterAdapter` subclasses in
  `apohara_aegis/openrouter_adapters.py`:
  - `OpenRouterMistralLarge2411Adapter` — `mistralai/mistral-large-2411`,
    EU AI Act regulatory diversity (live OpenRouter catalogue).
  - `OpenRouterGrok2Adapter` — `x-ai/grok-2-1212`, non-OpenAI / non-
    Anthropic / non-Google frontier lineage. **KNOWN-LIMITATION**: not
    in OpenRouter catalogue 2026-05-18; ships per the design doc and
    fails open until the route returns.
  - `OpenRouterPerplexitySonarLargeAdapter` —
    `perplexity/llama-3.1-sonar-large-128k-online`, only web-grounded
    vendor in the ensemble. **KNOWN-LIMITATION**: same catalogue gap
    as Grok-2; fails open via the base-class contract.
- Three new `FallbackVendorAdapter` seats in
  `make_default_adapters()` (`mistral-large-seat`, `grok-2-seat`,
  `perplexity-sonar-seat`) — each without a fallback because no clean
  cross-provider sibling exists yet (same wrapper pattern as Big
  Pickle).
- 9 new test cases in `tests/test_openrouter_adapters.py`
  (`test_phase3_priority_a_adapter_smoke_instantiation`,
  `test_phase3_priority_a_adapter_parses_valid_json`,
  `test_phase3_priority_a_seat_in_default_adapters` — 3 parametrized
  cases each).

### Changed

- `make_default_adapters()` now returns **13 seats** (12 frontier + Big
  Pickle stealth alias); was 10. Headline rounds to "12 vendors". See
  the docstring for the full lineup.
- `_scale_thresholds_for_adapter_count(13)` resolves to
  `{high: 13, med: 9, human_review: 4}`; the helper handles the N>10
  branch via `ceil(2N/3)`. `DEFAULT_VOTE_THRESHOLDS` (the N=10 canonical
  Day-4 ladder) is unchanged for back-compat.
- `DEFAULT_COST_CAPS_USD` gained 3 new entries at $5 each, raising the
  cumulative paid envelope from $45 → $60 per ensemble lifetime.
- `tests/test_ensemble.py::test_default_ensemble_is_13_seat_frontier`
  (renamed from `..._is_10_vendor_frontier`) updated to assert the
  13-seat composition, expanded seat-label list, and rescaled
  thresholds.

### Recommended (consumer-side, not enforced here)

- Apohara-probant `VERDICT_REVIEW_THRESHOLD` / `VERDICT_BLOCK_THRESHOLD`
  should be rescaled from `3` / `6` (calibrated for 9 vendors) to
  `4` / `8` for the 12-frontier ensemble per §"Threshold rescaling" of
  the design doc. This is a separate change in the consumer repo.

### References

- Design doc:
  `apohara-inti/docs/research/12-vendor-ensemble-design.md`
- Tracking issue:
  [github.com/SuarezPM/apohara-aegis#1](https://github.com/SuarezPM/apohara-aegis/issues/1)
