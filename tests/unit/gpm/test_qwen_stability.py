"""Qwen output stability tests — GPM-004 and GPM-005."""
import pytest
from unittest.mock import MagicMock, patch

from aivan.gpm.llm_runtime import (
    QwenOutputValidationError,
    _make_unavailable_response,
    _validate_output,
    analyze_quote,
)

# ── GPM-004: machine-readable reason codes ───────────────────────────────────

def test_reason_code_401_is_invalid_token():
    result = _make_unavailable_response(401)
    assert result["reason"] == "invalid_token"
    assert result["runtime_status"] == "unavailable"
    assert result["operator_action_required"] is True


def test_reason_code_429_is_rate_limit_exceeded():
    result = _make_unavailable_response(429)
    assert result["reason"] == "rate_limit_exceeded"


def test_reason_code_403_is_forbidden():
    result = _make_unavailable_response(403)
    assert result["reason"] == "forbidden"


def test_reason_code_503_is_provider_unavailable():
    result = _make_unavailable_response(503)
    assert result["reason"] == "provider_unavailable"


def test_reason_code_unknown_falls_back_to_provider_error():
    result = _make_unavailable_response(418)
    assert result["reason"] == "provider_error"


def test_safe_message_does_not_contain_api_key():
    result = _make_unavailable_response(401)
    assert "sk-" not in str(result)
    assert "API key" not in result["reason"]


# ── GPM-005: output validation ────────────────────────────────────────────────

VALID_OUTPUT = {
    "human_approval_required": True,
    "recommendation": "accept",
    "quote_position": "within_mid_range",
    "confidence": "high",
    "reasoning": "Price within normal market range.",
}


def test_valid_output_passes_validation():
    result = _validate_output(dict(VALID_OUTPUT))
    assert result["recommendation"] == "accept"


def test_missing_required_key_raises():
    bad = {k: v for k, v in VALID_OUTPUT.items() if k != "confidence"}
    with pytest.raises(QwenOutputValidationError, match="confidence"):
        _validate_output(bad)


def test_invalid_recommendation_raises():
    bad = {**VALID_OUTPUT, "recommendation": "unknown_action"}
    with pytest.raises(QwenOutputValidationError, match="recommendation"):
        _validate_output(bad)


def test_invalid_quote_position_raises():
    bad = {**VALID_OUTPUT, "quote_position": "totally_wrong"}
    with pytest.raises(QwenOutputValidationError, match="quote_position"):
        _validate_output(bad)


# ── GPM-005: retry logic ─────────────────────────────────────────────────────

def test_analyze_quote_retries_on_schema_failure_then_succeeds():
    """First call returns bad output, second call returns valid output."""
    call_count = 0

    def fake_complete_json(task, system_prompt, user_prompt, schema_hint, temperature):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"bad": "output"}  # missing required keys → validation error
        return dict(VALID_OUTPUT)

    mock_provider = MagicMock()
    mock_provider.complete_json.side_effect = fake_complete_json

    with patch("aivan.llm.gateway.get_provider", return_value=mock_provider):
        result = analyze_quote("SKU-001", 3.75, max_retries=2)

    assert result["recommendation"] == "accept"
    assert call_count == 2


def test_analyze_quote_raises_after_max_retries_exceeded():
    """All attempts return bad output → returns unavailable response (no raise)."""
    mock_provider = MagicMock()
    mock_provider.complete_json.return_value = {"missing": "required_keys"}

    with patch("aivan.llm.gateway.get_provider", return_value=mock_provider):
        result = analyze_quote("SKU-001", 3.75, max_retries=1)

    assert result["runtime_status"] == "unavailable"
    assert result["operator_action_required"] is True


def test_analyze_quote_returns_unavailable_on_runtime_error():
    """Provider raises RuntimeError with 401 in message → GPM-004 response."""
    mock_provider = MagicMock()
    mock_provider.complete_json.side_effect = RuntimeError(
        "Qwen request failed after retries: 401 Unauthorized"
    )

    with patch("aivan.llm.gateway.get_provider", return_value=mock_provider):
        result = analyze_quote("SKU-001", 3.75, max_retries=0)

    assert result["runtime_status"] == "unavailable"
    assert result["reason"] == "invalid_token"
