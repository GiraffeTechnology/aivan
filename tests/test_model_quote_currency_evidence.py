"""Explicit quote currencies outrank contradictory model extraction outputs."""
import pytest

from aivan.agents import supplier_response_agent as parser


@pytest.mark.parametrize("message,model_currency,expected", [
    ("Unit price: 12.50 GBP; freight: USD 5.00.", "USD", "GBP"),
    ("Freight: USD 5.00; unit price: 12.50 GBP.", "USD", "GBP"),
    ("Unit price: 12.50 USD; payment note: GBP account accepted.", "GBP", "USD"),
])
def test_high_confidence_model_cannot_override_explicit_unit_currency(
    monkeypatch, message, model_currency, expected,
):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_: {
        "unit_price": 12.5, "currency": model_currency, "confidence": 0.99,
    })
    result = parser.parse_supplier_reply(message, project_id="case-fixture")
    assert result.currency == expected
    assert result.unit_price == 12.5
    assert result.confidence == 0.99


def test_model_cannot_choose_a_currency_from_explicit_ambiguous_quote(monkeypatch):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_: {
        "unit_price": 12.5, "currency": "USD", "confidence": 0.99,
    })
    result = parser.parse_supplier_reply(
        "Unit price: GBP 12.50 or USD 15.00.", project_id="case-fixture",
    )
    assert result.currency == ""
    assert "currency" in result.missing_info


def test_explicit_currency_can_fill_model_omission_without_a_default(monkeypatch):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_: {
        "unit_price": 12.5, "confidence": 0.99, "missing_info": ["currency", "moq"],
    })
    result = parser.parse_supplier_reply("Unit price: 12.50 GBP.", project_id="case-fixture")
    assert result.currency == "GBP"
    assert result.missing_info == ["moq"]


def test_semantic_currency_format_outside_literal_parser_remains_supported(monkeypatch):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_: {
        "unit_price": 12.5, "currency": "EUR", "confidence": 0.99,
    })
    result = parser.parse_supplier_reply(
        "Our offer is twelve and a half euros per piece.", project_id="case-fixture",
    )
    assert result.currency == "EUR" and result.unit_price == 12.5


def test_consistent_model_currency_preserves_other_extracted_fields(monkeypatch):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_: {
        "unit_price": 12.5, "currency": "GBP", "lead_time_days": 8.5,
        "confidence": 0.99, "missing_info": ["moq"],
    })
    result = parser.parse_supplier_reply(
        "Unit price: 12.50 GBP; lead time 8.5 days.", project_id="case-fixture",
    )
    assert (result.currency, result.unit_price, result.lead_time_days) == ("GBP", 12.5, 8.5)
    assert result.missing_info == ["moq"]
