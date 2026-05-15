#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Day-4 bake-off aggregator — 10 frontier + 5 defense + 1 ensemble.

Reads the Day-4 baseline JSONs (filename pattern
``baseline_<id>_day4_<ts>.json``) PLUS the still-current Day-3 JSONs
that were not re-run (e.g. ``aegis-single-gemini``,
``claude-opus-4.7``, ``gpt-5.5``, ``minimax-m2.7``, the 5 defense-tier
JSONs, and the REBUILT Nemotron 4B classifier output) and emits:

1. ``logs/bakeoff_day4_<ts>.json`` — machine-readable aggregate of all
   16 rows with per-defense block_rate / cost / latency / errored,
   plus winners per axis.
2. ``logs/bakeoff_day4_table.md`` — README-ready markdown table.

Winners are computed honestly (same posture as the Day-3
``scripts/bakeoff_compare.py``): defenses with >20% error rate are
EXCLUDED from headline winner picks but DO appear in the row list
with an honest ``error_count`` column. The aggregate ``notes`` field
surfaces any vendor that errored above the 20% bar so the README's
"honest framing" paragraph can name it.

Usage::

    PYTHONPATH=. python3 scripts/bakeoff_day4_compare.py \\
        --out-json logs/bakeoff_day4_<ts>.json \\
        --out-md   logs/bakeoff_day4_table.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


# License / open-source attribution per defense (display column 4).
LICENSE_LABEL: dict[str, str] = {
    # Apohara Aegis tier
    "aegis-ensemble-10frontier": "Apache-2.0 (ours)",
    "aegis-ensemble": "Apache-2.0 (ours, Day-3 6-vendor superseded)",
    "aegis-single-gemini": "Apache-2.0 (ours, Phase-2 baseline)",
    # Frontier tier
    "gemini-3.1-pro": "Google (proprietary, AI Studio)",
    "claude-opus-4.7": "Anthropic (proprietary, opencode Zen)",
    "gpt-5.5": "OpenAI (proprietary, opencode Zen)",
    "openrouter-deepseek-v4-pro": "DeepSeek (open weights, OpenRouter)",
    "minimax-m2.7": "MiniMax (proprietary, direct API)",
    "openrouter-kimi-k2.6": "Moonshot (open weights, OpenRouter)",
    "openrouter-glm-5.1": "Z.ai (open weights, OpenRouter)",
    "openrouter-qwen3.6-plus": "Alibaba (open weights, OpenRouter)",
    "openrouter-nemotron-3-super-120b": "NVIDIA (NIM via OpenRouter)",
    "opencode-zen-big-pickle":
        "opencode Zen stealth tier (= DeepSeek-V4-Flash per live probe)",
    # Defense tier
    "groq-gpt-oss-safeguard": "OpenAI gpt-oss-safeguard 20B (Groq free)",
    "groq-llama-prompt-guard":
        "Meta Llama Prompt Guard 2 86M (Groq free)",
    "nvidia-llama-guard-4-12b": "Meta Llama Guard 4 12B (NIM free)",
    "nvidia-nemoguard-content-safety-8b": "NVIDIA NeMoguard 8B (NIM free)",
    "nvidia-nemotron-content-safety-reasoning-4b":
        "NVIDIA Nemotron Content Safety Reasoning 4B (NIM free)",
}


