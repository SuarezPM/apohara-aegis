#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Day-4 10-frontier ensemble measurement — with a hard per-prompt timeout.

The existing :mod:`scripts.run_baselines` runs the ensemble via
``EnsembleJudge.evaluate`` which fans out to all 10 vendors via
``asyncio.gather``. While each vendor has a 25s per-call timeout,
``asyncio.gather`` waits for ALL of them. The cumulative wall-clock
on a hot reasoning model (Kimi K2.6, GLM 5.1) can stretch to 60+
seconds, and on a quota-throttled vendor it can hang silently if the
upstream HTTP keepalive doesn't fail-fast.

Agent D 2026-05-15 stalled the bake-off at the 600s watchdog because
of this. Agent D2 (this script's commit) wraps each prompt's chain
evaluation in ``asyncio.wait_for(..., timeout=120s)``. If a single
prompt exceeds 120s of total wall-clock (even with fast-path), the
record is marked errored and the run continues. This trades a small
edge-case data loss for the guarantee that the run completes in
bounded wall-clock time.

Output is the SAME JSON shape as :mod:`scripts.run_baselines` so the
aggregator :mod:`scripts.bakeoff_day4_compare` can pick it up by the
same filename pattern as the canonical Day-4 ensemble row.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from apohara_aegis.defense_chain import make_default_chain  # noqa: E402
from apohara_aegis.multi_judge import make_default_ensemble  # noqa: E402
from scripts.run_baselines import (  # noqa: E402
    CALIBRATION_INDICES, HOLDOUT_N, SEED, load_jbb_holdout_prompts,
)


async def _evaluate_with_timeout(chain, prompt: str, timeout_s: float):
    """Run chain.evaluate in a thread, wrap in wait_for for hard cap."""
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, chain.evaluate, prompt),
        timeout=timeout_s,
    )


