"""Invalid supplier prices must not become actionable buyer recommendations."""
import math

import pytest

from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply


@pytest.fixture
def visible_prices(monkeypatch):
    monkeypatch.setenv("AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER", "false")


def reply(price, text="Synthetic quotation"):
    return SupplierReply(
        project_id="price-validity",
        supplier_id="synthetic-supplier",
        raw_text=text,
        unit_price=price,
        currency="GBP",
    )


def options(replies):
    requirement = BuyerRequirement(
        project_id="price-validity", quantity=100, quantity_unit="pcs"
    )
    return generate_buyer_options(requirement, replies, [], requirement.project_id)


@pytest.mark.parametrize("price", [-1.0, float("nan"), float("inf"), -float("inf")])
def test_invalid_price_cannot_generate_a_buyer_option(price, visible_prices):
    assert options([reply(price)]) == []


@pytest.mark.parametrize("price", [-1.0, float("nan"), float("inf"), -float("inf")])
def test_invalid_followup_cannot_displace_an_available_valid_quote(price, visible_prices):
    valid = reply(2.5, "Earlier valid quotation")
    invalid = reply(price, "Invalid follow-up quotation")
    result = options([valid, invalid])
    assert len(result) == 1
    assert result[0].quote.unit_price == 2.5
    assert result[0].quote.currency == "GBP"
    assert math.isfinite(result[0].quote.buyer_total)
    assert valid.unit_price == 2.5
    if math.isnan(price):
        assert math.isnan(invalid.unit_price)
    else:
        assert invalid.unit_price == price


def test_explicit_zero_price_remains_admitted(visible_prices):
    result = options([reply(0.0)])
    assert len(result) == 1
    assert result[0].quote.unit_price == 0.0
    assert result[0].quote.buyer_total == 0.0
