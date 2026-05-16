#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""HarmBench dual-benchmark subset runner — Sprint US-003 (2026-05-16).

Runs the Day-5 10-frontier FallbackVendorAdapter ensemble against an
N=40 deterministic subset of the canonical HarmBench
``harmbench_behaviors_text_test.csv`` (Mazeika et al. 2024, NeurIPS
2024) and emits a single JSON report that the README BENCHMARKS table
cites alongside the JBB-Behaviors held-out 80 baseline
(93.75% +/- 2.7%).

Why a separate script?
======================

``scripts/run_baselines.py`` is the comparative harness for the 18
Day-3 / Day-4 / Day-5 single-defense vs ensemble bake-off. It already
ships a ``--dataset=harmbench`` path that pulls from the
``swiss-ai/harmbench`` Hugging Face mirror (320-row DirectRequest
test split, ungated).

This script is purposely smaller and dedicated to the dual-benchmark
README claim. Differences from ``run_baselines.py``:

1. **Canonical CSV source** — Pulls the official CSV directly from
   ``centerforaisafety/HarmBench`` on GitHub (the upstream
   provenance, no HF mirror chain). Matches the standing 2026 LLM
   safety literature citation path word-for-word.
2. **Per-attacker block rate** — Records each of the 10 ensemble
   adapter's individual block rate (is_harmful per prompt) so the
   downstream README and AUDIT can show per-vendor confidence.
3. **Hard cost cap** — Aborts gracefully if cumulative cost crosses
   USD 40.00, emitting a partial JSON with honesty annotation.
4. **Wilson 95% CI** — Computed in-line with z=1.96 (no statsmodels
   dependency). The README cites these bounds for both benchmarks
   in the same units.

Determinism
===========

* ``random.seed(42)`` BEFORE sampling — the 40 prompts chosen are a
  function of (file SHA, seed=42).
* The full CSV is downloaded once and cached at
  ``logs/.harmbench_text_test.csv`` (gitignored via prefix).
* The chosen 40 are written into the output JSON's records list so
  the result is independently auditable.

Usage
=====

::

    source ~/.config/environment.d/98-apohara-aegis-keys.conf
    PYTHONPATH=. python3 scripts/run_harmbench_subset.py \\
        --out logs/harmbench_subset40_<ts>.json
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import random
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


HARMBENCH_CSV_URL = (
    "https://raw.githubusercontent.com/centerforaisafety/HarmBench/"
    "main/data/behavior_datasets/harmbench_behaviors_text_test.csv"
)
HARMBENCH_CSV_CACHE = REPO_ROOT / "logs" / ".harmbench_text_test.csv"
SEED = 42
N_PROMPTS = 40
COST_CEILING_USD = 40.00
DATASET_TAG = "harmbench-text-test-subset40-seed42"


# ---------------------------------------------------------------------------
# Dataset loading — canonical centerforaisafety/HarmBench CSV
# ---------------------------------------------------------------------------


def _download_harmbench_csv() -> str:
    """Fetch the canonical text-test CSV from GitHub raw URL.

    Cached at ``logs/.harmbench_text_test.csv`` (dot-prefix keeps it
    out of the committed logs directory listing). Returns the CSV
    text.
    """
    HARMBENCH_CSV_CACHE.parent.mkdir(parents=True, exist_ok=True)
    if HARMBENCH_CSV_CACHE.exists():
        return HARMBENCH_CSV_CACHE.read_text(encoding="utf-8")
    print(
        f"[harmbench] downloading {HARMBENCH_CSV_URL} ...",
        flush=True,
    )
    with urllib.request.urlopen(HARMBENCH_CSV_URL, timeout=60) as resp:
        body = resp.read().decode("utf-8")
    HARMBENCH_CSV_CACHE.write_text(body, encoding="utf-8")
    print(
        f"[harmbench] cached {len(body)} bytes "
        f"to {HARMBENCH_CSV_CACHE}",
        flush=True,
    )
    return body


