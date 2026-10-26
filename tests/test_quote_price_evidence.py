"""Preserve quoted price facts in option selection and explanations.

These synthetic unit fixtures do not establish live GLTG, database or UI acceptance.
"""
from __future__ import annotations

import pytest

from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.schemas.leadtime import LeadTimeEstimate
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply


def reply(supplier: str, price: float | None, currency: str = "GBP") -> SupplierReply:
    return SupplierReply(project_id="quote-case", supplier_id=supplier,
                         raw_text=f"Unit price: {price} {currency}",
                         unit_price=price, currency=currency)


def options(replies, estimates=()):
    return generate_buyer_options(
        BuyerRequirement(project_id="quote-case", quantity=1000, quantity_unit="pcs"),
        replies, list(estimates), "quote-case",
    )


@pytest.mark.parametrize("zero_first", [True, False])
def test_explicit_zero_unit_quote_is_not_missing_price(zero_first):
    replies = [reply("zero-quote", 0.0), reply("paid-quote", 12.5)]
    if not zero_first:
        replies.reverse()
    result = options(replies)
    lowest = next(item for item in result if item.option_type == "lowest_cost")
    assert lowest.supplier_id == "zero-quote"
    assert lowest.quote.currency == "GBP"
    assert lowest.quote.buyer_total == 0
    assert len({item.supplier_id for item in result}) == len(result)


@pytest.mark.parametrize("price", [0.0042, 12.34567, 1.23456789])
def test_lowest_cost_reason_preserves_stored_supplier_unit_price(price):
    selected = options([reply("precise-quote", price)])[0]
    assert selected.option_type == "lowest_cost"
    assert selected.reasoning == f"Lowest cost: GBP {price}/pc"
    assert selected.quote.currency == "GBP"


def test_next_comparable_quote_reason_preserves_price_without_recalculating_it():
    lead_time = LeadTimeEstimate(
        estimate_id="synthetic-lead-evidence", project_id="quote-case",
        supplier_id="fast-cheap", category="apparel",
        calculated_lead_time_days=2.5, expected_days=2.5, conservative_days=3.5,
        p50_days=2.5, p80_days=3.5, p90_days=4.5, risk_buffer_days=1,
    )
    result = options([reply("fast-cheap", 0.0012), reply("next-quote", 0.0042)], [lead_time])
    next_quote = next(item for item in result if item.supplier_id == "next-quote")
    assert next_quote.reasoning == "Next comparable quote: GBP 0.0042/pc"
    assert result[0].lead_time_estimate.p80_days == 3.5
    assert result[0].lead_time_estimate.earliest_possible_days is None


def test_actual_missing_price_is_still_excluded():
    result = options([reply("missing-quote", None), reply("actual-quote", 12.5)])
    assert [item.supplier_id for item in result] == ["actual-quote"]


def test_zero_does_not_make_incompatible_currencies_comparable():
    result = options([reply("zero-quote", 0.0, "GBP"), reply("usd-quote", 12.5, "USD")])
    assert len(result) == 2
    assert all(item.option_type != "lowest_cost" for item in result)
    assert all(any("not directly comparable" in warning for warning in item.warnings)
               for item in result)
