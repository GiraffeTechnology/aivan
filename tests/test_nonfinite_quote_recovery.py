"""Uncomputable quote values cannot become offers or break valid alternatives."""
from __future__ import annotations

import math

import pytest

from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply


def quote(supplier: str, price: float) -> SupplierReply:
    return SupplierReply(project_id="finite-case", supplier_id=supplier,
                         raw_text="Synthetic supplier extraction fixture",
                         unit_price=price, currency="GBP")


def options(replies):
    return generate_buyer_options(
        BuyerRequirement(project_id="finite-case", quantity=1000, quantity_unit="pcs"),
        replies, [], "finite-case",
    )


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")],
                         ids=["nan", "positive-infinity", "negative-infinity"])
def test_nonfinite_quote_does_not_break_valid_supplier_alternative(invalid, monkeypatch):
    monkeypatch.setenv("AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER", "false")
    replies = [quote("invalid-price", invalid), quote("valid-price", 12.34567)]
    result = options(replies)
    assert [item.supplier_id for item in result] == ["valid-price"]
    assert result[0].reasoning == "Lowest cost: GBP 12.35/pc"
    assert result[0].quote.unit_price == 12.34567
    assert result[0].quote.calculation_trace[0].startswith("Unit price: 12.34567 × ")
    assert math.isfinite(result[0].quote.buyer_total)
    assert len(replies) == 2
    assert not math.isfinite(replies[0].unit_price)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")],
                         ids=["nan", "positive-infinity", "negative-infinity"])
def test_only_nonfinite_quotes_produce_no_actionable_option(invalid):
    assert options([quote("invalid-price", invalid)]) == []


@pytest.mark.parametrize("valid", [0.0, 12.34567])
def test_finite_zero_and_precise_quotes_remain_available(valid, monkeypatch):
    monkeypatch.setenv("AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER", "false")
    result = options([quote("valid-price", valid)])
    assert len(result) == 1
    assert result[0].supplier_id == "valid-price"
    assert result[0].quote.currency == "GBP"
    assert result[0].reasoning == f"Lowest cost: GBP {valid:.2f}/pc"
    assert result[0].quote.unit_price == valid
    assert result[0].quote.calculation_trace[0].startswith(f"Unit price: {valid} × ")