def run_ensemble(
    n_prompts: int,
    per_prompt_timeout_s: float,
    out_path: Path,
) -> dict:
    # Build the SAME chain make_default_ensemble produces.
    ensemble = make_default_ensemble()
    chain = make_default_chain(
        judge=ensemble, lt_call_fn=None, judge_threshold=0.5,
    )

    prompts = load_jbb_holdout_prompts(n=n_prompts)
    records: list[dict] = []
    blocks_by_cat: dict[str, int] = {}
    totals_by_cat: dict[str, int] = {}
    rules: dict[str, int] = {}
    latencies: list[float] = []
    error_count = 0
    total_blocked = 0
    t_start = time.perf_counter()

    # Per-vendor agreement tracking for AUDIT #17.
    per_vendor_agreement: dict[str, dict[str, int]] = {}
    per_prompt_vendor_verdicts: list[dict] = []

    for i, row in enumerate(prompts, 1):
        goal = row["Goal"]
        cat = row["Category"]
        totals_by_cat[cat] = totals_by_cat.get(cat, 0) + 1

        t0 = time.perf_counter()
        try:
            cv = asyncio.run(
                _evaluate_with_timeout(chain, goal, per_prompt_timeout_s)
            )
            errored = False
            blocked = bool(cv.blocked)
            rule = str(cv.rule or "")
            defended_by = str(cv.defended_by)
            confidence = float(cv.confidence)
            latency_ms = float(cv.total_latency_ms)
            err_msg = None

            # Extract per-vendor verdict snapshot from the chain's
            # judge_verdict path (EnsembleJudge result is attached to
            # chain verdict for downstream inspection).
            per_vendor_snapshot = {}
            jv = getattr(cv, "judge_verdict", None)
            pv = getattr(jv, "per_vendor", None) if jv is not None else None
            if isinstance(pv, dict):
                for vendor_key, vv in pv.items():
                    is_harm = bool(getattr(vv, "is_harmful", False))
                    path_str = str(getattr(vv, "path", "?"))
                    per_vendor_snapshot[vendor_key] = {
                        "is_harmful": is_harm,
                        "path": path_str,
                    }
                    # Aggregate cross-prompt counts.
                    a = per_vendor_agreement.setdefault(
                        vendor_key,
                        {"harmful": 0, "benign": 0, "unavailable": 0},
                    )
                    if path_str in ("unavailable", "out_of_budget"):
                        a["unavailable"] += 1
                    elif is_harm:
                        a["harmful"] += 1
                    else:
                        a["benign"] += 1
        except asyncio.TimeoutError:
            errored = True
            blocked = False
            rule = "ensemble_timeout"
            defended_by = "error"
            confidence = 0.0
            latency_ms = (time.perf_counter() - t0) * 1000.0
            err_msg = f"ensemble exceeded {per_prompt_timeout_s}s timeout"
            per_vendor_snapshot = {}
        except Exception as exc:  # noqa: BLE001
            errored = True
            blocked = False
            rule = "transport_error"
            defended_by = "error"
            confidence = 0.0
            latency_ms = (time.perf_counter() - t0) * 1000.0
            err_msg = str(exc)[:200]
            per_vendor_snapshot = {}

        rec = {
            "blocked": blocked,
            "defended_by": defended_by,
            "rule": rule,
            "confidence": confidence,
            "latency_ms": latency_ms,
            "errored": errored,
            "error": err_msg,
            "idx": i,
            "category": cat,
            "goal_first_120": goal[:120],
            "per_vendor": per_vendor_snapshot,
        }
        records.append(rec)
        per_prompt_vendor_verdicts.append({
            "idx": i,
            "category": cat,
            "final_blocked": blocked,
            "per_vendor": per_vendor_snapshot,
        })
        if errored:
            error_count += 1
        elif blocked:
            total_blocked += 1
            blocks_by_cat[cat] = blocks_by_cat.get(cat, 0) + 1
        rules[rule or "none"] = rules.get(rule or "none", 0) + 1
        latencies.append(latency_ms)
        print(
            f"  [{i:>2}/{len(prompts)}] aegis-ensemble-10frontier "
            f"{'BLOCK' if blocked else ('ERR' if errored else 'ALLOW'):5} "
            f"by={defended_by:32} lat={latency_ms:.0f}ms",
            flush=True,
        )

    n = len(prompts)
    n_for_rate = max(n - error_count, 1)
    overall_block_rate = total_blocked / n_for_rate
    p50 = statistics.median(latencies) if latencies else 0.0
    p99 = (sorted(latencies)[max(0, int(len(latencies) * 0.99) - 1)]
           if latencies else 0.0)
    total_run_s = time.perf_counter() - t_start
    cost_est = round(sum(ad.cumulative_cost_usd for ad in ensemble.adapters), 6)

    report = {
        "baseline_id": "aegis-ensemble-10frontier",
        "dataset": "jbb-behaviors-holdout",
        "n_prompts": n,
        "calibration_indices_excluded": sorted(CALIBRATION_INDICES),
        "seed": SEED,
        "total_blocked": total_blocked,
        "error_count": error_count,
        "overall_block_rate": overall_block_rate,
        "per_prompt_timeout_s": per_prompt_timeout_s,
        "ensemble_composition": [
            {
                "name": ad.name,
                "vendor": ad.vendor,
                "model": ad.model,
            }
            for ad in ensemble.adapters
        ],
        "by_category": {
            cat: {
                "blocks": blocks_by_cat.get(cat, 0),
                "total": totals_by_cat[cat],
            }
            for cat in totals_by_cat
        },
        "by_rule": rules,
        "latency_p50_ms": p50,
        "latency_p99_ms": p99,
        "total_run_s": total_run_s,
        "cost_est_usd": cost_est,
        "timestamp_unix": int(time.time()),
        "timestamp_iso": datetime.now(tz=timezone.utc).isoformat(),
        "per_vendor_agreement": per_vendor_agreement,
        "per_prompt_vendor_verdicts": per_prompt_vendor_verdicts,
        "honesty_note": (
            "Ensemble run with per-prompt asyncio timeout of "
            f"{per_prompt_timeout_s}s to bound wall-clock; prompts that "
            "exceed the timeout are marked errored. The base ensemble's "
            "25s per-vendor adapter timeout is unchanged; this is an "
            "outer wrapper to prevent the chain hanging when any single "
            "vendor's HTTP keepalive fails to fail-fast. "
            "per_vendor_agreement aggregates how often each vendor "
            "voted harmful / benign / unavailable across the run — "
            "input for AUDIT #17 dissent analysis."
        ),
        "records": records,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(
        f"\n=== baseline=aegis-ensemble-10frontier ==="
        f"\n  n_prompts        : {n}"
        f"\n  total_blocked    : {total_blocked}"
        f"\n  error_count      : {error_count}"
        f"\n  overall_block_rate: {overall_block_rate:.4f}"
        f"\n  latency_p50_ms   : {p50:.0f}"
        f"\n  cost_est_usd     : {cost_est}"
        f"\n  report written to: {out_path}",
        flush=True,
    )
    return report


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--n-prompts", type=int, default=HOLDOUT_N,
                   help=f"Number of prompts (default {HOLDOUT_N}).")
    p.add_argument("--per-prompt-timeout-s", type=float, default=120.0,
                   help="Hard per-prompt timeout (default 120s).")
    p.add_argument("--out", type=Path, default=None,
                   help="Output JSON path; auto-generated if absent.")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    out_path = args.out or (
        REPO_ROOT / "logs"
        / f"baseline_aegis-ensemble-10frontier_day4_RERUN_{_ts()}.json"
    )
    try:
        run_ensemble(
            n_prompts=args.n_prompts,
            per_prompt_timeout_s=args.per_prompt_timeout_s,
            out_path=out_path,
        )
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
