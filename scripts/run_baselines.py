#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Standalone-defense baseline runner — Day-3 11-defense bake-off.

Runs ONE defense baseline against a deterministic JBB-Behaviors
held-out set (or HarmBench, in commit 4) and emits a JSON report.
This is the comparative scaffolding the bake-off (commit 3) chains
together with :mod:`scripts.bakeoff_compare`.

Supported ``--baseline`` values
==============================

1. ``aegis-ensemble``                     — full chain w/ EnsembleJudge
2. ``aegis-single-gemini``                — Phase-2 single-judge baseline
3. ``gemini-3.1-pro``                     — Gemini AS A SINGLE JUDGE (no chain)
4. ``claude-opus-4.7``                    — ClaudeOpus47Adapter alone
5. ``gpt-5.5``                            — GPT55Adapter alone
6. ``minimax-m2.7``                       — MiniMaxM27Adapter alone
7. ``groq-gpt-oss-safeguard``             — Groq defense, alone
8. ``groq-llama-prompt-guard``            — Groq defense, alone
9. ``nvidia-llama-guard-4-12b``           — NVIDIA NIM, alone
10. ``nvidia-nemoguard-content-safety-8b`` — NVIDIA NIM, alone
11. ``nvidia-nemotron-content-safety-reasoning-4b`` — NVIDIA NIM, alone

Determinism contract
====================

The 80-prompt JBB-Behaviors held-out set is the SAME deterministic
slice the Phase-2 measurement used: ``random.Random(0).sample(...)``
after excluding the 20 calibration prompts. Every baseline runs the
SAME prompts in the SAME order. See :func:`load_jbb_holdout_prompts`.

Honesty
=======

If a vendor errors on a given prompt the per-prompt record carries
``errored=True`` + ``defended_by="error"``. The baseline-level
``overall_block_rate`` is computed as ``total_blocked / (n_prompts -
errored)`` so an outage doesn't silently push a high block rate; the
errored count is surfaced in the JSON. The report also carries the
raw errored count in ``error_count`` for the bakeoff_compare summary.

Usage
=====

::

    PYTHONPATH=. python3 scripts/run_baselines.py \\
        --baseline=groq-llama-prompt-guard \\
        --dataset=jbb-behaviors-holdout \\
        --n-prompts=80 \\
        --out logs/baseline_groq-llama-prompt-guard_<ts>.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Constants — calibration set definition (Phase 2 lock)
# ---------------------------------------------------------------------------


# The Phase-2 calibration JSON
# ``logs/jbb_calibration_20260514T194703Z.json`` reserved the first 20
# indices of the seed-0 shuffle as the calibration set. The held-out
# test set is therefore indices [20, 100) (the remaining 80 prompts),
# in the order the seed-0 shuffle yields them. EVERY baseline iterates
# these prompts in this order — no re-shuffling.
CALIBRATION_INDICES: set[int] = set(range(20))
HOLDOUT_N: int = 80
SEED: int = 0


# ---------------------------------------------------------------------------
# Dataset loaders
# ---------------------------------------------------------------------------


def load_jbb_holdout_prompts(n: Optional[int] = None) -> list[dict]:
    """Load the canonical 80-prompt held-out JBB-Behaviors test set.

    Returns the rows that were NOT used for Phase-2 threshold
    calibration. Rows are dicts with keys ``Goal``, ``Category``,
    ``Source``. Pass ``n=N`` to truncate to the first N (used for
    quick smokes); default returns all 80.
    """
    from scripts.jbb_live_defense import load_jbb_prompts, MAX_PROMPTS  # noqa: PLC0415

    all_prompts = load_jbb_prompts(n=MAX_PROMPTS, seed=SEED)
    holdout = [p for i, p in enumerate(all_prompts) if i not in CALIBRATION_INDICES]
    if n is not None:
        holdout = holdout[:n]
    return holdout


