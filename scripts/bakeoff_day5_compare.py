#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Day-5 vs Day-4 ensemble bake-off aggregate (FallbackVendorAdapter).

Compares the Day-4 RERUN ensemble measurement (commit ``e9b66f4``,
log ``logs/baseline_aegis-ensemble-10frontier_day4_RERUN_20260515T194716Z.json``)
against the Day-5 FALLBACK ensemble measurement and emits:

1. ``logs/bakeoff_day5_<ts>.json`` — machine-readable aggregate.

Scope is intentionally narrower than ``bakeoff_day4_compare.py``: only
the ensemble row + per-seat availability deltas. The 19-baseline Day-4
aggregate (`logs/bakeoff_day4_20260515T201928Z.json`) stays canonical
for the individual-judge baselines — Day-5 did not re-run those.

Per-seat aggregation
====================

Both Day-4 and Day-5 logs store ``per_vendor_agreement`` as a
``{key: {harmful, benign, unavailable}}`` map. The key format is
``f"{verdict.vendor}:{seat_model}"`` — the verdict's actual provider
joined to the seat's stable model label. For Day-5 with
``FallbackVendorAdapter`` seats, a single seat can produce more than
one key across the run (e.g. some prompts answer via the primary
``ai_studio:gemini-3.1-pro-preview`` and the rest via the OR backup
``openrouter:gemini-3.1-pro-preview``). To compare per-seat across the
two runs we bucket all keys by the suffix after the first ``':'`` (the
seat-level model label) and sum the counts.

Usage::

    PYTHONPATH=. python3 scripts/bakeoff_day5_compare.py \\
        --day4 logs/baseline_aegis-ensemble-10frontier_day4_RERUN_20260515T194716Z.json \\
        --day5 logs/baseline_aegis-ensemble-10frontier_day5_FALLBACK_<ts>.json \\
        --out  logs/bakeoff_day5_<ts>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


# Day-5 seat order (matches `apohara_aegis.multi_judge.make_default_adapters`).
SEAT_LABELS: list[tuple[str, str]] = [
    ("Gemini 3.1 Pro", "gemini-3.1-pro-preview"),
    ("Claude Opus 4.7", "claude-opus-4-7"),
    ("GPT-5.5", "gpt-5.5"),
    ("DeepSeek V4 Pro", "deepseek/deepseek-v4-pro"),
    ("MiniMax M2.7", "MiniMax-M2.7"),
    ("Kimi K2.6", "kimi-k2.6"),
    ("GLM 5.1", "glm-5.1"),
    ("Qwen3.6 Plus", "qwen/qwen3.6-plus"),
    ("Nemotron 3 Super 120B", "nvidia/nemotron-3-super-120b-a12b"),
    ("Big Pickle", "big-pickle"),
]


# Day-4 stored per_vendor_agreement under slightly different model
# labels than Day-5 because Day-5 added FallbackVendorAdapter seat
# wrappers that changed the bucketing surface. This map normalises so
# the Day-4 row aligns to the Day-5 seat order even when the suffix
# differs (e.g. ``moonshotai/kimi-k2.6`` on Day-4 vs ``kimi-k2.6`` on
# Day-5 when OCZ Kimi answers).
DAY4_KEY_TO_SEAT: dict[str, str] = {
    "ai_studio:gemini-3.1-pro-preview": "gemini-3.1-pro-preview",
    "opencode_zen:claude-opus-4-7": "claude-opus-4-7",
    "opencode_zen:gpt-5.5": "gpt-5.5",
    "openrouter:deepseek/deepseek-v4-pro": "deepseek/deepseek-v4-pro",
    "minimax:MiniMax-M2.7": "MiniMax-M2.7",
    "openrouter:moonshotai/kimi-k2.6": "kimi-k2.6",
    "openrouter:z-ai/glm-5.1": "glm-5.1",
    "openrouter:qwen/qwen3.6-plus": "qwen/qwen3.6-plus",
    "openrouter:nvidia/nemotron-3-super-120b-a12b":
        "nvidia/nemotron-3-super-120b-a12b",
    "opencode_zen:big-pickle": "big-pickle",
}


def _bucket_day4(per_vendor_agreement: dict) -> dict[str, dict[str, int]]:
    """Return seat-suffix -> {harmful, benign, unavailable} for Day-4."""
    out: dict[str, dict[str, int]] = {}
    for key, counts in per_vendor_agreement.items():
        suffix = DAY4_KEY_TO_SEAT.get(key)
        if suffix is None:
            # Unknown Day-4 key — preserve under its raw form so the
            # aggregate still records it (defensive: future log shapes).
            suffix = key.split(":", 1)[-1]
        a = out.setdefault(
            suffix, {"harmful": 0, "benign": 0, "unavailable": 0}
        )
        a["harmful"] += int(counts.get("harmful", 0))
        a["benign"] += int(counts.get("benign", 0))
        a["unavailable"] += int(counts.get("unavailable", 0))
    return out