DISPLAY_NAME: dict[str, str] = {
    "aegis-ensemble-10frontier":
        "Apohara Aegis 10-frontier ensemble (ours)",
    "aegis-ensemble": "Apohara Aegis ensemble (Day-3 6-vendor; superseded)",
    "aegis-single-gemini":
        "Apohara Aegis single Gemini (Phase 2 baseline)",
    "gemini-3.1-pro": "Gemini 3.1 Pro alone",
    "claude-opus-4.7": "Claude Opus 4.7 alone",
    "gpt-5.5": "GPT-5.5 alone",
    "openrouter-deepseek-v4-pro": "DeepSeek V4 Pro alone",
    "minimax-m2.7": "MiniMax M2.7 alone",
    "openrouter-kimi-k2.6": "Kimi K2.6 alone",
    "openrouter-glm-5.1": "GLM 5.1 alone",
    "openrouter-qwen3.6-plus": "Qwen 3.6 Plus alone",
    "openrouter-nemotron-3-super-120b": "Nemotron 3 Super 120B alone",
    "opencode-zen-big-pickle": "Big Pickle alone",
    "groq-gpt-oss-safeguard": "OpenAI gpt-oss-safeguard 20B",
    "groq-llama-prompt-guard": "Meta Llama Prompt Guard 2 86M",
    "nvidia-llama-guard-4-12b": "Meta Llama Guard 4 12B",
    "nvidia-nemoguard-content-safety-8b":
        "NVIDIA NeMoguard Content Safety 8B",
    "nvidia-nemotron-content-safety-reasoning-4b":
        "NVIDIA Nemotron Content Safety Reasoning 4B (rebuilt)",
}


# Day-4 canonical row order: ensemble first, then 10 frontier rows in
# the same order as `make_default_adapters()`, then 5 defense-tier rows.
PREFERRED_ORDER: list[str] = [
    # Apohara Aegis row (the headline row).
    "aegis-ensemble-10frontier",
    # 10 frontier individual baselines (the ensemble's members).
    "claude-opus-4.7",
    "gpt-5.5",
    "gemini-3.1-pro",
    "openrouter-deepseek-v4-pro",
    "minimax-m2.7",
    "openrouter-kimi-k2.6",
    "openrouter-glm-5.1",
    "openrouter-qwen3.6-plus",
    "openrouter-nemotron-3-super-120b",
    "opencode-zen-big-pickle",
    # Secondary defense tier.
    "groq-gpt-oss-safeguard",
    "groq-llama-prompt-guard",
    "nvidia-llama-guard-4-12b",
    "nvidia-nemoguard-content-safety-8b",
    "nvidia-nemotron-content-safety-reasoning-4b",
]