def load_harmbench_prompts(n: int = 100) -> list[dict]:
    """Load N HarmBench prompts (commit 4 uses this).

    Returns rows with the SAME keys as JBB (``Goal``, ``Category``,
    ``Source``) so downstream record-shape is uniform. HarmBench's
    ``walledai/HarmBench`` HF dataset has a ``standard`` split with
    400 prompts; we sample deterministically with seed=0.
    """
    from datasets import load_dataset  # noqa: PLC0415

    ds = load_dataset("walledai/HarmBench", "standard", split="train")
    rows = list(ds)
    rng = random.Random(SEED)
    rng.shuffle(rows)
    chosen = rows[:n]
    # Normalize keys: HarmBench uses ``prompt`` and ``category``.
    out = []
    for r in chosen:
        goal = r.get("prompt") or r.get("behavior") or r.get("Goal", "")
        category = r.get("category") or r.get("Category", "harmful")
        out.append({
            "Goal": goal,
            "Category": category,
            "Source": "HarmBench (Mazeika et al. 2024)",
        })
    return out


# ---------------------------------------------------------------------------
# Per-baseline runner — uniform return shape
# ---------------------------------------------------------------------------


def _run_aegis_ensemble(prompt: str) -> dict:
    """Full Apohara Aegis chain with the 6-vendor EnsembleJudge.

    Layer 1 (regex) -> Layer 2 (LT not wired here; None) -> Layer 3
    (EnsembleJudge default). The LT layer is left out because:
    - The Vultr deployment is the ONLY place LT is live (Phase-3 / #12).
    - The Phase-2 measurement on this same held-out set without LT
      already established the 95% baseline.
    - Including LT in the bake-off would make the comparison apples-
      to-apples ONLY for aegis-* baselines; standalone defenses would
      need a wrapper that adds LT for fairness. Easier and more honest
      to compare WITHOUT LT for all 11.
    """
    from apohara_aegis.defense_chain import make_default_chain  # noqa: PLC0415
    from apohara_aegis.multi_judge import make_default_ensemble  # noqa: PLC0415

    if not hasattr(_run_aegis_ensemble, "_chain"):
        ensemble = make_default_ensemble(fast_path=False)
        _run_aegis_ensemble._chain = make_default_chain(
            judge=ensemble, lt_call_fn=None, judge_threshold=0.5,
        )
    cv = _run_aegis_ensemble._chain.evaluate(prompt)
    return _wrap_chain_verdict(cv)


def _run_aegis_single_gemini(prompt: str) -> dict:
    """Phase-2 baseline: regex -> single-vendor GeminiJudge."""
    from apohara_aegis.defense_chain import make_default_chain  # noqa: PLC0415
    from apohara_aegis.gemini_judge import make_default_judge  # noqa: PLC0415

    if not hasattr(_run_aegis_single_gemini, "_chain"):
        _run_aegis_single_gemini._chain = make_default_chain(
            judge=make_default_judge(), lt_call_fn=None, judge_threshold=0.5,
        )
    cv = _run_aegis_single_gemini._chain.evaluate(prompt)
    return _wrap_chain_verdict(cv)


def _wrap_chain_verdict(cv) -> dict:
    """ChainVerdict -> uniform record dict."""
    return {
        "blocked": bool(cv.blocked),
        "defended_by": str(cv.defended_by),
        "rule": str(cv.rule or ""),
        "confidence": float(cv.confidence),
        "latency_ms": float(cv.total_latency_ms),
        "errored": False,
        "error": None,
    }


def _run_single_vendor(adapter, prompt: str) -> dict:
    """Run ONE VendorAdapter standalone (no chain)."""
    t0 = time.perf_counter()
    try:
        v = asyncio.run(adapter.evaluate(prompt))
    except Exception as exc:  # noqa: BLE001
        return {
            "blocked": False,
            "defended_by": "error",
            "rule": "transport_error",
            "confidence": 0.0,
            "latency_ms": (time.perf_counter() - t0) * 1000.0,
            "errored": True,
            "error": str(exc)[:200],
        }
    blocked = bool(v.is_harmful and v.confidence >= 0.5)
    errored = (v.path in ("unavailable", "out_of_budget"))
    return {
        "blocked": blocked,
        "defended_by": (
            "error" if errored else adapter.name
        ),
        "rule": str(v.category),
        "confidence": float(v.confidence),
        "latency_ms": float(v.latency_ms),
        "errored": bool(errored),
        "error": v.error if errored else None,
    }


