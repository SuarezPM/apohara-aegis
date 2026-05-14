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
# Required: SSH pubkey that will be the only way into the box.
# (Root + password auth are disabled in cloud-init.)
export AEGIS_SSH_PUBKEY="$(cat ~/.ssh/id_ed25519.pub)"

# Optional: judge basicauth credentials. Defaults to
# user=judge / password=apohara-aegis-techex-2026 if unset.
# export AEGIS_JUDGE_USER='judge'
# export AEGIS_JUDGE_PASS_HASH="$(docker run --rm caddy:2.8 caddy hash-password --plaintext 'your-password')"

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

## Security posture

The Phase-4 reviewer pass (2026-05-14) tightened the deploy/* stack on
three axes. The current live URL `https://144.202.8.58.nip.io/` was
provisioned **before** these commits and therefore predates the
hardening; re-provisioning (`vultr_provision.py --destroy` then re-run)
is what activates the controls below. The honest disposition is
tracked in `AUDIT.md` entry #7.

| Control | What | Where |
| ------- | ---- | ----- |
| SSH key-only login | `disable_root: true`, `ssh_pwauth: false`, a non-root sudoer `aegis` carrying a single pubkey read from `AEGIS_SSH_PUBKEY` at provision time. Provisioner aborts BEFORE the Vultr API call if the env var is unset (no silent fallback to root + password). | `cloud-init.yaml`, `vultr_provision.py::load_user_data` |
| Non-root containers | `user: "65532:65532"` on `mock-llm` and `aegis-ui` (lobstertrap is already distroless-nonroot upstream). `aegis-ui` writes Python deps to a tmpfs `PYTHONUSERBASE` and logs to a host dir chmod-1777 by cloud-init. | `docker-compose.yml`, `cloud-init.yaml` |
| Judge basicauth | Caddy `basic_auth` on `/` and `/lt/*`. `/audit` (static governance dashboard) stays public. Credentials default to `judge` / `apohara-aegis-techex-2026`; override via `AEGIS_JUDGE_USER` + `AEGIS_JUDGE_PASS_HASH` env vars at provision time. | `Caddyfile`, `docker-compose.yml::caddy.environment` |

Override path (judge basicauth password):

```bash
# Generate a bcrypt hash for your chosen password (caddy:2.8 image).
docker run --rm caddy:2.8 caddy hash-password --plaintext 'your-strong-password'

# Export both vars before running the provisioner.
export AEGIS_JUDGE_USER='judge'
export AEGIS_JUDGE_PASS_HASH='$2a$14$...the-hash-output-above...'

python3 deploy/vultr_provision.py
```

Honesty note on the current live URL: it remains world-readable
without basicauth until the next re-provision, because re-provisioning
destroys the existing Let's Encrypt certificate (we are on the LE
production rate-limit budget for `*.nip.io`). The hardening above is
queued for the May 19, 2026 final-judging refresh — see AUDIT.md #7.

## Files in this directory

| File | Purpose |
| ---- | ------- |
| `vultr_provision.py`    | API client + idempotent provision / destroy CLI |
| `cloud-init.yaml`       | First-boot script (Docker install, repo clone, compose up) |
| `docker-compose.yml`    | 4-service stack (mock-llm, lobstertrap, aegis-ui, caddy) |
| `Dockerfile.lobstertrap`| Multi-stage Go build of the upstream Lobster Trap binary |
| `Caddyfile`             | Reverse-proxy routes + automatic Let's Encrypt TLS |
| `README.md`             | This file |
