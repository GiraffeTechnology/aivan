"""Semantic provenance tracking for RFQ fields.

Core product rule (PRD §2.3): AIVAN may *preserve* what a user said, but it may
not treat raw text as canonical authority. A canonical value (product,
destination, supplier, quality) is trustworthy only when it carries an
authoritative source. Raw evidence alone (``raw_text_only``) must trigger human
confirmation, never execution.

Field provenance is recorded on the requirement under
``requirement.extra["field_sources"]`` (written by the intake layer) and, when
the giraffe-language-skill was used, mirrored from
``requirement.extra["language_skill"]["field_sources"]``. This module reads those
markers; it never guesses canonical meaning itself.
"""

from __future__ import annotations

from typing import Any

from aivan.schemas.requirement import BuyerRequirement

# Sources that may back a canonical business fact. A local/small LLM's structured
# output is NOT here: model output is candidate evidence only and must be
# confirmed (by the language skill, a resolver, giraffe-db, or a human) before it
# can pass the execution readiness gate for product/destination.
AUTHORITATIVE_SOURCES = frozenset(
    {
        "language_skill",
        "operator_confirmed",
        "product_resolver",
        "location_resolver",
        "giraffe_db_product_reference",
        "giraffe_db_location_reference",
        "giraffe_db_supplier_registry",
    }
)

# Provisional sources: candidate evidence produced by a model. They are recorded
# for provenance and may be shown to an operator, but they never satisfy a
# readiness gate on their own — the action must be confirmation, not execution.
PROVISIONAL_SOURCES = frozenset({"llm_structured", "local_llm_candidate"})

# Sources that are NOT sufficient authority for a canonical fact.
NON_AUTHORITATIVE_SOURCES = frozenset({"raw_text_only", "deterministic", "", "none"})

RAW_TEXT_ONLY = "raw_text_only"


def field_sources(requirement: BuyerRequirement) -> dict[str, str]:
    """Return the merged {field -> source} map for a requirement.

    Language-skill provenance is authoritative and wins over locally recorded
    sources when both are present for the same field.
    """
    merged: dict[str, str] = {}
    extra = getattr(requirement, "extra", None) or {}

    local_sources = extra.get("field_sources")
    if isinstance(local_sources, dict):
        merged.update({k: str(v) for k, v in local_sources.items() if v})

    ls = extra.get("language_skill") or {}
    ls_sources = ls.get("field_sources") if isinstance(ls, dict) else None
    if isinstance(ls_sources, dict):
        # Language-skill field_sources are keyed by the trade_rfq.v1 field name;
        # translate the common ones onto BuyerRequirement attributes.
        rfq_to_attr = {
            "product_name": "product_type",
            "product_category": "category",
            "destination": "destination",
            "quantity": "quantity",
            "lead_time_days": "delivery_days",
            "quality_level": "quality_level",
        }
        for rfq_field, source in ls_sources.items():
            attr = rfq_to_attr.get(rfq_field, rfq_field)
            merged[attr] = "language_skill" if source else merged.get(attr, "language_skill")

    return merged


def source_of(requirement: BuyerRequirement, field: str) -> str:
    return field_sources(requirement).get(field, "")


def is_authoritative(requirement: BuyerRequirement, field: str) -> bool:
    """Whether ``field`` holds a canonical value from an authoritative source."""
    value = _field_value(requirement, field)
    if value in (None, "", []):
        return False
    return source_of(requirement, field) in AUTHORITATIVE_SOURCES


def is_provisional(requirement: BuyerRequirement, field: str) -> bool:
    """Whether ``field`` holds model-produced candidate evidence needing confirmation."""
    return source_of(requirement, field) in PROVISIONAL_SOURCES


def has_authoritative_product(requirement: BuyerRequirement) -> bool:
    return any(
        is_authoritative(requirement, f) for f in ("product_name", "product_type", "category")
    )


def has_authoritative_destination(requirement: BuyerRequirement) -> bool:
    return is_authoritative(requirement, "destination")


def mark_source(sources: dict[str, str], field: str, source: str) -> None:
    """Record ``field``'s provenance in a mutable source map."""
    if source:
        sources[field] = source


def _field_value(requirement: BuyerRequirement, field: str) -> Any:
    if hasattr(requirement, field):
        return getattr(requirement, field)
    extra = getattr(requirement, "extra", None) or {}
    return extra.get(field)