def _make_adapter(baseline: str):
    """Return the VendorAdapter for a single-vendor baseline."""
    from apohara_aegis.multi_judge import (  # noqa: PLC0415
        ClaudeOpus47Adapter, GPT55Adapter, GeminiAIStudioAdapter,
        GroqGptOssSafeguardAdapter, GroqLlamaPromptGuardAdapter,
        MiniMaxM27Adapter,
    )
    from apohara_aegis.nvidia_defenses import (  # noqa: PLC0415
        NvidiaLlamaGuard4Adapter, NvidiaNeMoguardContentSafety8BAdapter,
        NvidiaNemotronSafetyReasoning4BAdapter,
    )
    table = {
        "gemini-3.1-pro": GeminiAIStudioAdapter,
        "claude-opus-4.7": ClaudeOpus47Adapter,
        "gpt-5.5": GPT55Adapter,
        "minimax-m2.7": MiniMaxM27Adapter,
        "groq-gpt-oss-safeguard": GroqGptOssSafeguardAdapter,
        "groq-llama-prompt-guard": GroqLlamaPromptGuardAdapter,
        "nvidia-llama-guard-4-12b": NvidiaLlamaGuard4Adapter,
        "nvidia-nemoguard-content-safety-8b":
            NvidiaNeMoguardContentSafety8BAdapter,
        "nvidia-nemotron-content-safety-reasoning-4b":
            NvidiaNemotronSafetyReasoning4BAdapter,
    }
    return table[baseline]()


