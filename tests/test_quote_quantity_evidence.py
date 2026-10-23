"""A missing order quantity is not permission to fabricate a billable quantity."""
from __future__ import annotations

import pytest

from aivan.agents import buyer_option_agent as options_agent
from aivan.pricing.customer_quote import format_customer_quote_draft
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply


def supplier_reply(moq=0):
    return SupplierReply(
        project_id="quantity-case", supplier_id="supplier-1",
        raw_text="Unit price: 12.50 GBP", unit_price=12.5, currency="GBP", moq=moq,
    )


@pytest.mark.parametrize("quantity", [None, 0, -1])
@pytest.mark.parametrize("hide_price", [False, True])
def test_unconfirmed_quantity_does_not_fabricate_quote_or_call_calculator(
    monkeypatch, quantity, hide_price,
):
    monkeypatch.setenv("AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER", str(hide_price).lower())
    calls = []
    calculate = options_agent.calculate_buyer_quote

    def capture(*args, **kwargs):
        calls.append(kwargs)
        return calculate(*args, **kwargs)

    monkeypatch.setattr(options_agent, "calculate_buyer_quote", capture)
    requirement = BuyerRequirement(project_id="quantity-case", quantity=quantity)
    options = options_agent.generate_buyer_options(
        requirement, [supplier_reply(moq=500)], [], "quantity-case")
    assert len(options) == 1
    assert options[0].supplier_id == "supplier-1"
    assert options[0].source_quote_reference
    assert options[0].quote is None
    assert calls == []
    assert any("quantity" in warning.lower() for warning in options[0].warnings)
    # Preserve the actual candidate and uncertainty through the existing DTO.
    restored = type(options[0]).model_validate_json(options[0].model_dump_json())
    assert restored.quote is None
    text = format_customer_quote_draft([restored], requirement)
    assert "Requested quantity: Not confirmed." in text
    assert "Total amount: Not confirmed." in text
    assert "Please confirm the order quantity" in text
    assert "1000" not in text


@pytest.mark.parametrize("quantity", [1, 1000, 1250])
def test_confirmed_quantity_retains_existing_calculation(monkeypatch, quantity):
    monkeypatch.setenv("AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER", "false")
    monkeypatch.setenv("AIVAN_DEFAULT_MARGIN_RATE", "0")
    requirement = BuyerRequirement(project_id="quantity-case", quantity=quantity)
    options = options_agent.generate_buyer_options(
        requirement, [supplier_reply()], [], "quantity-case")
    assert len(options) == 1
    assert options[0].quote is not None
    assert options[0].quote.quantity == quantity
    assert options[0].quote.unit_price == 12.5
    assert options[0].quote.buyer_total == 12.5 * quantity
    assert options[0].quote.currency == "GBP"


def test_confirmed_quantity_below_moq_keeps_existing_billable_rule(monkeypatch):
    monkeypatch.setenv("AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER", "false")
    monkeypatch.setenv("AIVAN_DEFAULT_MARGIN_RATE", "0")
    requirement = BuyerRequirement(project_id="quantity-case", quantity=100)
    option = options_agent.generate_buyer_options(
        requirement, [supplier_reply(moq=500)], [], "quantity-case")[0]
    assert option.quote.quantity == 100
    assert option.quote.moq == 500
    assert option.quote.buyer_total == 6250
    assert any("below supplier MOQ" in warning for warning in option.warnings)
