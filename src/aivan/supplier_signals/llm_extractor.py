"""LLM extraction layer: free-text supplier reply -> structured ExtractionResult.

Call strategy (local-first): Ollama local model first, DashScope Qwen fallback
on timeout / connection error / HTTP 5xx. A 4xx is a bad request (fix the
prompt, not the client) and does NOT trigger fallback. The extractor never
raises -- it always returns an ExtractionResult, possibly all-null.
"""

from __future__ import annotations

import re
from datetime import date

from aivan.llm.base import LLMProvider
from aivan.supplier_signals.models import EnquiryContext, ExtractionResult, LoadLevel

SYSTEM_PROMPT = (
    "You are an assistant that extracts structured supply chain data from "
    "supplier replies. Extract exactly the fields requested. If a field cannot "
    "be determined from the text, return null. Do not invent data. Return valid "
    "JSON only, no explanation."
)

_USER_TEMPLATE = """Supplier reply:
\"\"\"
{reply_text}
\"\"\"

Enquiry context:
- Order quantity: {quantity} units
- Product type: {product_type}
- Enquiry date: {enquiry_date}

Extract the following fields and return as JSON:
{{
  "available_capacity_per_day": <integer units/day or null>,
  "earliest_available_date": <ISO date YYYY-MM-DD or null>,
  "load_level": <"LIGHT" | "MODERATE" | "HEAVY" | null>,
  "extraction_confidence": <0.0-1.0, your confidence in the extraction>,
  "extraction_notes": <one sentence explaining any uncertainty>
}}

Rules:
- available_capacity_per_day: extract stated daily output capacity for NEW orders only;
  if a range is given, use the conservative LOWER bound
- earliest_available_date: the earliest date supplier can START production
- load_level: LIGHT (<50% capacity used), MODERATE (50-80%), HEAVY (>80%)
- If load_level is implied by available_capacity_per_day relative to historical
  capacity in context, derive it; otherwise use stated language cues
- extraction_confidence: lower if reply is ambiguous or off-topic"""

# Cost guard: cap the reply we send (~1 token/char for CJK). Keeps input small.
_MAX_REPLY_CHARS = 1200
# Below this confidence we discard all extracted fields (never fabricate).
_MIN_CONFIDENCE = 0.5
_TASK = "supplier_state_extraction"


def build_user_prompt(reply_text: str, context: EnquiryContext) -> str:
    clipped = (reply_text or "")[:_MAX_REPLY_CHARS]
    return _USER_TEMPLATE.format(
        reply_text=clipped,
        quantity=context.quantity,
        product_type=context.product_type,
        enquiry_date=context.enquiry_date.isoformat(),
    )


def _is_4xx(exc: Exception) -> bool:
    """True for an HTTP 4xx status error (do not fall back on these)."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return isinstance(status, int) and 400 <= status < 500


def _coerce_capacity(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    if isinstance(value, str):
        # A range like "1000-1500" / "1000~1500件" -> conservative lower bound.
        nums = [int(n) for n in re.findall(r"\d+", value)]
        return min(nums) if nums else None
    return None


def _coerce_date(value) -> date | None:
    if not value or not isinstance(value, str):
        return None
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _coerce_load(value) -> LoadLevel:
    if isinstance(value, str):
        try:
            return LoadLevel(value.strip().upper())
        except ValueError:
            return LoadLevel.UNKNOWN
    return LoadLevel.UNKNOWN


def _coerce_confidence(value) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, conf))


def parse_extraction(data: dict, provider: str) -> ExtractionResult:
    """Validate and coerce a raw JSON dict into an ExtractionResult.

    Confidence below 0.5 voids every extracted field so a low-confidence reply
    never fabricates capacity/date/load values.
    """
    if not isinstance(data, dict):
        return ExtractionResult.empty(notes="non-dict LLM response", provider=provider)

    confidence = _coerce_confidence(data.get("extraction_confidence"))
    notes = str(data.get("extraction_notes") or "")

    if confidence < _MIN_CONFIDENCE:
        result = ExtractionResult.empty(notes=notes or "confidence below threshold", provider=provider)
        result.extraction_confidence = confidence
        return result

    return ExtractionResult(
        available_capacity_per_day=_coerce_capacity(data.get("available_capacity_per_day")),
        earliest_available_date=_coerce_date(data.get("earliest_available_date")),
        load_level=_coerce_load(data.get("load_level")),
        extraction_confidence=confidence,
        extraction_notes=notes,
        provider=provider,
    )


def extract_supplier_state(
    reply_text: str,
    context: EnquiryContext,
    primary: LLMProvider | None = None,
    fallback: LLMProvider | None = None,
    temperature: float = 0.0,
) -> ExtractionResult:
    """Extract supplier-state fields, Ollama-first with DashScope Qwen fallback."""
    if primary is None:
        from aivan.llm.providers.ollama_provider import OllamaProvider

        primary = OllamaProvider()
    if fallback is None:
        from aivan.llm.providers.qwen_provider import QwenProvider

        fallback = QwenProvider()

    user_prompt = build_user_prompt(reply_text, context)

    try:
        data = primary.complete_json(_TASK, SYSTEM_PROMPT, user_prompt, {}, temperature)
        return parse_extraction(data, getattr(primary, "provider_name", "primary"))
    except Exception as exc:
        if _is_4xx(exc):
            # Bad request: do not retry on the hosted model -- surface as empty.
            return ExtractionResult.empty(
                notes=f"primary 4xx: {exc}", provider=getattr(primary, "provider_name", "primary")
            )

    try:
        data = fallback.complete_json(_TASK, SYSTEM_PROMPT, user_prompt, {}, temperature)
        return parse_extraction(data, getattr(fallback, "provider_name", "fallback"))
    except Exception as exc:
        return ExtractionResult.empty(
            notes=f"primary+fallback failed: {exc}",
            provider=getattr(fallback, "provider_name", "fallback"),
        )