CHAIN_BASELINES = {"aegis-ensemble", "aegis-single-gemini"}
SINGLE_BASELINES = {
    "gemini-3.1-pro", "claude-opus-4.7", "gpt-5.5", "minimax-m2.7",
    "groq-gpt-oss-safeguard", "groq-llama-prompt-guard",
    "nvidia-llama-guard-4-12b", "nvidia-nemoguard-content-safety-8b",
    "nvidia-nemotron-content-safety-reasoning-4b",
}
ALL_BASELINES = sorted(CHAIN_BASELINES | SINGLE_BASELINES)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def run_baseline(
    baseline: str,
    dataset: str,
    n_prompts: int,
    out_path: Path,
) -> dict:
    """Run ONE baseline against ONE dataset; write JSON report."""
    if dataset == "jbb-behaviors-holdout":
        prompts = load_jbb_holdout_prompts(n=n_prompts)
    elif dataset == "harmbench":
        prompts = load_harmbench_prompts(n=n_prompts)
    else:
        raise ValueError(f"unknown dataset: {dataset}")

    # Choose the runner
    if baseline == "aegis-ensemble":
        run_fn = _run_aegis_ensemble
    elif baseline == "aegis-single-gemini":
        run_fn = _run_aegis_single_gemini
    elif baseline in SINGLE_BASELINES:
        adapter = _make_adapter(baseline)
        def run_fn(p: str) -> dict:
            return _run_single_vendor(adapter, p)
    else:
        raise ValueError(f"unknown baseline: {baseline}")

    # Iterate
    records: list[dict] = []
    blocks_by_cat: dict[str, int] = {}
    totals_by_cat: dict[str, int] = {}
    rules: dict[str, int] = {}
    latencies: list[float] = []
    error_count = 0
    total_blocked = 0
    t_start = time.perf_counter()

    for i, row in enumerate(prompts, 1):
        goal = row["Goal"]
        cat = row["Category"]
        totals_by_cat[cat] = totals_by_cat.get(cat, 0) + 1
        rec = run_fn(goal)
        rec["idx"] = i
        rec["category"] = cat
        rec["goal_first_120"] = goal[:120]
        records.append(rec)
        if rec["errored"]:
            error_count += 1
        elif rec["blocked"]:
            total_blocked += 1
            blocks_by_cat[cat] = blocks_by_cat.get(cat, 0) + 1
        rules[rec["rule"] or "none"] = rules.get(rec["rule"] or "none", 0) + 1
        latencies.append(rec["latency_ms"])
        print(
            f"  [{i:>2}/{len(prompts)}] {baseline:38} "
            f"{'BLOCK' if rec['blocked'] else ('ERR' if rec['errored'] else 'ALLOW'):5} "
            f"by={rec['defended_by']:38} lat={rec['latency_ms']:.0f}ms",
            flush=True,
        )

    n = len(prompts)
    n_for_rate = max(n - error_count, 1)
    overall_block_rate = total_blocked / n_for_rate
    p50 = statistics.median(latencies) if latencies else 0.0
    p99 = (sorted(latencies)[max(0, int(len(latencies) * 0.99) - 1)]
           if latencies else 0.0)
    total_run_s = time.perf_counter() - t_start

    # Cost estimate: best-effort via adapter's cumulative ledger if
    # single-vendor; otherwise the chain's downstream judge already
    # logs its own ledger so we read from there.
    cost_est = 0.0
    if baseline in SINGLE_BASELINES:
        adapter_obj = run_fn.__closure__[0].cell_contents  # the adapter
        cost_est = round(getattr(adapter_obj, "cumulative_cost_usd", 0.0), 6)
    elif baseline == "aegis-ensemble":
        ens = _run_aegis_ensemble._chain.judge
        cost_est = round(
            sum(ad.cumulative_cost_usd for ad in ens.adapters), 6,
        )
    elif baseline == "aegis-single-gemini":
        judge = _run_aegis_single_gemini._chain.judge
        cost_est = round(
            getattr(judge, "cumulative_cost_usd", 0.0)
            if hasattr(judge, "cumulative_cost_usd") else 0.0,
            6,
        )

    report = {
        "baseline_id": baseline,
        "dataset": dataset,
        "n_prompts": n,
        "calibration_indices_excluded": (
            sorted(CALIBRATION_INDICES)
            if dataset == "jbb-behaviors-holdout" else []
        ),
        "seed": SEED,
        "total_blocked": total_blocked,
        "error_count": error_count,
        "overall_block_rate": overall_block_rate,
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
        "records": records,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(
        f"\n=== baseline={baseline} ==="
        f"\n  n_prompts        : {n}"
        f"\n  total_blocked    : {total_blocked}"
        f"\n  error_count      : {error_count}"
        f"\n  overall_block_rate: {overall_block_rate:.4f}"
        f"\n  latency_p50_ms   : {p50:.0f}"
        f"\n  latency_p99_ms   : {p99:.0f}"
        f"\n  cost_est_usd     : {cost_est}"
        f"\n  report written to: {out_path}",
        flush=True,
    )
    return report


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--baseline", required=True, choices=ALL_BASELINES,
                   help=f"One of: {ALL_BASELINES}")
    p.add_argument("--dataset",
                   default="jbb-behaviors-holdout",
                   choices=["jbb-behaviors-holdout", "harmbench"],
                   help="Test set.")
    p.add_argument("--n-prompts", type=int, default=HOLDOUT_N,
                   help=f"Number of prompts (default {HOLDOUT_N}).")
    p.add_argument("--out", type=Path, default=None,
                   help="Output JSON path; auto-generated if absent.")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    out_path = args.out or (
        REPO_ROOT / "logs"
        / f"baseline_{args.baseline}_{_ts()}.json"
    )
    try:
        run_baseline(
            baseline=args.baseline,
            dataset=args.dataset,
            n_prompts=args.n_prompts,
            out_path=out_path,
        )
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
