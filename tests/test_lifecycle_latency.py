# SPDX-License-Identifier: Apache-2.0
"""End-to-end lifecycle latency benchmark for ``soar_pipeline.SOARPipeline``.

Measures orchestration overhead of the 4-stage DETECT -> JUDGE ->
ENFORCE -> FORENSICS pipeline across 1000 iterations on a representative
benign prompt.

Honest framing
==============

The <200 ms p99 target applies to **orchestration overhead only**: the
LLM-ensemble branch is stubbed to a fixed 10 ms ``asyncio.sleep`` so
the measurement isolates pipeline cost from vendor round-trip cost.
Real end-to-end latency (with live vendors) is measured separately in
the existing ``apohara-aegis/logs/baseline_aegis-ensemble-*.json``
artifacts -- those numbers include the actual model inference time
and are not comparable to this benchmark's p99.

Output
======

Writes ``apohara-aegis/logs/lifecycle_latency.json`` with per-stage
p50/p99 and overall p50/p95/p99. The JSON ``framing_note`` field
states the orchestration-only scope so any consumer of the file is
not misled.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apohara_aegis.soar_pipeline import SOARPipeline

# Repo logs/ directory (existing convention -- baseline_*.json live here).
LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LATENCY_LOG = LOGS_DIR / "lifecycle_latency.json"

# Benchmark configuration.
ITERATIONS = 1000
BENIGN_PROMPT = "Write me a Python function that adds two numbers and returns the result."
LLM_STUB_DELAY_MS = 10.0  # honest fixed stub for the LLM branch


async def _llm_stub(_event) -> dict:
    """Fixed-delay LLM ensemble stub -- mirrors US-77's parallel branch shape."""
    await asyncio.sleep(LLM_STUB_DELAY_MS / 1000.0)
    return {
        "vendor_count": 0,
        "final_blocked": False,
        "final_confidence": "STUB",
        "consensus_score": 1.0,
    }


def _quantile(samples: list[float], q: float) -> float:
    """Inclusive linear-interpolated quantile (statistics.quantiles equivalent for one value)."""
    if not samples:
        return 0.0
    if len(samples) == 1:
        return samples[0]
    return float(
        statistics.quantiles(samples, n=1000, method="inclusive")[int(round(q * 1000)) - 1]
    )


@pytest.mark.asyncio
async def test_lifecycle_latency_orchestration_p99_under_200ms() -> None:
    """1000 iterations: assert orchestration p99 < 200 ms (NOT vendor latency)."""

    pipeline = SOARPipeline(
        ledger_path=None,                 # in-memory chain -- isolates pipeline cost
        hmac_key=b"benchmark-key-32-bytes-zzzzzzzzz",
        judge_llm_fn=_llm_stub,
    )

    # Warm-up: import-time cost in the OWASP regex pack and the
    # supplementary rule pack should not pollute the first sample.
    for _ in range(20):
        await pipeline.run(BENIGN_PROMPT)

    detect_samples: list[float] = []
    judge_samples: list[float] = []
    enforce_samples: list[float] = []
    forensics_samples: list[float] = []
    total_samples: list[float] = []

    wall_t0 = time.perf_counter()
    for _ in range(ITERATIONS):
        verdict = await pipeline.run(BENIGN_PROMPT)
        detect_samples.append(verdict.stage_latencies_ms["detect_ms"])
        judge_samples.append(verdict.stage_latencies_ms["judge_ms"])
        enforce_samples.append(verdict.stage_latencies_ms["enforce_ms"])
        forensics_samples.append(verdict.stage_latencies_ms["forensics_ms"])
        total_samples.append(verdict.total_latency_ms)
    wall_elapsed_s = time.perf_counter() - wall_t0

    # Compute p50 / p95 / p99 for the overall pipeline and each stage.
    def p(samples: list[float], q: float) -> float:
        return _quantile(sorted(samples), q)

    total_p50 = p(total_samples, 0.50)
    total_p95 = p(total_samples, 0.95)
    total_p99 = p(total_samples, 0.99)

    result = {
        "stages": {
            "detect_p50_ms": p(detect_samples, 0.50),
            "detect_p99_ms": p(detect_samples, 0.99),
            "judge_p50_ms": p(judge_samples, 0.50),
            "judge_p99_ms": p(judge_samples, 0.99),
            "enforce_p50_ms": p(enforce_samples, 0.50),
            "enforce_p99_ms": p(enforce_samples, 0.99),
            "forensics_p50_ms": p(forensics_samples, 0.50),
            "forensics_p99_ms": p(forensics_samples, 0.99),
        },
        "total_p50_ms": total_p50,
        "total_p95_ms": total_p95,
        "total_p99_ms": total_p99,
        "iterations": ITERATIONS,
        "wall_elapsed_s": wall_elapsed_s,
        "llm_stub_delay_ms": LLM_STUB_DELAY_MS,
        "framing_note": (
            "Orchestration measurement; LLM calls mocked to fixed "
            f"{LLM_STUB_DELAY_MS:.0f}ms. Real vendor latencies measured "
            "separately in apohara-aegis/logs/baseline_aegis-ensemble-*.json."
        ),
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    LATENCY_LOG.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    # Assertion: orchestration-only p99 < 200 ms.
    # If this fails on a slow CI box we MUST weaken the claim in the
    # commit message rather than relax the assertion -- per honesty
    # discipline (CLAUDE.md section 6, 8).
    assert total_p99 < 200.0, (
        f"Orchestration p99 = {total_p99:.2f} ms > 200 ms target. "
        f"p50={total_p50:.2f} ms, p95={total_p95:.2f} ms. "
        f"Per-stage p99: {result['stages']}. "
        "If this is real (not CI jitter), weaken the README claim to the "
        "measured value -- do NOT relax the assertion."
    )
