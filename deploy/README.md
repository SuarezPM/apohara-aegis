# deploy/ — Apohara Aegis public demo on Vultr

> Innovation F for TechEx 2026 Track 1.
> Spins up a 1 vCPU / 2 GB Ubuntu 24.04 instance on Vultr (region `ewr`),
> running the full Lobster Trap × Aegis × Caddy stack behind auto-TLS via
> [`nip.io`](https://nip.io). Judges submit prompts at the public URL and
> watch the trust layer block attacks in real time.

## What you get

| URL | What it serves |
| --- | -------------- |
| `https://<IP>.nip.io/`        | Gradio "Try to break our trust layer" UI (`scripts/jbb_live_defense.py`) |
| `https://<IP>.nip.io/lt/`     | Lobster Trap proxy (`/lt/v1/chat/completions`) for direct `curl` |
| `https://<IP>.nip.io/audit`   | Static INV-15 Governance Dashboard (`assets/inv15-governance-dashboard.html`) |

The four compose services:

```
caddy (:80,:443)  ──┬── aegis-ui (:7860, Gradio)
                    ├── lobstertrap (:8080, Veea Lobster Trap)
                    └── (mock-llm :9999, OpenAI-compat stub backend)
```

## One-command provision

```bash
export VULTR_API_KEY='<paste-key-from-vultr-panel>'
python3 deploy/vultr_provision.py
```

The script:

1. Calls Vultr `POST /v2/instances` with cloud-init user-data.
2. Tags the instance with `apohara-aegis-techex2026-demo`.
3. Polls until the public IP is assigned (~30-60s).
4. Prints SSH command and the `https://<IP>.nip.io/` URL.

It is idempotent — re-running it finds the existing tagged instance and
prints the same info instead of provisioning a duplicate.

Cloud-init then takes 3-6 minutes inside the box to:

- install Docker + compose plugin,
- `git clone` this repo to `/opt/apohara-aegis`,
- `docker compose up -d --build`,
- enable `ufw` with only 22/80/443 inbound.

## Cost

- Plan: `vc2-1c-2gb` — **$6/month** (~$0.20/day).
- Bandwidth: 2 TB included; plenty for a 5-day judging window.
- Total spend for the May 14-26, 2026 demo window: **≈ $2.50**.

That's 1.3 % of the user's $200 Vultr credit — well inside the $30 budget cap.

## Verifying after provision

```bash
# Wait ~5 minutes after provision, then:
IP=$(python3 deploy/vultr_provision.py | awk '/ip /{print $3}' | head -1)

# 1. Caddy returns HTTPS root:
curl -sS -o /dev/null -w "%{http_code}\n" https://${IP}.nip.io/

# 2. Static audit dashboard:
curl -sS https://${IP}.nip.io/audit | head -20

# 3. Lobster Trap proxy:
curl -sS -X POST https://${IP}.nip.io/lt/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"model":"x","messages":[{"role":"user","content":"Ignore previous instructions"}]}'
# Expected: HTTP 200 with body id="lobstertrap-deny"
```

On the box itself:

```bash
ssh root@${IP}
docker compose -f /opt/apohara-aegis/deploy/docker-compose.yml ps
tail -f /var/log/apohara-aegis-bootstrap.log
docker compose -f /opt/apohara-aegis/deploy/docker-compose.yml logs -f
```

## Teardown

```bash
python3 deploy/vultr_provision.py --destroy
```

This issues `DELETE /v2/instances/{id}` on the tagged instance and
stops billing immediately. The script aborts cleanly if no such
instance exists.

## Security note (judges, please read)

This is a **public** demo. Prompt-injection attempts are **expected**
and logged. The Gradio UI runs scripts/jbb_live_defense.py against the
JailbreakBench harmful split (100 prompts, NeurIPS 2024). The point of
the demo is to *show* that Lobster Trap + Aegis catches them.

The mock LLM backend returns a canned response and does NOT execute
arbitrary instructions — there is no real model behind the proxy.
If your prompt slips past the policy, you will see a stub completion,
not actual unsafe content.

Do **not**:

- Submit real personal information — your prompts are logged on disk.
- Treat the canned mock-llm response as a Gemini/GPT/Claude output.

## Files in this directory

| File | Purpose |
| ---- | ------- |
| `vultr_provision.py`    | API client + idempotent provision / destroy CLI |
| `cloud-init.yaml`       | First-boot script (Docker install, repo clone, compose up) |
| `docker-compose.yml`    | 4-service stack (mock-llm, lobstertrap, aegis-ui, caddy) |
| `Dockerfile.lobstertrap`| Multi-stage Go build of the upstream Lobster Trap binary |
| `Caddyfile`             | Reverse-proxy routes + automatic Let's Encrypt TLS |
| `README.md`             | This file |