# Canonical baseline -> JSON-path resolution. The Day-3 baseline JSONs
# (1500Z) are reused for everything not re-run on Day-4. Day-4 fresh
# JSONs (with the _day4_ token in the filename) take precedence.
DEFAULT_SOURCE_BY_ID: dict[str, list[str]] = {
    # 10-frontier ensemble — DAY-4 fresh (alias filename). The RERUN
    # JSON (post OpenRouter top-up) supersedes the original 1824Z
    # file which fired during the credit-exhausted window.
    "aegis-ensemble-10frontier": [
        "baseline_aegis-ensemble-10frontier_day4_RERUN_*.json",
        "baseline_aegis-ensemble-10frontier_day4_*.json",
    ],
    # 5 of the 10 frontier rows REUSE Day-3 measurements per the
    # Agent D brief (avoiding throttle / cost burn for unchanged
    # implementations).
    "aegis-single-gemini": [
        "baseline_aegis-single-gemini_20260515T1500Z.json",
    ],
    # Claude Opus + MiniMax got fresh RERUN measurements at 1910Z;
    # Gemini + GPT-5.5 hit upstream quota / silent-error patterns on
    # the rerun and reuse their cleaner 1500Z baselines (also Day-4).
    "gemini-3.1-pro": [
        "baseline_gemini-3.1-pro_20260515T1500Z.json",
    ],
    "claude-opus-4.7": [
        "baseline_claude-opus-4.7_day4_RERUN_*.json",
        "baseline_claude-opus-4.7_20260515T1500Z.json",
    ],
    "gpt-5.5": [
        "baseline_gpt-5.5_20260515T1500Z.json",
    ],
    "minimax-m2.7": [
        "baseline_minimax-m2.7_day4_RERUN_*.json",
        "baseline_minimax-m2.7_20260515T1500Z.json",
    ],
    # 6 frontier rows are Day-4 NEW measurements. After Pablo's
    # OpenRouter top-up on 2026-05-15 PM, all 5 OpenRouter vendors
    # got re-measured cleanly — the _RERUN_ JSONs are the canonical
    # Day-4 source; the original _182434Z_ files (credit-exhausted)
    # remain in repo as honest audit trail of the quota incident.
    "openrouter-deepseek-v4-pro": [
        "baseline_openrouter-deepseek-v4-pro_day4_RERUN_*.json",
        "baseline_openrouter-deepseek-v4-pro_day4_*.json",
    ],
    "openrouter-kimi-k2.6": [
        "baseline_openrouter-kimi-k2.6_day4_RERUN_*.json",
        "baseline_openrouter-kimi-k2.6_day4_*.json",
    ],
    "openrouter-glm-5.1": [
        "baseline_openrouter-glm-5.1_day4_RERUN_*.json",
        "baseline_openrouter-glm-5.1_day4_*.json",
    ],
    "openrouter-qwen3.6-plus": [
        "baseline_openrouter-qwen3.6-plus_day4_RERUN_*.json",
        "baseline_openrouter-qwen3.6-plus_day4_*.json",
    ],
    "openrouter-nemotron-3-super-120b": [
        "baseline_openrouter-nemotron-3-super-120b_day4_RERUN_*.json",
        "baseline_openrouter-nemotron-3-super-120b_day4_*.json",
    ],
    "opencode-zen-big-pickle": [
        "baseline_opencode-zen-big-pickle_day4_*.json",
    ],
    # Secondary defense tier.
    # Groq free-tier was re-attempted on Day-4 but rate-limit ceilings
    # remained binding (60-75% of prompts returned HTTP 429 on both
    # gpt-oss-safeguard and llama-prompt-guard). The Day-3 1700Z JSON
    # is canonical; the Day-4 RERUN JSON is preserved as evidence of
    # the persistent throttle.
    "groq-gpt-oss-safeguard": [
        "baseline_groq-gpt-oss-safeguard_20260515T1700Z.json",
        "baseline_groq-gpt-oss-safeguard_day4_RERUN_*.json",
    ],
    "groq-llama-prompt-guard": [
        "baseline_groq-llama-prompt-guard_20260515T1700Z.json",
        "baseline_groq-llama-prompt-guard_day4_RERUN_*.json",
    ],
    "nvidia-llama-guard-4-12b": [
        "baseline_nvidia-llama-guard-4-12b_20260515T1500Z.json",
    ],
    "nvidia-nemoguard-content-safety-8b": [
        "baseline_nvidia-nemoguard-content-safety-8b_20260515T1500Z.json",
    ],
    "nvidia-nemotron-content-safety-reasoning-4b": [
        # IMPORTANT: REBUILT classifier output supersedes the Day-3
        # refusal-heuristic measurement per AUDIT #16 (commit b361aac).
        "baseline_nvidia-nemotron-content-safety-reasoning-4b_REBUILT_*.json",
    ],
}


def _resolve_source(baseline_id: str) -> Path | None:
    """Pick the highest-priority JSON path for ``baseline_id``.

    For globs, returns the lexically latest match (most recent
    timestamp). Returns ``None`` if no file matches — the row is
    omitted from the table and surfaced in ``missing`` for honest
    reporting.
    """
    for pattern in DEFAULT_SOURCE_BY_ID.get(baseline_id, []):
        candidates = sorted(
            (REPO_ROOT / "logs").glob(pattern), reverse=True,
        )
        if candidates:
            return candidates[0]
    return None