def _bucket_day5(per_vendor_agreement: dict) -> dict[str, dict[str, int]]:
    """Return seat-suffix -> {harmful, benign, unavailable} for Day-5.

    Multiple Day-5 keys can share a seat suffix because a single
    FallbackVendorAdapter seat can route through different providers
    across prompts (primary OR backup_N). We sum the counts.
    """
    out: dict[str, dict[str, int]] = {}
    for key, counts in per_vendor_agreement.items():
        # Day-5 key shape is e.g. ``ai_studio:gemini-3.1-pro-preview``
        # or ``openrouter:gemini-3.1-pro-preview`` — both share the
        # seat-level model suffix.
        suffix = key.split(":", 1)[-1]
        a = out.setdefault(
            suffix, {"harmful": 0, "benign": 0, "unavailable": 0}
        )
        a["harmful"] += int(counts.get("harmful", 0))
        a["benign"] += int(counts.get("benign", 0))
        a["unavailable"] += int(counts.get("unavailable", 0))
    return out


def _availability_pct(counts: dict[str, int]) -> float:
    total = counts["harmful"] + counts["benign"] + counts["unavailable"]
    if total == 0:
        return 0.0
    return (counts["harmful"] + counts["benign"]) / total * 100.0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--day4", type=Path, required=True,
                   help="Day-4 RERUN ensemble JSON.")
    p.add_argument("--day5", type=Path, required=True,
                   help="Day-5 FALLBACK ensemble JSON.")
    p.add_argument("--out", type=Path, required=True,
                   help="Output aggregate JSON path.")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    day4 = json.loads(args.day4.read_text())
    day5 = json.loads(args.day5.read_text())

    d4_seats = _bucket_day4(day4.get("per_vendor_agreement", {}))
    d5_seats = _bucket_day5(day5.get("per_vendor_agreement", {}))

    per_seat = []
    for display, suffix in SEAT_LABELS:
        d4 = d4_seats.get(suffix, {"harmful": 0, "benign": 0, "unavailable": 0})
        d5 = d5_seats.get(suffix, {"harmful": 0, "benign": 0, "unavailable": 0})
        per_seat.append({
            "seat": display,
            "model_suffix": suffix,
            "day4": {
                "harmful": d4["harmful"], "benign": d4["benign"],
                "unavailable": d4["unavailable"],
                "availability_pct": round(_availability_pct(d4), 2),
            },
            "day5": {
                "harmful": d5["harmful"], "benign": d5["benign"],
                "unavailable": d5["unavailable"],
                "availability_pct": round(_availability_pct(d5), 2),
            },
        })

    aggregate = {
        "comparison": "Day-4 RERUN (pre-FallbackVendorAdapter) vs Day-5 FALLBACK",
        "day4_source": str(args.day4.name),
        "day5_source": str(args.day5.name),
        "day4_overall_block_rate": day4.get("overall_block_rate"),
        "day5_overall_block_rate": day5.get("overall_block_rate"),
        "day4_total_blocked": day4.get("total_blocked"),
        "day5_total_blocked": day5.get("total_blocked"),
        "day4_error_count": day4.get("error_count"),
        "day5_error_count": day5.get("error_count"),
        "day4_cost_est_usd": day4.get("cost_est_usd"),
        "day5_cost_est_usd": day5.get("cost_est_usd"),
        "day4_latency_p50_ms": day4.get("latency_p50_ms"),
        "day5_latency_p50_ms": day5.get("latency_p50_ms"),
        "n_prompts": day5.get("n_prompts"),
        "per_seat_availability": per_seat,
        "timestamp_unix": int(__import__("time").time()),
        "timestamp_iso": datetime.now(tz=timezone.utc).isoformat(),
        "honesty_note": (
            "Per-seat availability buckets Day-4 and Day-5 by seat-level "
            "model label suffix (the part after the first ':'). For "
            "Day-5 a single FallbackVendorAdapter seat can produce "
            "multiple keys across prompts when different routes fire; "
            "the counts are summed at the seat level. Day-4 had one "
            "fixed provider per seat so the bucketing is 1:1 there. "
            "Block-rate denominators exclude errored prompts (see "
            "run_ensemble_with_timeout.py:overall_block_rate)."
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(aggregate, indent=2, ensure_ascii=False))

    print(f"=== Day-4 vs Day-5 ensemble comparison ===")
    print(f"  Day-4 overall_block_rate: "
          f"{day4.get('overall_block_rate', 0)*100:.2f}%")
    print(f"  Day-5 overall_block_rate: "
          f"{day5.get('overall_block_rate', 0)*100:.2f}%")
    print()
    print(f"{'Seat':<25} {'Day-4 avail':>11} {'Day-5 avail':>11} "
          f"{'Δ':>8}")
    for row in per_seat:
        d4_pct = row["day4"]["availability_pct"]
        d5_pct = row["day5"]["availability_pct"]
        delta = d5_pct - d4_pct
        print(f"  {row['seat']:<23} {d4_pct:>9.2f}%   {d5_pct:>9.2f}%   "
              f"{delta:>+6.2f}pp")
    print()
    print(f"  Aggregate written to: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
