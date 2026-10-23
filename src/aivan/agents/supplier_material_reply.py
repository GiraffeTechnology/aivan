"""Conservative English supplier declarations, not inferred material facts."""
from __future__ import annotations

from copy import deepcopy
import math
import re

_NUMBER = r"(\d+(?:\.\d+)?|\.\d+)"
_STATUSES = (
    "in_stock", "reserved_stock", "partial_stock", "supplier_confirmation_required",
    "not_available", "substitute_material_required", "unknown",
)
_MODES = ("in_house_manufacturer", "factory_without_stock", "trader", "broker", "hybrid", "unknown")
_LABELED = (
    ("material_availability_status", r"(?:material availability(?: status)?|raw material status)", "status"),
    ("supplier_execution_mode", r"(?:supplier )?execution mode", "mode"),
    ("raw_material_lead_time_estimate_days", r"raw material lead time(?: estimate)?", "days"),
    ("material_confirmation_days", r"material (?:supplier )?confirmation time", "days"),
    ("material_lock_validity_days", r"material lock validity", "days"),
    ("material_lock_required", r"material lock required", "bool"),
    ("material_can_be_locked", r"(?:can material be locked|material can be locked)", "bool"),
    ("in_house_manufacturing", r"(?:do you )?manufacture in.house", "bool"),
    ("substitute_material_needed", r"(?:is )?substitute material (?:needed|required)", "bool"),
    ("substitute_price_effect", r"substitute material price effect", "text"),
    ("substitute_quality_effect", r"substitute material quality effect", "text"),
    ("substitute_lead_time_effect", r"substitute material lead time effect", "text"),
)
_SENTENCES = {
    "we manufacture in-house": ("in_house_manufacturing", True),
    "we do not manufacture in-house": ("in_house_manufacturing", False),
    "we have raw material in stock": ("material_availability_status", "in_stock"),
    "we have partial raw material stock": ("material_availability_status", "partial_stock"),
    "we need to confirm with our material supplier": (
        "material_availability_status", "supplier_confirmation_required"),
    "material can be locked": ("material_can_be_locked", True),
    "material cannot be locked": ("material_can_be_locked", False),
    "substitute material is needed": ("substitute_material_needed", True),
    "substitute material is not needed": ("substitute_material_needed", False),
}
_FACTOR_FIELDS = {
    "supplier_execution_mode": "supplier_execution",
    "material_availability_status": "material",
    "raw_material_lead_time_estimate_days": "material",
    "material_lock_required": "material",
    "material_lock_validity_days": "material",
}


class SupplierMaterialContextError(ValueError):
    """A material declaration conflicts with the supplied typed context."""


def _value(text, kind):
    if kind == "status":
        value = text.lower().replace(" ", "_")
        return value if value in _STATUSES else None
    if kind == "mode":
        value = text.lower().replace(" ", "_")
        return value if value in _MODES else None
    if kind == "bool":
        return {"yes": True, "true": True, "no": False, "false": False}.get(text.lower())
    if kind == "days":
        match = re.fullmatch(_NUMBER + r"\s+days?", text, re.IGNORECASE)
        if match:
            number = float(match.group(1))
            return number if math.isfinite(number) else None
        return None
    return text if len(text) <= 500 else None


def parse_material_declarations(raw_text: str) -> dict:
    """Require an entire explicit clause, retaining its actual source text.

    Conditional, negated, mixed or range-valued statements do not match a
    positive declaration. Multiple different values remain a visible conflict.
    This parser operates after canonical English normalization; it is not OCR
    or translation and does not use model output or a guessed confidence score.
    """
    seen: dict[str, list[dict]] = {}
    for line in re.split(r"[;\n]", raw_text):
        original = line.strip()
        clause = original.rstrip(".! ")
        found = _SENTENCES.get(clause.lower())
        if found is not None:
            seen.setdefault(found[0], []).append({"value": found[1], "source_text": original})
        for field, label, kind in _LABELED:
            match = re.fullmatch(label + r"\s*[:=]\s*(.+)", clause, re.IGNORECASE)
            if match is None:
                continue
            value = _value(match.group(1).strip(), kind)
            if value is not None:
                seen.setdefault(field, []).append({"value": value, "source_text": original})
    fields = {}
    conflicts = {}
    for field, evidence in seen.items():
        if any(row["value"] != evidence[0]["value"] for row in evidence[1:]):
            conflicts[field] = evidence
        else:
            fields[field] = evidence[0]
    return {"schema_version": "aivan.supplier-material-declarations.v1",
            "source": "supplier_declaration_not_verified_inventory",
            "fields": fields, "conflicts": conflicts}


def material_context(context: dict | None, reply) -> dict:
    """Map exact provider fields only, without altering existing facts or IDs."""
    result = deepcopy(context or {})
    if reply is None:
        return result
    # Re-derive from the canonical message. A model/client dict is not evidence.
    declaration = parse_material_declarations(reply.raw_text)
    fields = declaration["fields"]
    if any(field in _FACTOR_FIELDS for field in declaration["conflicts"]):
        raise SupplierMaterialContextError("GLTG_SUPPLIER_MATERIAL_DECLARATION_CONFLICT")
    factors = result.setdefault("trade_processing_factors", {})
    if not isinstance(factors, dict):
        raise SupplierMaterialContextError("GLTG_INPUT_EVIDENCE_INVALID")
    for field, group in _FACTOR_FIELDS.items():
        if field not in fields:
            continue
        target = factors.setdefault(group, {})
        if not isinstance(target, dict):
            raise SupplierMaterialContextError("GLTG_INPUT_EVIDENCE_INVALID")
        value = fields[field]["value"]
        if target.get(field) is not None and target[field] != value:
            raise SupplierMaterialContextError("GLTG_SUPPLIER_MATERIAL_CONTEXT_CONFLICT")
        target[field] = value
    # Can-lock is not lock-required, no-stock is not not-available, and neither
    # substitute-needed nor in-house declarations become numeric probabilities.
    # Message identity is not a private provider observation primary key.
    return result
