"""Explicit supplier price alternatives require clarification, not selection."""
from __future__ import annotations

import pytest

from aivan.agents import supplier_response_agent as parser
from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.schemas.requirement import BuyerRequirement


def configure_model(monkeypatch, available):
    def completion(*_args):
        if not available:
            raise RuntimeError("controlled model unavailable")
        return {"unit_price": 12.5, "currency": "GBP", "confidence": 0.95,
                "missing_info": ["payment_terms"]}
    monkeypatch.setattr(parser, "llm_complete_json", completion)


@pytest.mark.parametrize("model_available", [True, False])
@pytest.mark.parametrize("terms", [
    "Unit price: GBP 12.50 or GBP 15.00",
    "Unit price: 12.50 GBP or 15.00 GBP",
    "Unit price: 12.50 to 15.00 GBP",
    "Unit price: GBP 12.50-15.00",
    "Unit price: 12.50–15.00 GBP",
    "Unit price: GBP 0.00 or GBP 12.50",
])
def test_alternative_or_range_price_is_not_a_single_quote(monkeypatch, model_available, terms):
    configure_model(monkeypatch, model_available)
    result = parser.parse_supplier_reply(
        terms + "; production lead time 8.5 days.", "price-range-case", "supplier-1")
    assert result.unit_price is None
    assert result.currency == "GBP"
    assert result.missing_info.count("unit_price") == 1
    assert result.lead_time_days == 8.5
    assert result.supplier_id == "supplier-1"
    assert result.confidence == (0.95 if model_available else 0.4)
    if model_available:
        assert "payment_terms" in result.missing_info
    assert generate_buyer_options(
        BuyerRequirement(project_id="price-range-case", quantity=100),
        [result], [], "price-range-case",
    ) == []


@pytest.mark.parametrize("model_available", [True, False])
@pytest.mark.parametrize("terms,price", [
    ("Unit price: GBP 12.50; freight: GBP 5.00", 12.5),
    ("Unit price: GBP 12.50 for 100 to 200 pieces", 12.5),
    ("Unit price: GBP 12.50 or GBP 12.50", 12.5),
    ("Unit price: GBP 0.00", 0),
])
def test_single_price_is_not_confused_with_freight_or_quantity_range(
    monkeypatch, model_available, terms, price,
):
    configure_model(monkeypatch, model_available)
    result = parser.parse_supplier_reply(terms, "price-range-case", "supplier-1")
    assert result.unit_price == price
    assert result.currency == "GBP"
    assert "unit_price" not in result.missing_info
    assert result.confidence == (0.95 if model_available else 0.4)
