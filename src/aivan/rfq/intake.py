"""Centralized RFQ intake.

Converts an inbound message into an RFQ evidence + canonical requirement packet
with per-field provenance. This module performs NO execution — it only
structures the message (via the requirement agent, which uses the language skill
/ local model / deterministic extraction) and exposes a canonical packet with
authoritative-source markers and a validation status derived from the readiness
gate.
"""

from __future__ import annotations

from aivan.agents.requirement_agent import structure_customer_requirement_with_llm
from aivan.execution.safety import evaluate_requirement_readiness
from aivan.rfq import semantic_sources
from aivan.schemas.requirement import BuyerRequirement


def structure_rfq(
    raw_text: str,
    attachments: list | None = None,
    existing_requirement: BuyerRequirement | None = None,
    project_id: str = "",
    source_channel: str | None = None,
) -> BuyerRequirement:
    """Structure an inbound RFQ message into a provenance-tagged requirement."""
    return structure_customer_requirement_with_llm(
        raw_text=raw_text,
        attachments=attachments,
        existing_requirement=existing_requirement,
        project_id=project_id,
        source_channel=source_channel,
    )


def to_canonical_packet(requirement: BuyerRequirement) -> dict:
    """Produce the internal canonical RFQ packet (PRD §5) for a requirement."""
    sources = semantic_sources.field_sources(requirement)
    extra = requirement.extra or {}
    gate = evaluate_requirement_readiness(requirement)

    return {
        "raw_text": requirement.raw_text,
        "source_language": extra.get("source_language") or requirement.language,
        "canonical_language": "en",
        "quantity": requirement.quantity,
        "quantity_unit": requirement.quantity_unit,
        "product_raw": extra.get("product_raw", ""),
        "product_name": requirement.product_type,
        "product_category": requirement.category,
        "product_modifier": extra.get("product_modifier", []),
        "product_source": sources.get("product_type") or sources.get("category") or semantic_sources.RAW_TEXT_ONLY,
        "quality_raw": extra.get("quality_raw", ""),
        "quality_level": extra.get("quality_level", ""),
        "quality_source": sources.get("quality_level", ""),
        "destination_raw": extra.get("destination_raw", ""),
        "destination": requirement.destination or None,
        "destination_source": sources.get("destination") or semantic_sources.RAW_TEXT_ONLY,
        "lead_time_days": requirement.delivery_days,
        "intent": extra.get("intent", ""),
        "validation_status": "valid" if gate.ready else "needs_confirmation",
        "missing_fields": gate.missing_fields,
    }
