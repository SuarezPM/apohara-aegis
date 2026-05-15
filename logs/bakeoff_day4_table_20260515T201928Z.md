| Defense | Tier | Block rate | Cost / 80 | p50 latency | License / Provider |
|---|---|---:|---:|---:|---|
| **Apohara Aegis 10-frontier ensemble (ours)** | ensemble | 87.5% | $1.4296 | 22.0s | Apache-2.0 (ours) |
| **Claude Opus 4.7 alone** | frontier | 92.2% (3 err) | $1.0314 | 3.1s | Anthropic (proprietary, opencode Zen) |
| **GPT-5.5 alone** | frontier | 92.5% | $0.1170 | 3.4s | OpenAI (proprietary, opencode Zen) |
| **Gemini 3.1 Pro alone** | frontier | 93.7% (1 err) | $0 | 7.5s | Google (proprietary, AI Studio) |
| **DeepSeek V4 Pro alone** | frontier | 91.7% (8 err) | $0.0276 | 6.7s | DeepSeek (open weights, OpenRouter) |
| **MiniMax M2.7 alone** | frontier | 97.3% (5 err) | $0.0396 | 4.5s | MiniMax (proprietary, direct API) |
| **Kimi K2.6 alone** | frontier | 96.0% (55 err) | $0.0878 | 11.5s | Moonshot (open weights, OpenRouter) |
| **GLM 5.1 alone** | frontier | 96.4% (24 err) | $0.0827 | 6.8s | Z.ai (open weights, OpenRouter) |
| **Qwen 3.6 Plus alone** | frontier | 91.2% | $0.0794 | 11.9s | Alibaba (open weights, OpenRouter) |
| **Nemotron 3 Super 120B alone** | frontier | 98.7% (2 err) | $0.0088 | 10.7s | NVIDIA (NIM via OpenRouter) |
| **Big Pickle alone** | frontier | 97.5% | $0 | 4.1s | opencode Zen stealth tier (= DeepSeek-V4-Flash per live probe) |
| **OpenAI gpt-oss-safeguard 20B** | defense | 100.0% (60 err) | $0 | 0.0s | OpenAI gpt-oss-safeguard 20B (Groq free) |
| **Meta Llama Prompt Guard 2 86M** | defense | 25.0% (48 err) | $0 | 0.0s | Meta Llama Prompt Guard 2 86M (Groq free) |
| **Meta Llama Guard 4 12B** | defense | 86.2% | $0 | 0.7s | Meta Llama Guard 4 12B (NIM free) |
| **NVIDIA NeMoguard Content Safety 8B** | defense | 91.2% | $0 | 0.8s | NVIDIA NeMoguard 8B (NIM free) |
| **NVIDIA Nemotron Content Safety Reasoning 4B (rebuilt)** | defense | 95.0% | $0 | 1.4s | NVIDIA Nemotron Content Safety Reasoning 4B (NIM free) |
| **Mistral Medium 3 (bonus)** | bonus | 97.5% | $0.0188 | 1.9s | Mistral Medium 3 (Mistral AI, OpenRouter) |
| **DeepSeek V4 Flash explicit (bonus, A/B vs Big Pickle)** | bonus | 93.5% (3 err) | $0.0060 | 3.9s | DeepSeek V4 Flash explicit (OpenRouter; A/B vs Big Pickle) |
| **DeepSeek R1 reasoning (bonus, n=40)** | bonus | 90.0% | $0.0615 | 27.3s | DeepSeek R1 reasoning model (OpenRouter, n=40 only) |
