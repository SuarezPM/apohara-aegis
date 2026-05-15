| Defense | Block rate | Cost (80 prompts) | Latency p50 | License |
|---|---:|---:|---:|---|
| Apohara Aegis ensemble (ours) | 95.0% | $1.1715 | 10064 ms | Apache-2.0 (ours) |
| Apohara Aegis single Gemini (Phase 2 baseline) | 95.0% | $0.0592 | 6533 ms | Apache-2.0 (ours) |
| Claude Opus 4.7 alone | 92.2% (3 err) | $1.0322 | 3114 ms | Anthropic (proprietary) |
| GPT-5.5 alone | 92.5% | $0.1170 | 3436 ms | OpenAI (proprietary) |
| MiniMax M2.7 alone | 91.0% (2 err) | $0.0379 | 9769 ms | MiniMax (proprietary) |
| NVIDIA NeMoguard Content Safety 8B | 91.2% | $0 | 807 ms | NVIDIA (NIM free) |
| NVIDIA Nemotron Safety Reasoning 4B | 93.8% | $0 | 4974 ms | NVIDIA (NIM free) |
| Meta Llama Guard 4 12B | 86.2% | $0 | 691 ms | Meta (NVIDIA NIM free) |
| OpenAI gpt-oss-safeguard 20B | 100.0% (60 err) | $0 | 0 ms | OpenAI (Groq free tier) |
| Meta Llama Prompt Guard 2 86M | 25.0% (48 err) | $0 | 0 ms | Meta (Groq free tier) |
| Gemini-3.1-pro alone (no Aegis chain) | 93.7% (1 err) | $0 | 7501 ms | Google (proprietary) |
