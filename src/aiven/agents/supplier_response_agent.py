from __future__ import annotations
from aiven.schemas.response import SupplierReply
from aiven.llm.gateway import llm_complete_json
from aiven.llm.prompts import SUPPLIER_RESPONSE_PARSING_SYSTEM
from aiven.utils.time_utils import utcnow_iso

def parse_supplier_reply(
    raw_text: str,
    project_id: str,
    supplier_id: str = "",
    candidate_id: str = "",
    channel: str = "",
) -> SupplierReply:
    """Parse a supplier reply message using LLM with deterministic fallback."""
    import re

    user_prompt = f"""Supplier message:
{raw_text}

Extract: unit_price, currency, moq, capacity_per_day, capacity_per_month, lead_time_days, material_availability, qc_commitment, logistics_note, incoterms, payment_terms, risks (list), missing_info (list), confidence."""

    try:
        result = llm_complete_json("supplier_response_parsing", SUPPLIER_RESPONSE_PARSING_SYSTEM, user_prompt)
        if result.get("confidence", 0) > 0.4:
            safe_data = {k: v for k, v in result.items() if k in SupplierReply.model_fields and k not in ("project_id", "supplier_id", "candidate_id", "raw_text")}
            return SupplierReply(
                project_id=project_id,
                supplier_id=supplier_id,
                candidate_id=candidate_id,
                raw_text=raw_text,
                channel=channel,
                received_at=utcnow_iso(),
                **safe_data,
            )
    except Exception:
        pass

    text_lower = raw_text.lower()
    price_match = re.search(r'(?:usd|price|单价|¥|\$)\s*([\d.]+)', text_lower)
    unit_price = float(price_match.group(1)) if price_match else None

    day_match = re.search(r'(\d+)\s*(?:days?|天)', text_lower)
    lead_time = int(day_match.group(1)) if day_match else None

    moq_match = re.search(r'moq[:\s]*(\d[\d,]*)', text_lower)
    moq = int(moq_match.group(1).replace(",", "")) if moq_match else None

    return SupplierReply(
        project_id=project_id,
        supplier_id=supplier_id,
        candidate_id=candidate_id,
        raw_text=raw_text,
        channel=channel,
        unit_price=unit_price,
        currency="USD",
        moq=moq,
        lead_time_days=lead_time,
        confidence=0.4,
        received_at=utcnow_iso(),
    )

def draft_supplier_followup(
    original_reply: SupplierReply,
    missing_info: list[str] = None,
) -> str:
    """Draft a follow-up question to a supplier for missing information."""
    missing = missing_info or original_reply.missing_info or ["Please provide lead time, capacity, and payment terms."]
    questions = "\n".join(f"{i+1}. {q}" for i, q in enumerate(missing))
    return f"""Thank you for your reply.

We need a few more details to proceed:

{questions}

Please reply at your earliest convenience.

Best regards."""
