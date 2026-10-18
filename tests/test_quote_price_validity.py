"""Invalid supplier prices must not become actionable buyer recommendations."""
import math

import pytest

from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply
from aivan.schemas.leadtime import LeadTimeEstimate


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


def options(replies, leads=None):
    requirement = BuyerRequirement(
        project_id="price-validity", quantity=100, quantity_unit="pcs"
    )
    return generate_buyer_options(requirement, replies, leads or [], requirement.project_id)


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


def quote_for(supplier, price, currency="GBP"):
    return SupplierReply(project_id="price-validity", supplier_id=supplier,
                         raw_text="Synthetic comparable quotation", unit_price=price, currency=currency)


def lead_for(supplier, days):
    # A synthetic provider DTO, not a local GLTG calculation or real evidence.
    return LeadTimeEstimate(estimate_id="synthetic-" + supplier, project_id="price-validity",
        supplier_id=supplier, category="synthetic", calculated_lead_time_days=days,
        earliest_possible_days=days, expected_days=days, conservative_days=days,
        p50_days=days, p80_days=days, p90_days=days, risk_buffer_days=0)


def test_explicit_zero_is_cheapest_when_mixed_with_paid_and_fastest_quotes(visible_prices):
    replies = [quote_for("fast", 3.0), quote_for("paid", 1.0), quote_for("zero", 0.0)]
    result = options(replies, [lead_for("fast", 10), lead_for("paid", 30), lead_for("zero", 20)])
    cheapest = next(option for option in result if option.option_type == "lowest_cost")
    assert cheapest.supplier_id == "zero"
    assert cheapest.quote.unit_price == 0.0


def test_unlike_currencies_are_not_given_a_lowest_cost_label(visible_prices):
    result = options([quote_for("gbp", 3.0), quote_for("usd", 1.0, "USD")],
                     [lead_for("gbp", 10), lead_for("usd", 20)])
    assert all(option.option_type != "lowest_cost" for option in result)
    assert all(any("not directly comparable" in warning for warning in option.warnings) for option in result)
    assert {option.quote.currency for option in result} == {"GBP", "USD"}


def test_price_reason_uses_selected_quote_currency_not_last_iteration(visible_prices):
    replies = [quote_for("fast", 9.0), quote_for("cheap", 1.0), quote_for("last", 5.0, "gbp")]
    result = options(replies, [lead_for("fast", 10), lead_for("cheap", 20), lead_for("last", 30)])
    cheapest = next(option for option in result if option.option_type == "lowest_cost")
    assert cheapest.supplier_id == "cheap" and cheapest.quote.currency == "GBP"
    assert cheapest.reasoning.startswith("Lowest cost: GBP 1.00/pc")


def test_latest_valid_business_revision_does_not_create_duplicate_supplier_options(visible_prices):
    result = options([quote_for("same", 3.0), quote_for("same", 2.0)], [lead_for("same", 10)])
    assert len(result) == 1
    assert result[0].supplier_id == "same" and result[0].quote.unit_price == 2.0


def test_missing_evidence_does_not_claim_fastest_or_supplier_reliability(visible_prices):
    result = options([quote_for("unknown-history", 2.0)])
    assert all(option.option_type not in {"fastest", "safest"} for option in result)
    assert all(option.risk_level == "unknown" for option in result)
    assert all("strong track record" not in option.reasoning for option in result)
