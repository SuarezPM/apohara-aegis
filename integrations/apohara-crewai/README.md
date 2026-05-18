# apohara-crewai

CrewAI middleware for [Apohara PROBANT](https://github.com/SuarezPM/apohara-aegis).
Wraps CrewAI tools so every `_run` call is gated through the Apohara judge API.

> **Python version constraint**: `crewai>=0.30` requires Python <=3.13.
> This package cannot be installed on Python 3.14+. Use Python 3.10-3.13.

## Install

```bash
# Local install for development / testing (Python 3.10-3.13):
pip install -e ./integrations/apohara-crewai

# When published to PyPI (future):
pip install apohara-crewai
```

## Quick start (10 lines)

```python
from crewai.tools import BaseTool
from apohara_crewai import apohara_guard

class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something"
    def _run(self, input: str) -> str:
        return f"result: {input}"

safe_tool = apohara_guard(MyTool(), block_on_review=False)
result = safe_tool._run("safe input")  # ALLOW → returns "result: safe input"
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `APOHARA_API_URL` | `https://api.apohara.dev` | Base URL of the Apohara judge API |
| — | — | — |

## Behavior

| Judge verdict | `block_on_review=False` (default) | `block_on_review=True` |
|---|---|---|
| ALLOW | Tool `_run` is called | Tool `_run` is called |
| REVIEW | Log warning, call `_run` | Raise `RuntimeError` |
| BLOCK | Raise `RuntimeError` | Raise `RuntimeError` |

Network failures are **fail-open** by default: a warning is logged but the tool proceeds.
Set `fail_open=False` to raise `RuntimeError` on network errors.

## Caveat — latency

Each `_run` call adds one synchronous HTTP round-trip to `/v1/soar/judge/evaluate`.
For production use, deploy the Apohara API on the same network segment as your
CrewAI agents to minimize this overhead.

## License

Apache-2.0 — see [LICENSE](LICENSE).
