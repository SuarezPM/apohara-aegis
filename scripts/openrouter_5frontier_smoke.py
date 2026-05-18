"""Day-6 OpenRouter 5-frontier sibling smoke probe.

Sends one minimal prompt per new adapter (``Reply with one word: ping``)
via the existing OpenAI-compatible chat endpoint, capturing latency,
HTTP status, parsed verdict path, and any error. Writes a single JSON
log under ``logs/openrouter_5frontier_smoke_<epoch>.json``.

Skipped automatically when ``OPENROUTER_API_KEY`` is unset.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from apohara_aegis.openrouter_adapters import (
    OpenRouterDeepSeekV32SpecialeAdapter,
    OpenRouterKimiK2ThinkingAdapter,
    OpenRouterLlamaNemotronSuper49BV15Adapter,
    OpenRouterQwen36MaxPreviewAdapter,
    OpenRouterQwen3MaxThinkingAdapter,
)

ADAPTERS = [
    OpenRouterDeepSeekV32SpecialeAdapter,
    OpenRouterKimiK2ThinkingAdapter,
    OpenRouterQwen36MaxPreviewAdapter,
    OpenRouterQwen3MaxThinkingAdapter,
    OpenRouterLlamaNemotronSuper49BV15Adapter,
]
PROBE = "Reply with one word: ping"


async def _probe_one(cls):
    # max_tokens budgeted for the 4-field judge JSON + small CoT trace.
    # The brief's literal ``max_tokens=8`` truncates every reasoning
    # judge mid-output and produces false parse_error verdicts (verified
    # on the first probe run); 400 matches the adapter default.
    adapter = cls(max_tokens=400)
    t0 = time.perf_counter()
    try:
        v = await adapter.evaluate(PROBE)
        elapsed = time.perf_counter() - t0
        return {
            "model_id": adapter.model_id,
            "name": adapter.name,
            "latency_s": round(elapsed, 3),
            "path": v.path,
            "is_harmful": v.is_harmful,
            "confidence": v.confidence,
            "error": v.error,
            "result": "pass" if v.path == "primary" else "fail",
        }
    except Exception as e:  # never let one probe crash the rest
        return {
            "model_id": adapter.model_id,
            "name": adapter.name,
            "latency_s": round(time.perf_counter() - t0, 3),
            "path": None,
            "error": f"{type(e).__name__}: {e}",
            "result": "fail",
        }


async def _main():
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY missing; skipping live probe.", file=sys.stderr)
        return 2
    results = []
    for cls in ADAPTERS:
        r = await _probe_one(cls)
        results.append(r)
        print(f"  {r['model_id']}: {r['result']} (lat={r['latency_s']}s, "
              f"path={r['path']}, err={r['error']})")
    out = REPO_ROOT / "logs" / f"openrouter_5frontier_smoke_{int(time.time())}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {
            "probe": PROBE,
            "endpoint": "https://openrouter.ai/api/v1/chat/completions",
            "results": results,
            "summary": {
                "total": len(results),
                "passed": sum(1 for r in results if r["result"] == "pass"),
                "failed": sum(1 for r in results if r["result"] == "fail"),
            },
        },
        indent=2,
    ))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
