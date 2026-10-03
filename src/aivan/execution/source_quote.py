"""Immutable source-quotation evidence reference, not a provider record ID."""
from __future__ import annotations

import hashlib
import json

from aivan.schemas.response import SupplierReply


def source_quote_reference(reply: SupplierReply) -> str:
    """Bind supplier identity, source message and actual terms to one revision.

    Arrival timestamps, parser confidence and random buyer-option IDs are not
    quote versions. Historical replies without message IDs still bind to their
    persisted canonical text and business terms; no provider ID is fabricated.
    """
    fields = ("project_id", "supplier_id", "candidate_id", "source_event_id", "raw_text",
              "unit_price", "currency", "moq", "capacity_per_day", "capacity_per_month",
              "lead_time_days", "material_availability", "qc_commitment", "logistics_note",
              "incoterms", "payment_terms")
    evidence = {name: getattr(reply, name) for name in fields}
    encoded = json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "aivan-source-quote-sha256-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
