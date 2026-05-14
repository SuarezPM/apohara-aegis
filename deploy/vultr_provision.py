#!/usr/bin/env python3
"""Vultr provisioning script for the Apohara Aegis TechEx 2026 public demo.

Provisions a single $6/mo (1 vCPU / 2 GB / 50 GB) cloud-compute instance in
the New York (``ewr``) region, attaches a cloud-init user-data script that
bootstraps Docker + Caddy + the Aegis stack, and prints the public URL.

Idempotent: if an instance already exists tagged with ``TAG`` (default
``apohara-aegis-techex2026-demo``), the script returns its existing IP
without provisioning a second box.

Usage::

    # Provision (or report existing instance).
    VULTR_API_KEY=... python3 deploy/vultr_provision.py

    # Tear down (destroys the tagged instance, irreversible).
    VULTR_API_KEY=... python3 deploy/vultr_provision.py --destroy

API reference: https://www.vultr.com/api/
Auth: ``Authorization: Bearer $VULTR_API_KEY`` header on every request.

Honesty contract: this script does NOT store the API key anywhere. It reads
from the ``VULTR_API_KEY`` env var only and aborts if absent.

Phase-4 hardening (2026-05-14): the cloud-init YAML now requires an
operator SSH public key (``AEGIS_SSH_PUBKEY`` env var, full ``ssh-ed25519
...`` line). The script substitutes the placeholder before
base64-encoding the YAML and aborts BEFORE any Vultr API call if the
env var is unset — there is no silent fallback to root + password auth.
Judge basicauth credentials (``AEGIS_JUDGE_USER`` /
``AEGIS_JUDGE_PASS_HASH``) are also propagated; when unset, Caddy falls
back to the baked-in defaults documented in deploy/README.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

try:
    import requests
except ImportError:
    print(
        "ERROR: `requests` not installed. Run:\n"
        "    pip install requests\n"
        "or:\n"
        "    sudo apt install python3-requests",
        file=sys.stderr,
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

API_BASE = "https://api.vultr.com/v2"

# Vultr identifiers (looked up live via /v2/os on 2026-05-14):
#   region "ewr"  = Piscataway, NJ (New York metro)
#   region "lax"  = Los Angeles, CA
#   plan   "vc2-1c-2gb" = Cloud Compute Regular Performance, 1 vCPU / 2 GB / 50 GB, ~$6/mo
#   os_id  2284  = Ubuntu 24.04 LTS x64
# Note: os_id 2076 is Alpine Linux x64 in Vultr's catalog (not Ubuntu).
# The Apohara Aegis cloud-init script requires apt-get / Debian-family
# tooling, so we pin to the real Ubuntu 24.04 image (2284).
REGION = "ewr"
PLAN = "vc2-1c-2gb"
OS_ID = 2284

# Tag used for idempotency. Re-running the script with the same tag returns
# the existing instance instead of provisioning a duplicate.
TAG = "apohara-aegis-techex2026-demo"

# Hostname / label shown in the Vultr panel.
LABEL = "apohara-aegis-demo"
HOSTNAME = "aegis-demo"


# ---------------------------------------------------------------------------
# Vultr API helpers
# ---------------------------------------------------------------------------


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _api(
    method: str,
    path: str,
    api_key: str,
    *,
    json_body: Optional[dict] = None,
    expect_status: tuple[int, ...] = (200, 201, 202, 204),
) -> dict[str, Any]:
    """Call the Vultr API. Returns parsed JSON or empty dict on 204."""
    url = f"{API_BASE}{path}"
    resp = requests.request(
        method,
        url,
        headers=_auth_headers(api_key),
        data=json.dumps(json_body) if json_body is not None else None,
        timeout=30,
    )
    if resp.status_code not in expect_status:
        raise RuntimeError(
            f"Vultr API {method} {path} returned {resp.status_code}:\n"
            f"{resp.text}"
        )
    if resp.status_code == 204 or not resp.text:
        return {}
    return resp.json()


def find_instance_by_tag(api_key: str, tag: str) -> Optional[dict]:
    """Return the first instance carrying ``tag`` in its ``tags`` array, else None."""
    data = _api("GET", "/instances", api_key)
    for inst in data.get("instances", []):
        tags = inst.get("tags") or []
        if tag in tags:
            return inst
    return None


def _mask(secret: str) -> str:
    """Return a redacted preview of a secret for logging (first 4 + last 4)."""
    if not secret:
        return "<empty>"
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}...{secret[-4:]} ({len(secret)} chars)"


def load_user_data() -> str:
    """Read deploy/cloud-init.yaml and substitute operator env vars.

    Performs four placeholder substitutions on the raw YAML before
    returning it:

    1. ``AEGIS_SSH_PUBKEY_PLACEHOLDER``      -> $AEGIS_SSH_PUBKEY (required).
    2. ``AEGIS_JUDGE_USER_PLACEHOLDER``      -> $AEGIS_JUDGE_USER (optional, default empty).
    3. ``AEGIS_JUDGE_PASS_HASH_PLACEHOLDER`` -> $AEGIS_JUDGE_PASS_HASH (optional, default empty).
    4. ``GEMINI_API_KEY_PLACEHOLDER``        -> $GEMINI_API_KEY (required, Phase 3).

    Honesty contract: the SSH pubkey AND the Gemini API key are
    hard-required. If either is unset the function raises with an
    actionable error message BEFORE the caller hits the Vultr API —
    there is no silent fallback to root + password auth, and there is
    no silent fallback to a judge container with no AI Studio
    credentials (the live demo URL would otherwise serve a broken
    judge that always returns ``path="unavailable"`` and silently
    bypasses Gemini, defeating the whole Phase-3 stack).

    Neither secret is ever written to a file on the operator's host
    by this function. The substituted YAML is held in memory only and
    fed to ``base64.b64encode`` for the Vultr ``user_data`` POST body.
    """
    path = Path(__file__).resolve().parent / "cloud-init.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"cloud-init.yaml not found at {path}. "
            f"This script expects it next to itself."
        )

    raw = path.read_text(encoding="utf-8")

    pubkey = os.environ.get("AEGIS_SSH_PUBKEY", "").strip()
    if not pubkey:
        raise RuntimeError(
            "AEGIS_SSH_PUBKEY env var is not set. Phase-4 hardening "
            "requires an operator SSH public key — root login and "
            "password auth are disabled in the cloud-init template, so "
            "without a pubkey you would lock yourself out.\n"
            "Fix:\n"
            "    export AEGIS_SSH_PUBKEY=\"$(cat ~/.ssh/id_ed25519.pub)\"\n"
            "Then re-run this script."
        )

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        raise RuntimeError(
            "GEMINI_API_KEY env var is not set. Phase-3 deployment "
            "requires a real AI Studio key — the aegis-ui container "
            "needs it to call the Gemini-3.1-PRO judge in "
            "apohara_aegis/gemini_judge.py. Without a key the judge "
            "returns path='unavailable' and silently bypasses the "
            "Phase-2 calibration, defeating the live defense stack.\n"
            "Fix:\n"
            "    export GEMINI_API_KEY='<your-AI-Studio-key>'\n"
            "Then re-run this script."
        )
    # Honesty log: key length + first/last 4 only, never the value.
    print(f"  gemini : {_mask(gemini_key)}", file=sys.stderr)

    raw = raw.replace("AEGIS_SSH_PUBKEY_PLACEHOLDER", pubkey)
    raw = raw.replace(
        "AEGIS_JUDGE_USER_PLACEHOLDER",
        os.environ.get("AEGIS_JUDGE_USER", "").strip(),
    )
    raw = raw.replace(
        "AEGIS_JUDGE_PASS_HASH_PLACEHOLDER",
        os.environ.get("AEGIS_JUDGE_PASS_HASH", "").strip(),
    )
    raw = raw.replace("GEMINI_API_KEY_PLACEHOLDER", gemini_key)
    return raw


def create_instance(api_key: str) -> dict:
    """Create the demo instance. Returns the Vultr API response body."""
    import base64

    user_data_b64 = base64.b64encode(load_user_data().encode("utf-8")).decode("ascii")

    body = {
        "region": REGION,
        "plan": PLAN,
        "os_id": OS_ID,
        "label": LABEL,
        "hostname": HOSTNAME,
        "tags": [TAG],
        # cloud-init script (base64 of YAML). Vultr decodes server-side and
        # feeds it to cloud-init as user-data.
        "user_data": user_data_b64,
        # Auto-deny inbound except 22, 80, 443 — handled at OS firewall level
        # in cloud-init since Vultr's "firewall_group_id" is a separate API.
        "enable_ipv6": False,
        "backups": "disabled",
        "ddos_protection": False,
        "activation_email": False,
    }
    resp = _api("POST", "/instances", api_key, json_body=body)
    return resp.get("instance") or resp


def destroy_instance(api_key: str, instance_id: str) -> None:
    _api("DELETE", f"/instances/{instance_id}", api_key)


# ---------------------------------------------------------------------------
# Wait helpers
# ---------------------------------------------------------------------------


def wait_for_ip(api_key: str, instance_id: str, timeout_s: int = 300) -> str:
    """Poll until ``main_ip`` is non-empty (Vultr assigns it ~30-60 s in)."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        data = _api("GET", f"/instances/{instance_id}", api_key)
        inst = data.get("instance", {})
        ip = inst.get("main_ip", "")
        if ip and ip != "0.0.0.0":
            return ip
        time.sleep(8)
    raise TimeoutError(
        f"Instance {instance_id} did not receive an IP within {timeout_s}s"
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def cmd_provision(api_key: str) -> int:
    existing = find_instance_by_tag(api_key, TAG)
    if existing:
        ip = existing.get("main_ip", "")
        iid = existing.get("id", "?")
        status = existing.get("status", "?")
        print(f"Existing instance found (tag={TAG}):")
        print(f"  id     : {iid}")
        print(f"  ip     : {ip}")
        print(f"  status : {status}")
        if ip and ip != "0.0.0.0":
            print(f"  ssh    : ssh root@{ip}")
            print(f"  url    : https://{ip}.nip.io/")
            print(f"  audit  : https://{ip}.nip.io/audit")
            print(f"  lt     : https://{ip}.nip.io/lt/")
        print("(re-run with --destroy to tear down)")
        return 0

    print(f"Provisioning new instance (region={REGION}, plan={PLAN}, os_id={OS_ID})...")
    inst = create_instance(api_key)
    iid = inst.get("id", "")
    if not iid:
        print(f"ERROR: Vultr API did not return an instance id. Response: {inst}", file=sys.stderr)
        return 1

    print(f"  id     : {iid}")
    print("Waiting for IP assignment (typically 30-90 s)...")
    try:
        ip = wait_for_ip(api_key, iid)
    except TimeoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"Instance {iid} was created. Check the Vultr panel to recover.")
        return 1

    print(f"  ip     : {ip}")
    print(f"  ssh    : ssh root@{ip}")
    print(f"  url    : https://{ip}.nip.io/")
    print(f"  audit  : https://{ip}.nip.io/audit")
    print(f"  lt     : https://{ip}.nip.io/lt/")
    print()
    print("Cloud-init is now running on the box. It will:")
    print("  1. apt update + install docker, docker-compose, git, ufw")
    print("  2. git clone the apohara-aegis repo")
    print("  3. docker compose up -d (lobstertrap + aegis-ui + caddy)")
    print("  4. Caddy auto-provisions TLS via Let's Encrypt for *.nip.io")
    print("Expected total time: 3-6 minutes from provision to live URL.")
    return 0


def cmd_destroy(api_key: str) -> int:
    existing = find_instance_by_tag(api_key, TAG)
    if not existing:
        print(f"No instance tagged '{TAG}' found. Nothing to destroy.")
        return 0
    iid = existing.get("id", "")
    ip = existing.get("main_ip", "")
    print(f"Destroying instance {iid} (ip={ip}, tag={TAG})...")
    destroy_instance(api_key, iid)
    print("Destroyed.")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--destroy",
        action="store_true",
        help="Tear down the tagged instance instead of provisioning",
    )
    args = p.parse_args(argv)

    api_key = os.environ.get("VULTR_API_KEY", "").strip()
    if not api_key:
        print(
            "ERROR: VULTR_API_KEY env var is not set.\n"
            "Export it with:\n"
            "    export VULTR_API_KEY='<your-key>'\n"
            "Then re-run this script. The key is NEVER read from any file by design.",
            file=sys.stderr,
        )
        return 2

    if args.destroy:
        return cmd_destroy(api_key)
    return cmd_provision(api_key)


if __name__ == "__main__":
    sys.exit(main())