def load_harmbench_subset(n: int = N_PROMPTS, seed: int = SEED) -> list[dict]:
    """Sample N prompts deterministically from the official CSV.

    Path: download (or cache-read) the canonical
    ``harmbench_behaviors_text_test.csv``, parse with the stdlib
    ``csv.DictReader``, shuffle with ``random.Random(seed)``, and
    return the first ``n`` rows normalised to the
    ``{Goal, Category, Source, BehaviorID}`` shape.

    Note: the upstream CSV ships 320 behaviors (sum of standard /
    contextual / copyright FunctionalCategories). The PRD references
    "400 behaviors total" — that includes the val split too. We pull
    the test split which is the standing benchmark surface in the
    2024 NeurIPS paper.
    """
    body = _download_harmbench_csv()
    rows = list(csv.DictReader(io.StringIO(body)))
    rng = random.Random(seed)
    rng.shuffle(rows)
    chosen = rows[:n]
    out: list[dict] = []
    for r in chosen:
        out.append({
            "Goal": r["Behavior"],
            "Category": (
                r.get("SemanticCategory")
                or r.get("FunctionalCategory")
                or "harmful"
            ),
            "Source": (
                "HarmBench text-test "
                "(Mazeika et al. 2024, NeurIPS)"
            ),
            "BehaviorID": r.get("BehaviorID", ""),
            "FunctionalCategory": r.get("FunctionalCategory", ""),
        })
    return out


# ---------------------------------------------------------------------------
# Statistics — Wilson 95% CI half-width
# ---------------------------------------------------------------------------


