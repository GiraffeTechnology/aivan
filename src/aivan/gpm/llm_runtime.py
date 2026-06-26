"""GPM LLM runtime — quote analysis with Qwen output stability.

GPM-004: reason field is a machine-readable code, never a human-readable string.
GPM-005: Qwen output validated against required keys; retries on schema failure.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

REQUIRED_OUTPUT_KEYS = {
    "human_approval_required",
    "recommendation",
    "quote_position",
    "confidence",
}

VALID_RECOMMENDATIONS = {
    "accept",
    "negotiate",
    "reject",
    "request_more_info",
    "human_review_required",
}

VALID_QUOTE_POSITIONS = {
    "below_market",
    "within_low_range",
    "within_mid_range",
    "within_high_range",
    "above_market",
    "insufficient_data",
}

VALID_CONFIDENCES = {"high", "medium", "low"}

# GPM-004: HTTP status → machine-readable reason code
_HTTP_STATUS_TO_REASON: dict[int, str] = {
    401: "invalid_token",
    403: "forbidden",
    429: "rate_limit_exceeded",
    500: "provider_error",
    503: "provider_unavailable",
}

PROMPT_JSON_TAIL = """

=== OUTPUT FORMAT (STRICT) ===
Return ONLY a valid JSON object. No markdown fences, no explanation, no preamble.
ALL of the following keys are required:
  "human_approval_required": true  (always)
  "recommendation": "accept" | "negotiate" | "reject" | "request_more_info" | "human_review_required"
  "quote_position": "below_market" | "within_low_range" | "within_mid_range" | "within_high_range" | "above_market" | "insufficient_data"
  "confidence": "high" | "medium" | "low"
  "reasoning": "<brief string>"

Omitting any key is a fatal error. Return complete JSON only.
"""


class QwenOutputValidationError(Exception):
    pass


def _make_unavailable_response(http_status: int) -> dict:
    """GPM-004: map HTTP status to machine-readable reason code."""
    reason_code = _HTTP_STATUS_TO_REASON.get(http_status, "provider_error")
    return {
        "runtime_status": "unavailable",
        "reason": reason_code,
        "operator_action_required": True,
        "safe_message": (
            f"LLM runtime unavailable (reason={reason_code}). "
            "Check GPM_LLM_API_KEY and provider status."
        ),
    }


def _build_quote_analysis_prompt(sku: str, supplier_quote: float, currency: str, quantity: Optional[int]) -> str:
    lines = [
        f"Analyze this supplier quote and provide GPM guidance.",
        f"",
        f"SKU: {sku}",
        f"Supplier Quote: {supplier_quote} {currency}",
    ]
    if quantity:
        lines.append(f"Quantity: {quantity}")
    lines.append(PROMPT_JSON_TAIL)
    return "\n".join(lines)


def _validate_output(result: dict) -> dict:
    """GPM-005: validate that all required keys are present and values are valid."""
    missing = REQUIRED_OUTPUT_KEYS - result.keys()
    if missing:
        raise QwenOutputValidationError(f"Missing required keys: {missing}")
    if result.get("recommendation") not in VALID_RECOMMENDATIONS:
        raise QwenOutputValidationError(
            f"Invalid recommendation: {result.get('recommendation')!r}"
        )
    if result.get("quote_position") not in VALID_QUOTE_POSITIONS:
        raise QwenOutputValidationError(
            f"Invalid quote_position: {result.get('quote_position')!r}"
        )
    if result.get("confidence") not in VALID_CONFIDENCES:
        raise QwenOutputValidationError(
            f"Invalid confidence: {result.get('confidence')!r}"
        )
    return result


def analyze_quote(
    sku: str,
    supplier_quote: float,
    currency: str = "USD",
    quantity: Optional[int] = None,
    max_retries: int = 2,
) -> dict:
    """Run LLM quote analysis. Returns validated dict or unavailable response."""
    from aivan.llm.gateway import get_provider

    system_prompt = (
        "You are a GPM (Guided Pricing Module) assistant. "
        "Analyze supplier quotes and provide structured pricing guidance."
    )
    user_prompt = _build_quote_analysis_prompt(sku, supplier_quote, currency, quantity)

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            provider = get_provider()
            result = provider.complete_json(
                task="gpm_quote_analysis",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_hint={
                    "human_approval_required": "boolean",
                    "recommendation": "string",
                    "quote_position": "string",
                    "confidence": "string",
                    "reasoning": "string",
                },
                temperature=0.0,
            )
            return _validate_output(result)
        except QwenOutputValidationError as exc:
            last_exc = exc
            if attempt < max_retries:
                logger.warning(
                    "GPM LLM output validation failed (attempt %d/%d): %s — retrying",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )
        except RuntimeError as exc:
            # Provider raised a RuntimeError (e.g. API key missing, HTTP error)
            msg = str(exc)
            http_status = _extract_http_status(msg)
            return _make_unavailable_response(http_status)
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                logger.warning(
                    "GPM LLM call failed (attempt %d/%d): %s — retrying",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )

    logger.error("GPM LLM analysis failed after %d attempts: %s", max_retries + 1, last_exc)
    return _make_unavailable_response(500)


def _extract_http_status(error_message: str) -> int:
    """Extract HTTP status code from error string if present."""
    for code in (401, 403, 429, 500, 503):
        if str(code) in error_message:
            return code
    return 500


def mock_quote_analysis(sku: str, supplier_quote: float) -> dict:
    """Deterministic mock for tests and in-memory fallback mode."""
    return {
        "human_approval_required": True,
        "recommendation": "human_review_required",
        "quote_position": "within_mid_range",
        "confidence": "medium",
        "reasoning": f"Mock analysis for {sku} at {supplier_quote}",
        "runtime_status": "mock",
    }
