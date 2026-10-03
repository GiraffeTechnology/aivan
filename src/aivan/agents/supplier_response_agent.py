from __future__ import annotations
from aivan.schemas.response import SupplierReply
from aivan.llm.gateway import llm_complete_json
from aivan.llm.prompts import SUPPLIER_RESPONSE_PARSING_SYSTEM
from aivan.utils.time_utils import utcnow_iso

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
            safe_data = {k: v for k, v in result.items() if k in SupplierReply.model_fields and k not in ("project_id", "supplier_id", "candidate_id", "raw_text", "source_event_id")}
            # An omitted currency is missing evidence, not an implicit USD quote.
            safe_data.setdefault("currency", "")
            if not safe_data["currency"]:
                missing = list(safe_data.get("missing_info") or [])
                if "currency" not in missing:
                    missing.append("currency")
                safe_data["missing_info"] = missing
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
    # Bind fallback facts to their business clause, not unrelated freight,
    # payment or offer-validity facts elsewhere in the same message.
    clauses = re.split(r';|\n|\.(?=\s|$)|,\s+(?=[A-Za-z])', raw_text)
    currency_codes = (
        "USD|EUR|GBP|CNY|JPY|HKD|CAD|AUD|CHF|NZD|SGD|KRW|INR|BRL|MXN|ZAR|"
        "SEK|NOK|DKK|PLN|THB|TWD|VND|IDR|AED|SAR|TRY|RUB"
    )
    amount = r'(\d+(?:\.\d+)?)(?![\w.,])'
    price_pattern = rf'(?:\bprice\b|\b(?:{currency_codes})\b|单价|¥|\$)\s*[:=]?\s*{amount}'
    price_clauses = []
    for clause in clauses:
        quoted_amount = re.search(price_pattern, clause, re.IGNORECASE)
        if quoted_amount and not re.search(
            r'\b(?:freight|shipping|sample|tooling|packaging|fee)\b',
            clause[:quoted_amount.start()], re.IGNORECASE,
        ):
            price_clauses.append(clause)
    named_prices = [clause for clause in price_clauses if re.search(r'\bprice\b|单价', clause, re.IGNORECASE)]
    price_clause = next(iter(named_prices or price_clauses), "")
    price_match = re.search(price_pattern, price_clause, re.IGNORECASE)
    unit_price = float(price_match.group(1)) if price_match else None
    explicit_currencies = {
        code.upper() for code in re.findall(rf'\b(?:{currency_codes})\b', price_clause, re.IGNORECASE)
    }
    currency = next(iter(explicit_currencies)) if len(explicit_currencies) == 1 else ""

    lead_clauses = [clause for clause in clauses if re.search(
        r'\b(?:lead\s*time|delivery|production)\b|交期|交货|生产', clause, re.IGNORECASE)]
    lead_values = {float(value) for clause in lead_clauses for value in re.findall(
        r'(?<![\w.,\-])(\d+(?:\.\d+)?|\.\d+)\s*(?:days?\b|天)', clause, re.IGNORECASE)}
    lead_time = next(iter(lead_values)) if len(lead_values) == 1 else None

    moq_match = re.search(r'moq[:\s]*(\d[\d,]*)', text_lower)
    moq = int(moq_match.group(1).replace(",", "")) if moq_match else None

    return SupplierReply(
        project_id=project_id,
        supplier_id=supplier_id,
        candidate_id=candidate_id,
        raw_text=raw_text,
        channel=channel,
        unit_price=unit_price,
        currency=currency,
        moq=moq,
        lead_time_days=lead_time,
        missing_info=[] if currency else ["currency"],
        confidence=0.4,
        received_at=utcnow_iso(),
    )

def draft_supplier_followup(
    original_reply: SupplierReply,
    missing_info: list[str] | None = None,
) -> str:
    """Draft a follow-up question to a supplier for missing information."""
    missing = missing_info or original_reply.missing_info or ["Please provide lead time, capacity, and payment terms."]
    questions = "\n".join(f"{i+1}. {q}" for i, q in enumerate(missing))
    return f"""Thank you for your reply.

We need a few more details to proceed:

{questions}

Please reply at your earliest convenience.

Best regards."""
