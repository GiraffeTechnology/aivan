"""RFQ intake canonicalization via the giraffe-language-skill service.

This is the AIVAN-side orchestration on top of :mod:`language_skill_client`. It
calls ``/v1/inbound/normalize`` then ``/v1/structure/rfq`` and overlays the
service's deterministic business facts onto a :class:`BuyerRequirement`,
recording the full provenance chain in ``requirement.extra["language_skill"]``.

Fail-soft contract (default): if the service is disabled or unavailable, these
helpers return ``None`` / leave the requirement untouched so the caller keeps
the raw message and does not hallucinate missing fields. Set
``AIVAN_LANGUAGE_SKILL_FAIL_SOFT=false`` to surface failures as exceptions.
"""

from __future__ import annotations

from typing import Any

from aivan.integrations.language_skill_client import (
    LanguageSkillClient,
    is_enabled,
    is_fail_soft,
)
from aivan.schemas.requirement import BuyerRequirement


class LanguageSkillUnavailable(RuntimeError):
    """Raised (only when fail-soft is disabled) when the service call fails."""


# Map trade_rfq.v1 structured field -> BuyerRequirement attribute. Fields not
# listed here are preserved under requirement.extra["language_skill"].
_RFQ_TO_REQUIREMENT = {
    "quantity": "quantity",
    "quantity_unit": "quantity_unit",
    "product_name": "product_type",
    "product_category": "category",
    "destination": "destination",
    "lead_time_days": "delivery_days",
}


def canonicalize_rfq(
    raw_text: str,
    source_channel: str | None = None,
    tenant_id: str = "default",
    sender_role: str = "buyer",
    client: LanguageSkillClient | None = None,
) -> dict[str, Any] | None:
    """Normalize + structure an inbound RFQ message.

    Returns ``{"normalize": <dict>, "structure": <dict|None>}`` on success, or
    ``None`` when the service is disabled or (in fail-soft mode) unavailable.
    """
    if not is_enabled():
        return None

    client = client or LanguageSkillClient()

    norm = client.normalize(
        source_text=raw_text,
        source_language="auto",
        canonical_language="en",
        domain_hint="trade_rfq",
        source_channel=source_channel,
        conversation_context={"tenant_id": tenant_id, "sender_role": sender_role},
    )
    if not norm.ok or norm.data is None:
        if not is_fail_soft():
            raise LanguageSkillUnavailable(norm.error or "normalize failed")
        return None

    normalize_data = norm.data
    struct = client.structure_rfq(
        raw_text=raw_text,
        canonical_text=normalize_data.get("canonical_text"),
        field_evidence=normalize_data.get("field_evidence"),
    )
    if not struct.ok or struct.data is None:
        if not is_fail_soft():
            raise LanguageSkillUnavailable(struct.error or "structure/rfq failed")
        # Normalization still succeeded; return it without structured fields.
        return {"normalize": normalize_data, "structure": None}

    return {"normalize": normalize_data, "structure": struct.data}


def apply_to_requirement(req: BuyerRequirement, canon: dict[str, Any]) -> BuyerRequirement:
    """Overlay canonicalization results onto ``req`` and record provenance.

    The language skill's deterministic extraction is authoritative for the
    explicit business facts it returns; a non-null service value overwrites the
    corresponding requirement field. Values the service does not provide are
    left as-is (never nulled out).
    """
    normalize_data = canon.get("normalize") or {}
    structure_data = canon.get("structure")

    detected = (normalize_data.get("language") or {}).get("detected")
    if detected:
        req.language = detected

    ls_meta: dict[str, Any] = {
        "raw_text": normalize_data.get("raw_text"),
        "source_language": detected,
        "canonical_text": normalize_data.get("canonical_text"),
        "translation": normalize_data.get("translation"),
        "field_evidence": normalize_data.get("field_evidence"),
        "warnings": normalize_data.get("warnings", []),
    }

    if structure_data:
        structured = structure_data.get("structured") or {}
        _overlay_fields(req, structured, structure_data.get("confidence_score"))
        _record_destination_provenance(
            req,
            structured,
            normalize_data.get("field_evidence") or {},
            structure_data.get("confidence_score"),
        )
        ls_meta.update(
            {
                "schema": structure_data.get("schema"),
                "structured": structured,
                "validation_status": structure_data.get("validation_status"),
                "missing_fields": structure_data.get("missing_fields", []),
                "confidence_score": structure_data.get("confidence_score"),
                "field_sources": structure_data.get("field_sources", {}),
            }
        )

    req.extra["language_skill"] = ls_meta
    return req


def _record_destination_provenance(
    req: BuyerRequirement,
    structured: dict[str, Any],
    field_evidence: dict[str, Any],
    confidence: Any,
) -> None:
    """Mark the canonical destination as sourced from the language skill.

    AIVAN owns no destination dictionary, so provenance must make it auditable
    that a canonical destination came from giraffe-language-skill (not an
    AIVAN-local alias table). Only recorded when the skill actually resolved one.
    """
    canonical = structured.get("destination")
    if canonical is None or (isinstance(canonical, str) and not canonical.strip()):
        return

    evidence = field_evidence.get("destination") if isinstance(field_evidence, dict) else None
    raw = None
    dest_confidence: Any = confidence
    if isinstance(evidence, dict):
        raw = evidence.get("raw_text") or evidence.get("span")
        if isinstance(evidence.get("confidence"), (int, float)):
            dest_confidence = evidence["confidence"]

    req.extra["destination_raw"] = raw
    req.extra["destination_canonical"] = canonical
    req.extra["destination_source"] = "language_skill"
    if isinstance(dest_confidence, (int, float)):
        req.extra["destination_confidence"] = float(dest_confidence)


def _overlay_fields(req: BuyerRequirement, structured: dict[str, Any], confidence: Any) -> None:
    for src_field, req_attr in _RFQ_TO_REQUIREMENT.items():
        value = structured.get(src_field)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        setattr(req, req_attr, value)

    # Preserve extra domain signals that have no dedicated requirement field.
    for extra_field in ("quality_level", "product_modifier", "intent"):
        value = structured.get(extra_field)
        if value is not None:
            req.extra[extra_field] = value

    if isinstance(confidence, (int, float)):
        req.confidence = max(req.confidence, float(confidence))