def wilson_ci(blocked: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Return (lower, upper) Wilson 95% CI for a binomial proportion.

    Standard reference: Newcombe (1998); see also Brown / Cai / DasGupta
    (2001). For small n (40), Wilson gives tighter and more honest
    bounds than the normal approximation, especially near 0 / 1.
    """
    if n <= 0:
        return (0.0, 0.0)
    p = blocked / n
    denom = 1.0 + (z**2) / n
    centre = (p + (z**2) / (2 * n)) / denom
    margin = (z * math.sqrt((p * (1 - p) / n) + (z**2 / (4 * n**2)))) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run(out_path: Path) -> int:
    from apohara_aegis.defense_chain import make_default_chain  # noqa: PLC0415
    from apohara_aegis.multi_judge import make_default_ensemble  # noqa: PLC0415

    prompts = load_harmbench_subset(n=N_PROMPTS, seed=SEED)
    n = len(prompts)
    print(
        f"[harmbench] loaded {n} prompts, seed={SEED}, source=text-test",
        flush=True,
    )

    ensemble = make_default_ensemble(fast_path=False)
    chain = make_default_chain(
        judge=ensemble, lt_call_fn=None, judge_threshold=0.5,
    )

    # Per-attacker (i.e. per-adapter / per-vendor:model) block tally.
    # We discover the canonical seat keys at construction time from
    # each adapter's primary route. EnsembleVerdict.per_vendor uses
    # "<vendor_prefix>:<model_id>" — when a FallbackVendorAdapter routes
    # to a backup, the vendor prefix changes (e.g. ai_studio -> openrouter)
    # so additional keys appear; we tally those too on first sight.
    canonical_keys: list[str] = []
    for ad in ensemble.adapters:
        # FallbackVendorAdapter exposes the seat's primary route via
        # ._primary; raw VendorAdapter instances are themselves the
        # primary route.
        primary = getattr(ad, "_primary", ad)
        vendor_prefix = str(getattr(primary, "vendor", primary.name))
        model_id = str(primary.model)
        canonical_keys.append(f"{vendor_prefix}:{model_id}")
    per_attacker_blocks: dict[str, int] = {k: 0 for k in canonical_keys}
    per_attacker_active: dict[str, int] = {k: 0 for k in canonical_keys}

    # Per-category breakdown — counts the number of records per
    # SemanticCategory (or FunctionalCategory fallback).
    per_category_total: dict[str, int] = {}
    per_category_blocks: dict[str, int] = {}

    latencies: list[float] = []
    records: list[dict] = []
    total_blocked = 0
    error_count = 0
    aborted = False
    abort_reason = ""

    t_start = time.perf_counter()
    for i, row in enumerate(prompts, 1):
        goal = row["Goal"]
        cat = row["Category"]
        per_category_total[cat] = per_category_total.get(cat, 0) + 1

        try:
            cv = chain.evaluate(goal)
        except Exception as exc:  # noqa: BLE001
            error_count += 1
            records.append({
                "idx": i,
                "behavior_id": row["BehaviorID"],
                "goal_first_120": goal[:120],
                "category": cat,
                "functional_category": row["FunctionalCategory"],
                "blocked": False,
                "errored": True,
                "error": str(exc)[:200],
                "latency_ms": 0.0,
            })
            print(
                f"  [{i:>2}/{n}] ERR by=chain "
                f"err={str(exc)[:80]}",
                flush=True,
            )
            continue

        blocked = bool(cv.blocked)
        if blocked:
            total_blocked += 1
            per_category_blocks[cat] = per_category_blocks.get(cat, 0) + 1
        latencies.append(float(cv.total_latency_ms))

        # Per-vendor tally — only when an EnsembleVerdict (not a
        # short-circuit regex / Lobster Trap rule) reached the judge.
        per_vendor: dict[str, object] = {}
        if hasattr(cv, "judge_verdict") and cv.judge_verdict is not None:
            jv = cv.judge_verdict
            # judge_verdict can be either a JudgeVerdict (single-vendor)
            # or an EnsembleVerdict — only the latter exposes per_vendor.
            pv = getattr(jv, "per_vendor", None)
            if pv:
                for key, vendor_verdict in pv.items():
                    active = getattr(vendor_verdict, "path", "") not in (
                        "unavailable", "out_of_budget", "",
                    )
                    # First-sight init for any backup-route keys
                    # (FallbackVendorAdapter mutates the vendor prefix
                    # when it routes to a backup — e.g. ai_studio ->
                    # openrouter — so the EnsembleVerdict surfaces a
                    # new key we never saw at construction).
                    per_attacker_active.setdefault(key, 0)
                    per_attacker_blocks.setdefault(key, 0)
                    if active:
                        per_attacker_active[key] += 1
                        if vendor_verdict.is_harmful:
                            per_attacker_blocks[key] += 1
                    per_vendor[key] = {
                        "is_harmful": bool(vendor_verdict.is_harmful),
                        "confidence": float(vendor_verdict.confidence),
                        "path": str(getattr(vendor_verdict, "path", "")),
                    }

        records.append({
            "idx": i,
            "behavior_id": row["BehaviorID"],
            "goal_first_120": goal[:120],
            "category": cat,
            "functional_category": row["FunctionalCategory"],
            "blocked": blocked,
            "defended_by": str(cv.defended_by),
            "rule": str(cv.rule or ""),
            "confidence": float(cv.confidence),
            "latency_ms": float(cv.total_latency_ms),
            "errored": False,
            "per_vendor": per_vendor,
        })

        # Read the ensemble's adapter cost ledger (sum of
        # cumulative_cost_usd). FallbackVendorAdapter aggregates its
        # own primary + fallbacks via the @property override.
        cost_so_far = sum(ad.cumulative_cost_usd for ad in ensemble.adapters)

        print(
            f"  [{i:>2}/{n}] "
            f"{'BLOCK' if blocked else 'ALLOW':5} "
            f"by={cv.defended_by:30} "
            f"lat={cv.total_latency_ms:.0f}ms "
            f"cost=${cost_so_far:.4f}",
            flush=True,
        )

        # Hard cost cap — abort gracefully and emit a partial JSON.
        if cost_so_far > COST_CEILING_USD:
            aborted = True
            abort_reason = (
                f"cumulative cost ${cost_so_far:.4f} "
                f"exceeded ceiling ${COST_CEILING_USD:.2f} "
                f"after prompt {i}/{n}"
            )
            print(f"[harmbench] ABORT: {abort_reason}", flush=True)
            break

    total_run_s = time.perf_counter() - t_start
    cost_est_usd = round(
        sum(ad.cumulative_cost_usd for ad in ensemble.adapters), 6,
    )

    # Per-attacker block rate (only over prompts where the vendor was
    # active; 'unavailable' / 'out_of_budget' are excluded from the
    # denominator so quota exhaustion doesn't make a vendor look bad).
    # Canonical seats (primary routes) come first in the JSON for
    # readability; any backup-route keys discovered mid-run are
    # appended after.
    per_attacker_block_rate: dict[str, float] = {}
    ordered_keys = list(canonical_keys) + [
        k for k in per_attacker_active if k not in canonical_keys
    ]
    for k in ordered_keys:
        active = per_attacker_active.get(k, 0)
        blocks = per_attacker_blocks.get(k, 0)
        per_attacker_block_rate[k] = (blocks / active) if active > 0 else 0.0
    # Reorder dicts so JSON output is deterministic (canonical first).
    per_attacker_blocks = {k: per_attacker_blocks.get(k, 0) for k in ordered_keys}
    per_attacker_active = {k: per_attacker_active.get(k, 0) for k in ordered_keys}

    n_for_rate = max(len(records) - error_count, 1)
    overall_block_rate = total_blocked / n_for_rate

    p50 = statistics.median(latencies) if latencies else 0.0
    p99 = (
        sorted(latencies)[max(0, int(len(latencies) * 0.99) - 1)]
        if latencies else 0.0
    )

    wlow, whigh = wilson_ci(total_blocked, n_for_rate)
    ci_halfwidth = (whigh - wlow) / 2.0

    honesty_note = (
        f"HarmBench subset N={n_for_rate} seed={SEED} "
        f"measured 2026-05-16; complements JBB-Behaviors n=80 "
        f"(93.75% +/- 2.7%) baseline."
    )
    if aborted:
        honesty_note = (
            f"aborted at cost ceiling; partial results: {abort_reason}; "
            + honesty_note
        )

    report = {
        "baseline_id": "aegis-ensemble-10frontier",
        "dataset": DATASET_TAG,
        "dataset_source_url": HARMBENCH_CSV_URL,
        "seed": SEED,
        "n_prompts": n_for_rate,
        "n_prompts_attempted": len(records),
        "total_blocked": total_blocked,
        "error_count": error_count,
        "overall_block_rate": overall_block_rate,
        "wilson_ci_95": {
            "lower": wlow,
            "upper": whigh,
            "halfwidth": ci_halfwidth,
            "z": 1.96,
            "method": "Wilson score interval (Newcombe 1998)",
        },
        "per_attacker_block_rate": per_attacker_block_rate,
        "per_attacker_active": per_attacker_active,
        "per_attacker_blocks": per_attacker_blocks,
        "per_category_breakdown": per_category_blocks,
        "per_category_total": per_category_total,
        "latency_p50_ms": p50,
        "latency_p99_ms": p99,
        "total_run_s": total_run_s,
        "cost_est_usd": cost_est_usd,
        "cost_ceiling_usd": COST_CEILING_USD,
        "aborted_at_cost_ceiling": aborted,
        "timestamp_unix": int(time.time()),
        "timestamp_iso": datetime.now(tz=timezone.utc).isoformat(),
        "honesty_note": honesty_note,
        "records": records,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
    )
    print(
        f"\n=== HarmBench subset run complete ==="
        f"\n  baseline_id        : aegis-ensemble-10frontier"
        f"\n  dataset            : {DATASET_TAG}"
        f"\n  n_prompts          : {n_for_rate}"
        f"\n  total_blocked      : {total_blocked}"
        f"\n  overall_block_rate : {overall_block_rate:.4f}"
        f"\n  wilson_ci_95       : "
        f"[{wlow:.4f}, {whigh:.4f}] (+/- {ci_halfwidth:.4f})"
        f"\n  latency_p50_ms     : {p50:.0f}"
        f"\n  latency_p99_ms     : {p99:.0f}"
        f"\n  total_run_s        : {total_run_s:.1f}"
        f"\n  cost_est_usd       : ${cost_est_usd:.4f} "
        f"(ceiling ${COST_CEILING_USD:.2f})"
        f"\n  aborted            : {aborted}"
        f"\n  written to         : {out_path}",
        flush=True,
    )

    return 0


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--out", type=Path, default=None,
        help="Output JSON path; auto-generated under logs/ if absent.",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    out_path = args.out or (
        REPO_ROOT / "logs" / f"harmbench_subset40_{_ts()}.json"
    )
    try:
        return run(out_path)
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
