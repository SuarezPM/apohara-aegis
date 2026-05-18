# SPDX-License-Identifier: Apache-2.0
"""
Tests for templates.py industry configuration templates.

Apohara PROBANT Fusion Sprint (2026-05-18) — US-75.

Coverage:
  - Exactly 6 templates present
  - Each template satisfies minimum field cardinality
  - DJL rule IDs match expected regex format (cross-resolution deferred to US-86)
  - Mandatory incident codes resolve to the taxonomy DEFINITIONS dict
  - Regulatory ref strings are non-empty and distinct per template
"""
from __future__ import annotations

import re

import pytest

from apohara_aegis.templates import TEMPLATES, IndustryTemplate
from apohara_aegis.taxonomy import DEFINITIONS as TAXONOMY, IncidentCode


# ---------------------------------------------------------------------------
# AC3-1 — exactly 6 templates
# ---------------------------------------------------------------------------


def test_exactly_6_templates() -> None:
    assert len(TEMPLATES) == 6, (
        f"Expected 6 industry templates, found {len(TEMPLATES)}: {list(TEMPLATES)}"
    )


def test_template_keys_are_lowercase_strings() -> None:
    for key in TEMPLATES:
        assert isinstance(key, str) and key == key.lower(), (
            f"Template key '{key}' must be a lowercase string."
        )


# ---------------------------------------------------------------------------
# AC3-2 — each template has required fields with minimum cardinality
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", list(TEMPLATES.keys()))
def test_each_template_has_required_fields(key: str) -> None:
    tpl = TEMPLATES[key]

    assert isinstance(tpl, IndustryTemplate)
    assert isinstance(tpl.name, str) and tpl.name, f"{key}: name must be a non-empty string"
    assert isinstance(tpl.description, str) and tpl.description, (
        f"{key}: description must be a non-empty string"
    )

    # Cardinality minimums from AC1
    assert len(tpl.regulatory_refs) >= 3, (
        f"{key}: ≥3 regulatory_refs required, found {len(tpl.regulatory_refs)}"
    )
    assert len(tpl.default_djl_rule_subset) >= 5, (
        f"{key}: ≥5 default_djl_rule_subset entries required, "
        f"found {len(tpl.default_djl_rule_subset)}"
    )
    assert len(tpl.mandatory_incident_codes) >= 1, (
        f"{key}: ≥1 mandatory_incident_codes required, "
        f"found {len(tpl.mandatory_incident_codes)}"
    )
    assert len(tpl.default_compliance_report_sections) >= 2, (
        f"{key}: ≥2 default_compliance_report_sections required, "
        f"found {len(tpl.default_compliance_report_sections)}"
    )


# ---------------------------------------------------------------------------
# AC3-3 — DJL rule IDs match expected regex format (format-only; US-86 resolves)
# ---------------------------------------------------------------------------

_DJL_ID_RE = re.compile(r"^DJL-[A-Z]+-\d{3}$")


@pytest.mark.parametrize("key", list(TEMPLATES.keys()))
def test_djl_rule_subset_format_only(key: str) -> None:
    tpl = TEMPLATES[key]
    for rule_id in tpl.default_djl_rule_subset:
        assert _DJL_ID_RE.match(rule_id), (
            f"{key}: DJL rule ID '{rule_id}' does not match pattern DJL-[A-Z]+-NNN"
        )


# ---------------------------------------------------------------------------
# AC3-4 — mandatory incident codes resolve to taxonomy DEFINITIONS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", list(TEMPLATES.keys()))
def test_mandatory_incident_codes_resolve_to_taxonomy(key: str) -> None:
    tpl = TEMPLATES[key]
    for code in tpl.mandatory_incident_codes:
        assert isinstance(code, IncidentCode), (
            f"{key}: {code!r} is not an IncidentCode instance"
        )
        assert code in TAXONOMY, (
            f"{key}: IncidentCode '{code}' not found in taxonomy.DEFINITIONS"
        )


# ---------------------------------------------------------------------------
# AC3-5 — regulatory refs are non-empty strings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", list(TEMPLATES.keys()))
def test_regulatory_refs_format(key: str) -> None:
    tpl = TEMPLATES[key]
    for ref in tpl.regulatory_refs:
        assert isinstance(ref, str) and ref.strip(), (
            f"{key}: regulatory ref must be a non-empty string, got {ref!r}"
        )
    # All refs within a template must be distinct
    assert len(set(tpl.regulatory_refs)) == len(tpl.regulatory_refs), (
        f"{key}: regulatory_refs contains duplicates"
    )


# ---------------------------------------------------------------------------
# Structural / type checks
# ---------------------------------------------------------------------------


def test_templates_are_frozen() -> None:
    """IndustryTemplate is frozen=True; direct attribute assignment must raise FrozenInstanceError."""
    tpl = TEMPLATES["finance"]
    with pytest.raises(Exception):
        # dataclasses.FrozenInstanceError is a subclass of AttributeError in CPython
        tpl.name = "mutated"  # type: ignore[misc]


def test_all_expected_verticals_present() -> None:
    expected_keys = {"finance", "healthcare", "government", "retail", "manufacturing", "energy"}
    assert set(TEMPLATES.keys()) == expected_keys, (
        f"Unexpected or missing template keys: {set(TEMPLATES.keys()) ^ expected_keys}"
    )
