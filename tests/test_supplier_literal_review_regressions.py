"""Supplier ranges need clarification; unit-label currencies remain evidence.

These synthetic unit fixtures do not establish real-service acceptance.
"""
from __future__ import annotations

import pytest

from aivan.agents import supplier_response_agent as parser


@pytest.fixture(params=["unavailable", "low-confidence", "confident-value", "confident-unresolved"])
def literal_model(monkeypatch, request):
    def completion(*_args):
        if request.param == "unavailable":
            raise RuntimeError("controlled model unavailable")
        return {
            "unit_price": 999,
            "currency": "",
            "lead_time_days": None if request.param == "confident-unresolved" else 15,
            "confidence": 0.2 if request.param == "low-confidence" else 0.95,
            "missing_info": ["lead_time_days", "currency", "payment_terms"],
        }
    monkeypatch.setattr(parser, "llm_complete_json", completion)
    return request.param


@pytest.mark.parametrize("duration", [
    "10 to 15 days", "10-15 days", "10–15 days", "10—15 days",
    "10 days to 15 days", "10 or 15 days", "10/15 days",
    "between 10 and 15 days", "8.5 to 10.25 days", ".5 to 1.5 days",
    "10 to 10 days", "10至15天",
])
def test_explicit_lead_time_range_remains_unresolved(literal_model, duration):
    reply = parser.parse_supplier_reply(
        f"Unit price: GBP 12.50; production lead time {duration}.",
        "literal-review-case", "supplier-1", "candidate-1",
    )
    assert reply.lead_time_days is None
    assert reply.missing_info.count("lead_time_days") == 1
    assert reply.unit_price == 12.5
    assert reply.currency == "GBP"
    assert reply.raw_text.endswith(f"{duration}.")
    assert reply.supplier_id == "supplier-1"
    assert reply.candidate_id == "candidate-1"
    assert reply.confidence == (0.95 if literal_model.startswith("confident") else 0.4)


@pytest.mark.parametrize("terms,currency", [
    ("GBP unit price: 12.50", "GBP"),
    ("gbp unit price = 12.50", "GBP"),
    ("EUR: unit price: 12.50", "EUR"),
    ("Freight: USD 5.00 GBP unit price: 12.50", "GBP"),
    ("USD freight: 5.00 GBP unit price: 12.50", "GBP"),
    ("GBP unit price: 12.50 shipping USD 5.00", "GBP"),
    ("Freight: USD 5.00 unit price: 12.50", ""),
    ("GBP freight: 5.00 unit price: 12.50", ""),
    ("GBP or EUR unit price: 12.50", ""),
    ("GBP/EUR unit price: 12.50", ""),
])
def test_unit_label_currency_is_kept_without_borrowing_freight_currency(
    literal_model, terms, currency,
):
    reply = parser.parse_supplier_reply(
        terms + "; production lead time 8.5 days.", "literal-review-case",
    )
    assert reply.unit_price == 12.5
    assert reply.currency == currency
    assert ("currency" in reply.missing_info) == (not currency)
    assert reply.lead_time_days == 8.5
    assert "lead_time_days" not in reply.missing_info
    assert reply.confidence == (0.95 if literal_model.startswith("confident") else 0.4)


@pytest.mark.parametrize("text,days", [
    ("production lead time 8.5 days; raw material lead time 2 to 3 days", 8.5),
    ("production lead time 8.5 days; offer valid for 10 to 15 days", 8.5),
    ("production lead time 8.5 days; payment due in 10 to 15 days", 8.5),
    ("production lead time 0 days", 0),
])
def test_unrelated_ranges_do_not_erase_a_single_lead_time(literal_model, text, days):
    reply = parser.parse_supplier_reply("GBP unit price: 12.50; " + text, "literal-review-case")
    assert reply.lead_time_days == days
    assert "lead_time_days" not in reply.missing_info
    assert reply.currency == "GBP"
    assert reply.confidence == (0.95 if literal_model.startswith("confident") else 0.4)
