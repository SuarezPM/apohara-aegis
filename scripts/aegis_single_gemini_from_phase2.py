#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Derive the aegis-single-gemini bake-off entry from Phase-2's
canonical measurement.

The Phase-2 measurement on the same 80-prompt JBB-Behaviors held-out
set landed on 2026-05-14 as ``logs/jbb_defense_full_20260514T195225Z.json``
with a documented 95.0% block rate. Re-running the same chain on
Day 3 hit AI Studio quota throttling that pushed the wall-clock from
6.5s/prompt to ~5 min/prompt — not a measurement problem but an
operational one. The honest path is to reuse the Phase-2 JSON as the
canonical baseline for the bake-off (the brief's table explicitly
references that 95.0% number).

Provenance is preserved by recording the Phase-2 source path in the
derived JSON's ``_source_phase2`` field so the bake-off comparator
+ the README footnote both trace back to the original measurement
without any number being re-typed.

Output is a baseline JSON in the same shape as
``scripts/run_baselines.py`` produces, suitable as input to
``scripts/bakeoff_compare.py``.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PHASE2 = REPO_ROOT / "logs" / "jbb_defense_full_20260514T195225Z.json"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: aegis_single_gemini_from_phase2.py <out_path>",
              file=sys.stderr)
        return 2
    out_path = Path(sys.argv[1])
    src = json.loads(PHASE2.read_text())

    n = src["n_prompts"]
    blocked = src["total_blocked"]
    block_rate = src["overall_block_rate"]
    cost_est = src["cost_est_usd"]
    if isinstance(cost_est, dict):
        # Phase-2 reported {ai_studio_max_usd: 0.0592, vertex_max_usd: ...};
        # we want a scalar for the bake-off table. Use the ai_studio
        # number since that is the path that fired (the Vertex
        # fallback was not exercised on this run).
        cost_est_scalar = float(cost_est.get("ai_studio_max_usd", 0.06))
    else:
        cost_est_scalar = float(cost_est)

    by_cat = {
        cat: {"blocks": d["blocks"], "total": d["total"]}
        for cat, d in src["by_category"].items()
    }
    rules = dict(src.get("by_rule", {}))
    p50 = float(src["latency_p50_ms"])
    p99 = float(src["latency_p99_ms"])

    report = {
        "baseline_id": "aegis-single-gemini",
        "dataset": "jbb-behaviors-holdout",
        "n_prompts": n,
        "calibration_indices_excluded": list(range(20)),
        "seed": 0,
        "total_blocked": blocked,
        "error_count": 0,
        "overall_block_rate": block_rate,
        "by_category": by_cat,
        "by_rule": rules,
        "latency_p50_ms": p50,
        "latency_p99_ms": p99,
        "total_run_s": float(src.get("total_run_s", 0.0)),
        "cost_est_usd": cost_est_scalar,
        "timestamp_unix": int(datetime.now(timezone.utc).timestamp()),
        "timestamp_iso": datetime.now(tz=timezone.utc).isoformat(),
        "records": [],  # Phase-2 JSON's per-prompt records would inflate
                        # the bake-off summary; the per-record audit
                        # lives in the original Phase-2 file.
        "_source_phase2": str(PHASE2.relative_to(REPO_ROOT)),
        "_note": (
            "Aegis-single-gemini baseline derived verbatim from the "
            "Phase-2 measurement (regex + LT + Gemini-3.1-PRO judge, "
            "calibrated threshold 0.5). The Day-3 bake-off bake-off "
            "rerun hit AI Studio quota throttling (per-prompt latency "
            "ballooned from 6.5s to ~5 min mid-run) so we use the "
            "Phase-2 numbers — same 80-prompt held-out test set, same "
            "calibrated threshold. This is the only baseline that "
            "carries the Lobster Trap layer (2 of 76 blocks come from "
            "LT, the rest from the judge); the other 10 baselines run "
            "without LT, which is the apples-to-apples comparison "
            "surface for standalone defenses."
        ),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(f"[ok] derived aegis-single-gemini baseline from {PHASE2}")
    print(f"[ok] -> {out_path}")
    print(f"     n_prompts={n} blocked={blocked} block_rate={block_rate:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
