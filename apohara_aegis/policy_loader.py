# SPDX-License-Identifier: Apache-2.0
"""Loader for the Lobster Trap policy YAML — used to expose perimeter rules
to a smolagents wrapper without forcing the engine to be installed.

The YAML schema mirrors `configs/lobstertrap_policy.yaml` at the repo root.
We don't *evaluate* the rules here (that's Lobster Trap's job, in Go); we
just load + summarise so the AegisGuard wrapper can echo the active policy
into its audit log."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PolicyDigest:
    """Read-only summary of a loaded Lobster Trap policy YAML."""

    name: str
    version: str
    default_action: str
    ingress_rule_count: int
    egress_rule_count: int
    deny_rules: tuple[str, ...] = field(default_factory=tuple)


def load_policy(path: str | Path) -> PolicyDigest:
    """Load and digest a Lobster Trap policy file.

    Raises ``FileNotFoundError`` if the path doesn't exist, and
    ``ValueError`` if the YAML is malformed. Returns a frozen
    ``PolicyDigest`` suitable for logging.

    Example::

        >>> d = load_policy("configs/lobstertrap_policy.yaml")
        >>> d.name
        'apohara-contextforge-techex'
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Policy file not found: {p}")

    try:
        raw: dict[str, Any] = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - structural test
        raise ValueError(f"Malformed YAML in {p}: {exc}") from exc

    ingress = raw.get("ingress_rules") or []
    egress = raw.get("egress_rules") or []
    deny_names = tuple(
        r.get("name", "<unnamed>")
        for r in (ingress + egress)
        if str(r.get("action", "")).upper() == "DENY"
    )

    return PolicyDigest(
        name=str(raw.get("policy_name", "<unnamed>")),
        version=str(raw.get("version", "0.0")),
        default_action=str(raw.get("default_action", "ALLOW")).upper(),
        ingress_rule_count=len(ingress),
        egress_rule_count=len(egress),
        deny_rules=deny_names,
    )
