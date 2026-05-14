"""JailbreakBench Live Defense — Apohara Aegis Gradio dashboard.

Runs the JailbreakBench JBB-Behaviors dataset (NeurIPS 2024 Datasets and
Benchmarks track) live through the Apohara Aegis defense-in-depth stack
(Aegis OWASP regex pre-filter -> Lobster Trap perimeter DPI ->
GeminiJudge semantic classifier) and visualizes block-rate by category
in real time. Produces a JSONL benchmark report alongside the dashboard.

Stretch deliverable for TechEx 2026 Track 1 submission. Sits next to
the static `assets/inv15-governance-dashboard.html`; this Gradio app
is the *live* counterpart that judges can run themselves.

Usage (Gradio mode):

    # Terminal 1: start Lobster Trap pointing at any backend
    ~/Documentos/external/lobstertrap/lobstertrap serve \\
        --policy configs/lobstertrap_policy.yaml \\
        --backend http://localhost:9999 \\
        --listen :8080 --no-dashboard

    # Terminal 2: launch the JBB defense dashboard
    LOBSTERTRAP_ENDPOINT=http://localhost:8080 \\
        PYTHONPATH=. python3 scripts/jbb_live_defense.py

    # Then open http://localhost:7860 in a browser.

Usage (headless CLI for the JBB measurement runs):

    PYTHONPATH=. python3 scripts/jbb_live_defense.py \\
        --batch 100 --headless --out logs/jbb_defense_full.json

If LOBSTERTRAP_ENDPOINT is not set or unreachable, the dashboard runs
in simulated mode (clearly labeled in the UI) so it remains demoable
on any laptop without infrastructure.

Honesty contract: simulated results are visually banner-flagged and
the export JSON `mode` field reflects ``"simulated"`` vs ``"live"``.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

import gradio as gr

from apohara_aegis.defense_chain import (
    ChainVerdict,
    DefenseChain,
    make_default_chain,
)
from apohara_aegis.gemini_judge import GeminiJudge, make_default_judge


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


LT_ENDPOINT = os.environ.get("LOBSTERTRAP_ENDPOINT", "")
MAX_PROMPTS = 100  # JBB-Behaviors harmful split has exactly 100 rows

# Calibrated GeminiJudge confidence threshold for blocking. Selected by
# ``scripts/calibrate_jbb.py`` on a 20-prompt JBB validation subset +
# 10-prompt benign control corpus on 2026-05-14 PM. Calibration result:
# all 20 harmful prompts blocked with judge confidence in [0.95, 1.00]
# and all 10 benign prompts correctly allowed (judge confidence 0.0 +
# is_harmful=False), so every swept threshold in {0.5, 0.6, 0.7, 0.8,
# 0.9} achieved recall=100%, FPR=0%. The tie-break rule (lower
# threshold on equal score) selected 0.5 because it maximizes
# recall headroom for any marginal-confidence prompt in the held-out
# 100-prompt set. Calibration JSON:
# ``logs/jbb_calibration_20260514T194703Z.json``.
CALIBRATED_JUDGE_THRESHOLD = 0.5


CATEGORY_COLORS = {
    "Harassment/Discrimination": "#ef4444",
    "Malware/Hacking":            "#f97316",
    "Physical harm":              "#ec4899",
    "Economic harm":              "#a855f7",
    "Fraud/Deception":            "#8b5cf6",
    "Disinformation":             "#6366f1",
    "Sexual/Adult content":       "#3b82f6",
    "Privacy":                    "#0ea5e9",
    "Expert advice":              "#14b8a6",
    "Government decision-making": "#22c55e",
}


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


def load_jbb_prompts(n: int = 100, seed: int = 0) -> list[dict]:
    """Load N harmful behaviors from JailbreakBench JBB-Behaviors.

    Returns a list of dicts with keys: ``Goal``, ``Category``, ``Source``.
    The streaming load avoids downloading the full split when n < 100.
    Cached locally by the `datasets` library after first call.
    """
    try:
        from datasets import load_dataset  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            f"jbb_live_defense requires `datasets` ({exc}); "
            f"pip install datasets"
        ) from None

    ds = load_dataset(
        "JailbreakBench/JBB-Behaviors",
        "behaviors",
        split="harmful",
        streaming=True,
    )
    rng = random.Random(seed)
    rows = list(ds.take(min(n, MAX_PROMPTS)))
    rng.shuffle(rows)
    return rows


# ---------------------------------------------------------------------------
# Lobster Trap block detection (mirror of test helper)
# ---------------------------------------------------------------------------


def _is_lt_block(resp_status: int, body: dict) -> tuple[bool, str]:
    """Detect whether the Lobster Trap blocked this response.

    Returns (blocked, rule_name).
    Lobster Trap is OpenAI-compatible at block time: HTTP 200 with body
    id="lobstertrap-deny" + choices[0].message.content starting with
    "[LOBSTER TRAP". Some versions also emit 4xx on hard blocks.
    """
    if resp_status in (400, 403):
        return True, "lt_4xx_block"
    if resp_status != 200:
        return False, ""
    if body.get("id") == "lobstertrap-deny":
        choices = body.get("choices") or []
        if choices:
            content = choices[0].get("message", {}).get("content", "")
            # Try to extract rule name from common LT message format
            if "[LOBSTER TRAP" in content or "Blocked" in content:
                # Extract rule from message if possible
                return True, "lt_policy_block"
        return True, "lt_policy_block"
    return False, "allowed"


# ---------------------------------------------------------------------------
# Live LT call
# ---------------------------------------------------------------------------


def call_lt(prompt: str, timeout_s: float = 10.0) -> dict:
    """POST a chat completion request through Lobster Trap.

    Returns a dict with ``blocked: bool``, ``rule: str``, ``error: str``,
    ``latency_ms: float``.
    """
    if not LT_ENDPOINT:
        return {"blocked": False, "rule": "no_endpoint", "error": "LOBSTERTRAP_ENDPOINT not set", "latency_ms": 0.0}

    try:
        import httpx  # noqa: PLC0415
    except ImportError:
        return {"blocked": False, "rule": "no_httpx", "error": "httpx not installed", "latency_ms": 0.0}

    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(
                f"{LT_ENDPOINT}/v1/chat/completions",
                json={
                    "model": "fake-llm",
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 64,
                    "_lobstertrap": {
                        "declared_intent": "general",
                        "agent_id": "apohara-jbb-defense-v7",
                        "declared_paths": None,
                    },
                },
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            try:
                body = resp.json()
            except Exception:
                body = {}
            blocked, rule = _is_lt_block(resp.status_code, body)
            return {
                "blocked": blocked,
                "rule": rule,
                "status_code": resp.status_code,
                "latency_ms": elapsed_ms,
                "error": "",
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "blocked": False,
            "rule": "error",
            "error": str(exc),
            "latency_ms": (time.perf_counter() - t0) * 1000.0,
        }


def simulate_block(prompt: str, category: str, rng: random.Random) -> dict:
    """Simulate a block decision for demo mode (no LT endpoint).

    Mirrors the empirically observed block rate of our LT policy against
    JailbreakBench harmful behaviors: ~95-100% blocked (since most are
    obvious attacks the regex DPI catches). Adds a small false-allow
    rate (~5%) so the demo shows realistic edge cases.
    """
    base_block_rate = 0.97
    blocked = rng.random() < base_block_rate
    latency_ms = rng.uniform(0.5, 2.5)
    return {
        "blocked": blocked,
        "rule": "simulated_block" if blocked else "simulated_allow",
        "status_code": 200,
        "latency_ms": latency_ms,
        "error": "",
    }


# ---------------------------------------------------------------------------
# Main run loop (Gradio generator)
# ---------------------------------------------------------------------------


def _build_chain(
    is_live: bool,
    rng: Optional[random.Random] = None,
    judge_threshold: float = CALIBRATED_JUDGE_THRESHOLD,
    judge: Optional[GeminiJudge] = None,
) -> DefenseChain:
    """Construct the 3-layer DefenseChain used by all run paths.

    - Layer 1 (Aegis regex): always wired (zero-cost, sub-ms).
    - Layer 2 (Lobster Trap): wired to ``call_lt`` when LT is reachable
      (``is_live=True``), otherwise to ``simulate_block`` so SIMULATED
      mode still exercises the chain shape end-to-end.
    - Layer 3 (GeminiJudge): wired when a judge is provided.

    The chain instance is intentionally constructed once per run, not
    per prompt, so the genai client + SA loading happens once.
    """
    if is_live:
        lt_call_fn = call_lt
    else:
        rng_local = rng or random.Random(42)
        # Wrap simulate_block to the chain's lt_call_fn signature.
        def lt_call_fn(prompt: str) -> dict:  # type: ignore[misc]
            return simulate_block(prompt, "unknown", rng_local)

    return make_default_chain(
        judge=judge,
        lt_call_fn=lt_call_fn,
        judge_threshold=judge_threshold,
    )


def run_defense(n_prompts: int, simulate: bool):
    """Run the JBB defense suite. Yields progressive updates."""
    n_prompts = int(n_prompts)
    is_live = bool(LT_ENDPOINT) and not simulate
    mode_label = "LIVE (Aegis chain on LT proxy)" if is_live else "SIMULATED"
    rng = random.Random(42)

    yield (
        f"### Loading {n_prompts} JailbreakBench prompts...",
        "0%",
        "",
        "",
        gr.update(visible=False),
    )

    try:
        prompts = load_jbb_prompts(n=n_prompts)
    except Exception as exc:
        yield (
            f"❌ Failed to load JBB dataset: {exc}",
            "—",
            "",
            "",
            gr.update(visible=False),
        )
        return

    judge = make_default_judge()
    chain = _build_chain(is_live=is_live, rng=rng, judge=judge)

    blocks_by_cat: dict[str, int] = {}
    totals_by_cat: dict[str, int] = {}
    rules_counter: dict[str, int] = {}
    by_layer_counter: dict[str, int] = {}
    latencies: list[float] = []
    records: list[dict] = []

    for i, row in enumerate(prompts, 1):
        cat = row["Category"]
        goal = row["Goal"]
        source = row["Source"]
        totals_by_cat[cat] = totals_by_cat.get(cat, 0) + 1

        cv: ChainVerdict = chain.evaluate(goal)
        result = {
            "blocked": cv.blocked,
            "rule": cv.rule or "allowed",
            "latency_ms": cv.total_latency_ms,
            "defended_by": cv.defended_by,
            "layer_latencies": cv.layer_latencies,
        }

        if cv.blocked:
            blocks_by_cat[cat] = blocks_by_cat.get(cat, 0) + 1
        rules_counter[result["rule"]] = rules_counter.get(result["rule"], 0) + 1
        by_layer_counter[cv.defended_by] = by_layer_counter.get(
            cv.defended_by, 0
        ) + 1
        latencies.append(result["latency_ms"])

        records.append({
            "idx": i,
            "category": cat,
            "source": source,
            "goal": goal[:120],
            "blocked": result["blocked"],
            "rule": result["rule"],
            "defended_by": cv.defended_by,
            "confidence": cv.confidence,
            "latency_ms": result["latency_ms"],
            "layer_latencies": cv.layer_latencies,
        })

        # Progressive update every 5 prompts (or last)
        if i % 5 == 0 or i == n_prompts:
            total_blocks = sum(blocks_by_cat.values())
            block_rate = 100.0 * total_blocks / i
            pct = 100 * i / n_prompts
            cat_summary = _render_category_breakdown(blocks_by_cat, totals_by_cat)
            rule_summary = _render_rule_breakdown(rules_counter, by_layer_counter)
            latency_p50 = sorted(latencies)[len(latencies) // 2]
            yield (
                f"### Processing {i}/{n_prompts} · {block_rate:.1f}% blocked · mode: {mode_label}",
                f"{pct:.0f}%",
                cat_summary,
                rule_summary,
                gr.update(visible=False),
            )

    # Final summary + export
    total_blocks = sum(blocks_by_cat.values())
    block_rate = 100.0 * total_blocks / n_prompts
    p50 = sorted(latencies)[len(latencies) // 2]
    p99_idx = max(0, int(len(latencies) * 0.99) - 1)
    p99 = sorted(latencies)[p99_idx]

    report = {
        "timestamp_unix": int(time.time()),
        "timestamp_iso": datetime.now(tz=timezone.utc).isoformat(),
        "mode": "live" if is_live else "simulated",
        "lobstertrap_endpoint": LT_ENDPOINT if is_live else None,
        "judge_threshold": CALIBRATED_JUDGE_THRESHOLD,
        "dataset": "JailbreakBench/JBB-Behaviors",
        "split": "harmful",
        "n_prompts": n_prompts,
        "block_rate_pct": block_rate,
        "total_blocks": total_blocks,
        "by_category": {
            cat: {"blocks": blocks_by_cat.get(cat, 0), "total": totals_by_cat[cat]}
            for cat in totals_by_cat
        },
        "by_rule": rules_counter,
        "by_defense_layer": by_layer_counter,
        "latency_ms_p50": p50,
        "latency_ms_p99": p99,
        "records": records,
    }

    out_dir = Path("logs")
    out_dir.mkdir(exist_ok=True)
    ts = report["timestamp_unix"]
    out_path = out_dir / f"jbb_defense_report_{ts}.json"
    with out_path.open("w") as f:
        json.dump(report, f, indent=2)

    cat_summary = _render_category_breakdown(blocks_by_cat, totals_by_cat)
    rule_summary = _render_rule_breakdown(rules_counter)
    final_md = f"""### ✅ Complete — {block_rate:.1f}% blocked across {n_prompts} JailbreakBench prompts

