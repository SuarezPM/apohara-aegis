# SPDX-License-Identifier: Apache-2.0
"""Apohara Aegis × smolagents — minimal end-to-end demo.

Run::

    pip install smolagents
    PYTHONPATH=. python examples/aegis_smolagents_demo.py

The demo runs the agent twice — once with safe metadata (allowed),
once with high-risk critic metadata (blocked by INV-15). No real
network calls; we stub the model so the demo is hermetic.
"""
from __future__ import annotations

from smolagents import CodeAgent
from smolagents.models import ChatMessage, MessageRole

from apohara_aegis import AegisBlocked, AegisGuard


class _DemoModel:
    """Stub model — emits final_answer('ok') so the loop terminates fast."""
    model_id = "demo-stub"

    def generate(self, messages, stop_sequences=None, **kw):
        return ChatMessage(role=MessageRole.ASSISTANT,
                           content='<code>\nfinal_answer("ok")\n</code>')

    def __call__(self, *a, **kw):
        return self.generate(*a, **kw)


def main() -> None:
    agent = CodeAgent(tools=[], model=_DemoModel(), max_steps=2)
    AegisGuard.wrap(
        agent,
        policy_path="configs/lobstertrap_policy.yaml",
        # lt_endpoint="http://localhost:8080",  # uncomment for live LT proxy
        judge_role="critic",
        tau=0.65,
    )
    print(f"Aegis loaded policy: {agent.aegis_policy.name} v{agent.aegis_policy.version}")

    # 1) Safe call — retriever role, max reuse but exempt
    agent.aegis_meta = {"role": "retriever", "candidate_count": 4, "reuse_rate": 1.0}
    print("→ retriever step:", agent.run("safe"))

    # 2) Unsafe call — critic role under high JCR risk
    agent.aegis_meta = {
        "role": "critic", "candidate_count": 5,
        "reuse_rate": 0.9, "layout_shuffled": True,
    }
    try:
        agent.run("unsafe")
    except AegisBlocked as exc:
        print(f"→ critic step BLOCKED ✓: {exc.assessment.reason}")
    except Exception as exc:
        # smolagents may wrap; surface inner AegisBlocked if present
        cur = exc.__cause__ or exc.__context__
        while cur is not None:
            if isinstance(cur, AegisBlocked):
                print(f"→ critic step BLOCKED ✓ (chained): {cur.assessment.reason}")
                return
            cur = cur.__cause__ or cur.__context__
        raise


if __name__ == "__main__":
    main()