def _load_baselines() -> tuple[list[dict], list[str]]:
    """Load every Day-4 baseline JSON in canonical order.

    Returns ``(loaded_rows, missing_ids)``. Missing IDs are surfaced
    in the aggregate's ``notes`` field rather than silently dropped.
    """
    loaded: list[dict] = []
    missing: list[str] = []
    for bid in PREFERRED_ORDER:
        path = _resolve_source(bid)
        if path is None:
            missing.append(bid)
            continue
        try:
            data = json.loads(path.read_text())
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] skipping {path}: {exc}", file=sys.stderr)
            missing.append(bid)
            continue
        if "baseline_id" not in data:
            continue
        summary = {k: v for k, v in data.items() if k != "records"}
        summary["_source_path"] = str(path)
        # Day-4 alias: keep the file's baseline_id field but stamp the
        # "row_id" we emit to the table so the alias filename's row is
        # reported as the alias name (not the underlying chain ID).
        summary["_row_id"] = bid
        loaded.append(summary)
    return loaded, missing


def _summarize(baselines: list[dict], missing: list[str]) -> dict:
    """Compute the aggregate JSON + winners (honest)."""
    def _err_frac(b: dict) -> float:
        return b.get("error_count", 0) / max(b.get("n_prompts", 1), 1)

    reliable = [b for b in baselines if _err_frac(b) <= 0.20]
    above70 = [
        b for b in reliable if b["overall_block_rate"] >= 0.70
    ]
    highest = (
        max(reliable, key=lambda b: b["overall_block_rate"])
        if reliable else None
    )
    lowest_cost = (
        min(above70, key=lambda b: b["cost_est_usd"])
        if above70 else None
    )
    lowest_lat = (
        min(above70, key=lambda b: b["latency_p50_ms"])
        if above70 else None
    )
    free_tier_reliable = [b for b in reliable if b["cost_est_usd"] == 0.0]
    best_free = (
        max(free_tier_reliable, key=lambda b: b["overall_block_rate"])
        if free_tier_reliable else None
    )
    # Best PAID-tier reliable (>0 cost) — useful for showing the
    # frontier-judge winner separately from the free-tier winner.
    paid_tier_reliable = [b for b in reliable if b["cost_est_usd"] > 0.0]
    best_paid = (
        max(paid_tier_reliable, key=lambda b: b["overall_block_rate"])
        if paid_tier_reliable else None
    )

    notes: list[str] = []
    if missing:
        notes.append(
            "Missing baseline JSONs (no fresh measurement available): "
            + ", ".join(missing)
        )
    rate_limited = [
        b["_row_id"] for b in baselines if _err_frac(b) > 0.20
    ]
    if rate_limited:
        notes.append(
            "Baselines excluded from headline-winner picks due to "
            f">20% error rate: {', '.join(rate_limited)}"
        )

    return {
        "dataset": "jbb-behaviors-holdout-80",
        "phase": "Phase 4 Day 4 (2026-05-15)",
        "ensemble_composition_note": (
            "aegis-ensemble-10frontier uses the 10-vendor frontier "
            "roster wired in apohara_aegis/multi_judge.make_default_adapters "
            "as of Day-4 commit `e9b66f4`. The 6 OpenRouter / Big "
            "Pickle individual baselines are fresh Day-4 measurements; "
            "the Day-3 4 frontier rows (Gemini 3.1 Pro / Claude Opus "
            "4.7 / GPT-5.5 / MiniMax M2.7) reuse the 2026-05-15T1500Z "
            "JSONs (same code path, no measurement change). The 5 "
            "defense-tier rows include the REBUILT Nemotron 4B "
            "classifier per AUDIT #16."
        ),
        "baselines": [
            {
                "id": b["_row_id"],
                "underlying_baseline_id": b["baseline_id"],
                "block_rate": round(b["overall_block_rate"], 4),
                "total_blocked": b["total_blocked"],
                "n_prompts": b["n_prompts"],
                "error_count": b.get("error_count", 0),
                "cost_usd": round(b["cost_est_usd"], 6),
                "latency_p50_ms": round(b["latency_p50_ms"], 1),
                "latency_p99_ms": round(b["latency_p99_ms"], 1),
                "open_source_label":
                    LICENSE_LABEL.get(b["_row_id"], "unknown"),
                "display_name":
                    DISPLAY_NAME.get(b["_row_id"], b["_row_id"]),
                "source_path": b.get("_source_path"),
            }
            for b in baselines
        ],
        "winners_note": (
            "Computed only among defenses with <=20% error rate "
            "('reliable' set). A defense rate-limited on >20% of "
            "prompts shows inflated block_rate on the smaller "
            "denominator; we surface those rows in the table but "
            "exclude them from winner picks."
        ),
        "winners": {
            "highest_block_rate": (
                {
                    "id": highest["_row_id"],
                    "block_rate": round(highest["overall_block_rate"], 4),
                }
                if highest else None
            ),
            "lowest_cost_above_70pct": (
                {
                    "id": lowest_cost["_row_id"],
                    "block_rate":
                        round(lowest_cost["overall_block_rate"], 4),
                    "cost_usd": round(lowest_cost["cost_est_usd"], 6),
                }
                if lowest_cost else None
            ),
            "lowest_latency_above_70pct": (
                {
                    "id": lowest_lat["_row_id"],
                    "block_rate":
                        round(lowest_lat["overall_block_rate"], 4),
                    "latency_p50_ms":
                        round(lowest_lat["latency_p50_ms"], 1),
                }
                if lowest_lat else None
            ),
            "best_free_tier": (
                {
                    "id": best_free["_row_id"],
                    "block_rate":
                        round(best_free["overall_block_rate"], 4),
                }
                if best_free else None
            ),
            "best_paid_tier": (
                {
                    "id": best_paid["_row_id"],
                    "block_rate":
                        round(best_paid["overall_block_rate"], 4),
                    "cost_usd": round(best_paid["cost_est_usd"], 6),
                }
                if best_paid else None
            ),
            "rate_limited_excluded": rate_limited,
        },
        "notes": notes,
        "summary_generated_iso":
            datetime.now(tz=timezone.utc).isoformat(),
    }