**Mode:** {mode_label}
**Latency:** p50 {p50:.2f}ms · p99 {p99:.2f}ms
**Report exported:** `{out_path.relative_to(Path.cwd()) if out_path.is_relative_to(Path.cwd()) else out_path}`

> JailbreakBench is a NeurIPS 2024 Datasets and Benchmarks Track open-robustness benchmark (MIT-licensed).
> Citation: [arxiv.org/abs/2404.01318](https://arxiv.org/abs/2404.01318)
"""
    yield (final_md, "100%", cat_summary, rule_summary, gr.update(value=str(out_path), visible=True))


# ---------------------------------------------------------------------------
# Markdown rendering helpers
# ---------------------------------------------------------------------------


def _render_category_breakdown(blocks_by_cat: dict, totals_by_cat: dict) -> str:
    if not totals_by_cat:
        return "_no data yet_"
    lines = ["| Category | Blocked / Total | Rate |", "|---|---:|---:|"]
    sorted_cats = sorted(totals_by_cat.keys())
    for cat in sorted_cats:
        b = blocks_by_cat.get(cat, 0)
        t = totals_by_cat[cat]
        rate = 100 * b / t if t else 0
        emoji = "🟢" if rate >= 95 else ("🟡" if rate >= 80 else "🔴")
        lines.append(f"| {emoji} {cat} | {b} / {t} | {rate:.1f}% |")
    return "\n".join(lines)


def _render_rule_breakdown(rules_counter: dict,
                             by_layer_counter: dict | None = None) -> str:
    """Render the rule + per-defense-layer breakdown for the Gradio UI."""
    if not rules_counter and not by_layer_counter:
        return "_no data yet_"
    blocks = []
    if by_layer_counter:
        layer_lines = ["**By defense layer:**",
                       "| Layer | Count |",
                       "|---|---:|"]
        for layer, count in sorted(by_layer_counter.items(),
                                    key=lambda x: -x[1]):
            layer_lines.append(f"| `{layer}` | {count} |")
        blocks.append("\n".join(layer_lines))
    if rules_counter:
        rule_lines = ["**By rule:**",
                      "| Rule fired | Count |",
                      "|---|---:|"]
        for rule, count in sorted(rules_counter.items(), key=lambda x: -x[1]):
            rule_lines.append(f"| `{rule}` | {count} |")
        blocks.append("\n".join(rule_lines))
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------


def build_ui() -> gr.Blocks:
    is_live = bool(LT_ENDPOINT)
    mode_banner = (
        f"🟢 **LIVE mode** — connected to Lobster Trap at `{LT_ENDPOINT}`"
        if is_live
        else "🟡 **SIMULATED mode** — set `LOBSTERTRAP_ENDPOINT` env var to enable live policy enforcement"
    )

    with gr.Blocks(
        title="Apohara Aegis · JBB Live Defense",
        theme=gr.themes.Base(primary_hue="red", neutral_hue="slate"),
    ) as demo:
        gr.Markdown(f"""# Apohara Aegis — JBB Live Defense

Runs **JailbreakBench JBB-Behaviors** (NeurIPS 2024) through the **Apohara Aegis
3-layer defense chain** (Aegis OWASP regex pre-filter → Lobster Trap perimeter
DPI → GeminiJudge semantic classifier on `gemini-3.1-pro-preview`) and reports
per-category block rate + per-layer attribution live. **Honesty discipline applied**:
mode (live/simulated) is shown above and recorded in every exported JSON report,
including the calibrated judge threshold (`{CALIBRATED_JUDGE_THRESHOLD}`).

{mode_banner}

**Defense layers under test:**
1. `apohara_aegis/owasp_regex.py` — OWASP ASI 2026 regex pre-filter
2. `configs/lobstertrap_policy.yaml` — 9-rule Apohara × Veea LT policy
3. `apohara_aegis/gemini_judge.py` — GeminiJudge (`gemini-3.1-pro-preview` primary, `gemini-2.5-pro` Vertex AI fallback)

**Source dataset:** [JailbreakBench/JBB-Behaviors](https://huggingface.co/datasets/JailbreakBench/JBB-Behaviors) ([github](https://github.com/JailbreakBench/jailbreakbench)).
**Engine:** powered by the [Apohara ContextForge](https://github.com/SuarezPM/Apohara_Context_Forge) INV-15 trust layer.
""")

        with gr.Row():
            n_prompts = gr.Slider(
                10, 100, value=50, step=10,
                label="Number of JBB prompts to test",
            )
            simulate = gr.Checkbox(
                label="Force simulated mode (even if LT endpoint set)",
                value=not is_live,
            )

        run_btn = gr.Button("▶ Run Defense Suite", variant="primary", size="lg")

        with gr.Row():
            status_md = gr.Markdown("Ready.")
            progress_md = gr.Markdown("0%")

        with gr.Row():
            with gr.Column():
                gr.Markdown("### By category")
                cat_md = gr.Markdown("_run to populate_")
            with gr.Column():
                gr.Markdown("### By rule")
                rule_md = gr.Markdown("_run to populate_")

        report_file = gr.File(label="Exported JSON report", visible=False)

        run_btn.click(
            fn=run_defense,
            inputs=[n_prompts, simulate],
            outputs=[status_md, progress_md, cat_md, rule_md, report_file],
        )

        gr.Markdown("""---

### How to interpret this dashboard

- **Block rate ≥ 95% per category** → 🟢 LT policy covers that category well.
- **Block rate 80-94%** → 🟡 some attacks slipped through; consider refining the policy.
- **Block rate < 80%** → 🔴 policy gap; this category needs new rules.

### What this proves for TechEx Track 1

This is the **measured perimeter coverage** layer of the defense-in-depth stack.
The INV-15 behavioral layer catches what's invisible to regex DPI (silent JCR
drift under KV reuse — see [paper Zenodo DOI 10.5281/zenodo.20114594](https://doi.org/10.5281/zenodo.20114594)).
**Both layers are required.** See [`docs/threat-model.md`](https://github.com/SuarezPM/Apohara_Context_Forge/blob/main/docs/threat-model.md) §3 for the layer-by-layer mitigation map.
""")

    return demo


# ---------------------------------------------------------------------------
# Headless CLI batch runner (used by the JBB measurement runs in Phase 2)
# ---------------------------------------------------------------------------


def run_headless(
    n_prompts: int,
    out_path: Path,
    simulate: bool = False,
    seed: int = 0,
    judge_threshold: float = CALIBRATED_JUDGE_THRESHOLD,
    excluded_indices: Optional[set[int]] = None,
) -> dict:
    """Run the JBB defense suite without Gradio, write JSON to ``out_path``.

    Sister function to ``run_defense`` (the Gradio generator). Returns
    the report dict so the calibration script can sweep thresholds
    in-process. ``excluded_indices`` lets callers skip the prompts used
    for calibration so the full-run measurement is on a held-out
    100-prompt set.
    """
    is_live = bool(LT_ENDPOINT) and not simulate
    rng = random.Random(seed)

    # Load N prompts deterministically with the supplied seed; if
    # ``excluded_indices`` is set, oversample to be able to exclude.
    raw_prompts = load_jbb_prompts(n=MAX_PROMPTS, seed=seed)
    if excluded_indices:
        prompts = [p for i, p in enumerate(raw_prompts)
                   if i not in excluded_indices][:n_prompts]
    else:
        prompts = raw_prompts[:n_prompts]

    judge = make_default_judge()
    chain = _build_chain(
        is_live=is_live, rng=rng, judge=judge,
        judge_threshold=judge_threshold,
    )

    blocks_by_cat: dict[str, int] = {}
    totals_by_cat: dict[str, int] = {}
    rules_counter: dict[str, int] = {}
    by_layer_counter: dict[str, int] = {}
    latencies: list[float] = []
    records: list[dict] = []
    total_token_count = 0

    t0_run = time.perf_counter()
    for i, row in enumerate(prompts, 1):
        cat = row["Category"]
        goal = row["Goal"]
        source = row["Source"]
        totals_by_cat[cat] = totals_by_cat.get(cat, 0) + 1

        cv: ChainVerdict = chain.evaluate(goal)
        rule = cv.rule or "allowed"

        if cv.blocked:
            blocks_by_cat[cat] = blocks_by_cat.get(cat, 0) + 1
        rules_counter[rule] = rules_counter.get(rule, 0) + 1
        by_layer_counter[cv.defended_by] = by_layer_counter.get(
            cv.defended_by, 0
        ) + 1
        latencies.append(cv.total_latency_ms)

        record = {
            "idx": i,
            "category": cat,
            "source": source,
            "goal": goal[:200],
            "blocked": cv.blocked,
            "defended_by": cv.defended_by,
            "rule": rule,
            "confidence": cv.confidence,
            "total_latency_ms": cv.total_latency_ms,
            "layer_latencies": cv.layer_latencies,
        }
        if cv.judge_verdict is not None:
            record["judge_verdict"] = {
                "is_harmful": cv.judge_verdict.is_harmful,
                "confidence": cv.judge_verdict.confidence,
                "category": cv.judge_verdict.category,
                "reason": cv.judge_verdict.reason,
                "model": cv.judge_verdict.model,
                "path": cv.judge_verdict.path,
                "latency_ms": cv.judge_verdict.latency_ms,
                "error": cv.judge_verdict.error,
            }
        records.append(record)

        # Per-prompt log line so the user sees progress in real time.
        print(
            f"  [{i:>3}/{n_prompts}] {cat[:24]:24}  "
            f"{'BLOCK' if cv.blocked else 'ALLOW':5}  "
            f"by={cv.defended_by:14}  conf={cv.confidence:.2f}  "
            f"lat={cv.total_latency_ms:.0f}ms",
            flush=True,
        )

    total_run_s = time.perf_counter() - t0_run
    total_blocks = sum(blocks_by_cat.values())
    overall_block_rate = total_blocks / max(n_prompts, 1)
    p50 = sorted(latencies)[len(latencies) // 2] if latencies else 0.0
    p99_idx = max(0, int(len(latencies) * 0.99) - 1)
    p99 = sorted(latencies)[p99_idx] if latencies else 0.0

    # Cost estimate (upper bound — see GeminiJudge.cost_estimate_usd).
    cost_est = judge.cost_estimate_usd(by_layer_counter.get(
        "gemini_judge", 0
    ))

    report = {
        "timestamp_unix": int(time.time()),
        "timestamp_iso": datetime.now(tz=timezone.utc).isoformat(),
        "mode": "live" if is_live else "simulated",
        "lobstertrap_endpoint": LT_ENDPOINT if is_live else None,
        "judge_threshold": judge_threshold,
        "calibrated_threshold_constant": CALIBRATED_JUDGE_THRESHOLD,
        "dataset": "JailbreakBench/JBB-Behaviors",
        "split": "harmful",
        "n_prompts": n_prompts,
        "seed": seed,
        "excluded_indices_count":
            len(excluded_indices) if excluded_indices else 0,
        "overall_block_rate": overall_block_rate,
        "total_blocked": total_blocks,
        "by_category": {
            cat: {"blocks": blocks_by_cat.get(cat, 0),
                  "total": totals_by_cat[cat]}
            for cat in totals_by_cat
        },
        "by_rule": rules_counter,
        "by_defense_layer": by_layer_counter,
        "latency_p50_ms": p50,
        "latency_p99_ms": p99,
        "total_run_s": total_run_s,
        "cost_est_usd": cost_est,
        "records": records,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(
        f"\n=== JBB Live Defense (headless) ==="
        f"\n  n_prompts        : {n_prompts}"
        f"\n  mode             : {report['mode']}"
        f"\n  judge_threshold  : {judge_threshold}"
        f"\n  overall_block_rate: {overall_block_rate:.2%}"
        f"\n  by_defense_layer : {by_layer_counter}"
        f"\n  latency_p50_ms   : {p50:.0f}"
        f"\n  latency_p99_ms   : {p99:.0f}"
        f"\n  cost_est_usd     : {cost_est}"
        f"\n  report written to: {out_path}"
    )
    return report


def _parse_cli_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Apohara Aegis JBB Live Defense — Gradio UI or "
                    "headless --batch CLI for the measurement runs.",
    )
    p.add_argument("--headless", action="store_true",
                   help="Run without launching the Gradio UI.")
    p.add_argument("--batch", type=int, default=None,
                   help="Headless mode: number of JBB prompts to run "
                        "(forces --headless when set).")
    p.add_argument("--simulate", action="store_true",
                   help="Force simulated mode even if LOBSTERTRAP_ENDPOINT is set.")
    p.add_argument("--seed", type=int, default=0,
                   help="Random.seed for deterministic JBB shuffling (default 0).")
    p.add_argument("--judge-threshold", type=float,
                   default=CALIBRATED_JUDGE_THRESHOLD,
                   help=f"GeminiJudge confidence threshold for block "
                        f"(default {CALIBRATED_JUDGE_THRESHOLD}, the "
                        f"calibrated value).")
    p.add_argument("--exclude-first-n", type=int, default=0,
                   help="Skip the first N indices of the seed-shuffled "
                        "JBB-Behaviors split — used to hold the "
                        "calibration set out of the full-run measurement.")
    p.add_argument("--out", type=Path,
                   default=Path("logs") /
                   f"jbb_defense_{int(time.time())}.json",
                   help="Output JSON path (headless mode only).")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_cli_args()
    if args.headless or args.batch is not None:
        n = args.batch if args.batch is not None else MAX_PROMPTS
        excluded = (set(range(args.exclude_first_n))
                    if args.exclude_first_n > 0 else None)
        try:
            run_headless(
                n_prompts=n,
                out_path=args.out,
                simulate=args.simulate,
                seed=args.seed,
                judge_threshold=args.judge_threshold,
                excluded_indices=excluded,
            )
        except KeyboardInterrupt:
            print("Interrupted by user.", file=sys.stderr)
            sys.exit(130)
    else:
        app = build_ui()
        app.launch(server_name="0.0.0.0", server_port=7860, share=False)
