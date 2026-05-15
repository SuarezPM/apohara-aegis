#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fill the Day-5 README + AUDIT placeholders with real measured numbers.

Schema notes
============

``EnsembleJudge.evaluate`` builds ``per_vendor_agreement`` and the
per-prompt verdicts with key ``f"{verdict.vendor}:{adapter.model}"``
(see ``multi_judge.py:1748``). When the adapter is a
``FallbackVendorAdapter``:

- ``verdict.vendor`` = the BACKUP route's real provider (preserved by
  the wrapper for honest dissent) — e.g., ``ai_studio`` if AI Studio
  Gemini fired, ``openrouter`` if the OR Gemini backup fired.
- ``adapter.model`` = the wrapper's ``model_label`` — the stable
  seat-level model name (e.g., ``gemini-3.1-pro-preview``).

So a single Day-5 seat can produce multiple keys across a run if
different routes fired on different prompts. To compute per-seat
availability we bucket by the SECOND component of the key (the suffix
after the first ``:``).

Usage::

    PYTHONPATH=. python3 scripts/fill_day5_placeholders.py \\
        --day5 logs/baseline_aegis-ensemble-10frontier_day5_FALLBACK_<TS>.json \\
        --wiring-sha <SHA-US-003> \\
        --bakeoff-sha <SHA-US-004> \\
        --readme README.md \\
        --audit AUDIT.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# Seat-level model label (from FallbackVendorAdapter.model_label assigned
# in make_default_adapters) → README/AUDIT placeholder key.
# Order matches the README §Day-5 table.
SEAT_MODEL_TO_PLACEHOLDER: list[tuple[str, str]] = [
    ("gemini-3.1-pro-preview", "new-gemini"),
    ("claude-opus-4-7", "new-claude"),
    ("gpt-5.5", "new-gpt55"),
    ("deepseek-v4-pro", "new-deepseek"),
    ("MiniMax-M2.7", "new-minimax"),
    ("kimi-k2.6", "new-kimi"),
    ("glm-5.1", "new-glm"),
    ("qwen3.6-plus", "new-qwen"),
    ("nvidia/nemotron-3-super-120b-a12b", "new-nemotron"),
    ("big-pickle", "new-bigpickle"),
]


def _seat_availability(per_vendor_agreement: dict, seat_model: str) -> float:
    """Bucket per_vendor_agreement keys by seat-level model suffix.

    For seat_model 'gemini-3.1-pro-preview', sums counts across keys
    like 'ai_studio:gemini-3.1-pro-preview' AND
    'openrouter:gemini-3.1-pro-preview' AND
    'openrouter:google/gemini-3.1-pro-preview' (the OR backup adapter
    presents its own model name in the verdict — we match by substring
    on the suffix-after-colon).
    """
    matched_h = 0
    matched_b = 0
    matched_u = 0
    seat_lower = seat_model.lower().replace("/", "").replace("-", "").replace(".", "").replace(" ", "")
    for key, counts in per_vendor_agreement.items():
        if ":" not in key:
            continue
        _, model_part = key.split(":", 1)
        model_lower = model_part.lower().replace("/", "").replace("-", "").replace(".", "").replace(" ", "")
        if seat_lower in model_lower or model_lower in seat_lower:
            matched_h += counts.get("harmful", 0)
            matched_b += counts.get("benign", 0)
            matched_u += counts.get("unavailable", 0)
    total = matched_h + matched_b + matched_u
    if total == 0:
        return 0.0
    avail = matched_h + matched_b
    return avail / total * 100.0


def _format_pct(pct: float) -> str:
    return f"{pct:.2f}"


def _build_substitutions(
    day5: dict,
    wiring_sha: str,
    bakeoff_sha: str,
    timestamp: str,
) -> dict[str, str]:
    block_rate = float(day5.get("overall_block_rate", 0.0)) * 100.0
    subs: dict[str, str] = {
        "<SHA-US-003>": wiring_sha,
        "<SHA-US-004>": bakeoff_sha,
        "<TS>": timestamp,
        "<new-blockrate>": _format_pct(block_rate),
    }
    per_vendor_agree = day5.get("per_vendor_agreement", {})
    for seat_model, placeholder in SEAT_MODEL_TO_PLACEHOLDER:
        pct = _seat_availability(per_vendor_agree, seat_model)
        subs[f"<{placeholder}>"] = _format_pct(pct)
    return subs


def _substitute(text: str, subs: dict[str, str]) -> tuple[str, list[str]]:
    new_text = text
    for placeholder, value in subs.items():
        new_text = new_text.replace(placeholder, value)
    remaining = re.findall(r"<(new-[a-z0-9-]+|SHA-[A-Z0-9-]+|TS)>", new_text)
    return new_text, remaining


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--day5", type=Path, required=True)
    p.add_argument("--wiring-sha", required=True)
    p.add_argument("--bakeoff-sha", required=True)
    p.add_argument("--readme", type=Path, default=Path("README.md"))
    p.add_argument("--audit", type=Path, default=Path("AUDIT.md"))
    args = p.parse_args()

    if not args.day5.exists():
        print(f"ERROR: Day-5 JSON not found at {args.day5}", file=sys.stderr)
        return 1

    day5 = json.loads(args.day5.read_text())
    # Extract timestamp from filename: baseline_..._day5_FALLBACK_<TS>.json
    stem = args.day5.stem
    timestamp = stem.rsplit("FALLBACK_", 1)[-1] if "FALLBACK_" in stem else stem.rsplit("_", 1)[-1]

    subs = _build_substitutions(day5, args.wiring_sha, args.bakeoff_sha, timestamp)
    print("Substitution map:")
    for k, v in subs.items():
        print(f"  {k} -> {v}")
    print()

    overall_ok = True
    for path in (args.readme, args.audit):
        original = path.read_text()
        new_text, remaining = _substitute(original, subs)
        if new_text == original:
            print(f"NOTE: {path} unchanged (no matching placeholders).")
            continue
        path.write_text(new_text)
        n_subs = sum(original.count(k) for k in subs.keys())
        print(f"Updated {path}: {n_subs} substitutions.")
        if remaining:
            print(f"  WARNING: remaining placeholders: {sorted(set(remaining))}",
                  file=sys.stderr)
            overall_ok = False

    return 0 if overall_ok else 2


if __name__ == "__main__":
    sys.exit(main())
