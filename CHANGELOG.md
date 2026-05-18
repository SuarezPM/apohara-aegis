# Changelog

All notable changes to **apohara-aegis** are documented here. Format
loosely follows [Keep a Changelog](https://keepachangelog.com/). Older
day-by-day measurements live in [`AUDIT.md`](AUDIT.md) and the
[`README.md`](README.md) milestone sections.

## [Unreleased]

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