def _render_markdown_table(summary: dict) -> str:
    """Render the Day-4 comparative table as README markdown."""
    lines = [
        "| Defense | Tier | Block rate | Cost / 80 | p50 latency | License / Provider |",
        "|---|---|---:|---:|---:|---|",
    ]
    frontier_ids = set(PREFERRED_ORDER[1:11])  # 10 frontier rows
    ensemble_ids = {"aegis-ensemble-10frontier", "aegis-ensemble"}
    for b in summary["baselines"]:
        name = b["display_name"]
        if b["id"] in ensemble_ids:
            tier = "ensemble"
        elif b["id"] in frontier_ids:
            tier = "frontier"
        else:
            tier = "defense"
        block_rate = f"{100.0 * b['block_rate']:.1f}%"
        if b["error_count"]:
            block_rate += f" ({b['error_count']} err)"
        cost = (
            "$0"
            if b["cost_usd"] == 0.0 else f"${b['cost_usd']:.4f}"
        )
        lat_s = b["latency_p50_ms"] / 1000.0
        lat = f"{lat_s:.1f}s"
        lic = b["open_source_label"]
        lines.append(
            f"| **{name}** | {tier} | {block_rate} | {cost} | {lat} | {lic} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--out-json", required=True, type=Path,
        help="Path to write the aggregate JSON.",
    )
    p.add_argument(
        "--out-md", required=True, type=Path,
        help="Path to write the markdown table snippet.",
    )
    args = p.parse_args()

    baselines, missing = _load_baselines()
    if not baselines:
        print("[err] no baseline JSONs found", file=sys.stderr)
        return 2
    summary = _summarize(baselines, missing)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(summary, indent=2))
    md = _render_markdown_table(summary)
    args.out_md.write_text(md)
    print(f"[ok] {len(baselines)} baselines aggregated")
    print(f"[ok] JSON  -> {args.out_json}")
    print(f"[ok] MD    -> {args.out_md}")
    if missing:
        print(f"[warn] missing baseline IDs: {', '.join(missing)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
