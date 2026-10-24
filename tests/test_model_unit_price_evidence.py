"""Literal quoted unit prices survive model extraction; synthetic unit fixtures."""
from __future__ import annotations

import pytest

from aivan.agents import supplier_response_agent as parser


@pytest.mark.parametrize("price", [0.0, 0.0042, 12.5, 12.34567])
@pytest.mark.parametrize("model_price", [999.0, None])
def test_model_cannot_override_or_erase_explicit_unit_price(monkeypatch, price, model_price):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_args: {
        "unit_price": model_price, "currency": "USD", "lead_time_days": 30,
        "confidence": 0.95, "missing_info": ["unit_price", "payment_terms"],
        "risks": ["capacity_unconfirmed"],
    })
    result = parser.parse_supplier_reply(
        f"Unit price: {price} GBP; production lead time 8.5 days.",
        "price-evidence-case", "supplier-1", "candidate-1",
    )
    assert result.unit_price == price
    assert result.currency == "GBP"
    assert result.lead_time_days == 8.5
    assert result.missing_info == ["payment_terms"]
    assert result.risks == ["capacity_unconfirmed"]
    assert result.confidence == 0.95
    assert (result.project_id, result.supplier_id, result.candidate_id) == (
        "price-evidence-case", "supplier-1", "candidate-1")


def test_literal_unit_price_supplies_model_omission(monkeypatch):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_args: {
        "currency": "GBP", "confidence": 0.95,
        "missing_info": ["unit_price", "capacity_per_day"],
    })
    result = parser.parse_supplier_reply("GBP 12.50 per piece", "price-evidence-case")
    assert result.unit_price == 12.5
    assert result.missing_info == ["capacity_per_day"]
    assert result.confidence == 0.95


def test_semantic_price_without_supported_literal_keeps_existing_model_path(monkeypatch):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_args: {
        "unit_price": 12.5, "currency": "GBP", "confidence": 0.95,
    })
    result = parser.parse_supplier_reply(
        "The cost of each piece is twelve pounds fifty.", "price-evidence-case")
    assert result.unit_price == 12.5
    assert result.currency == "GBP"
    assert result.confidence == 0.95
