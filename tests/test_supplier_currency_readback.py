"""Saved supplier records must not gain a currency absent from their evidence."""
import pytest

from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply


def saved_record(**updates):
    record = {"project_id": "case-fixture", "supplier_id": "supplier-fixture",
              "raw_text": "Unit price: 12.50; lead time 8.5 days.",
              "unit_price": 12.5, "lead_time_days": 8.5}
    record.update(updates)
    return record


def test_saved_reply_missing_currency_stays_unknown_on_readback():
    # This is the same SupplierReply(**raw) boundary used by RFQ reply recovery.
    record = saved_record()
    reply = SupplierReply(**record)
    assert "currency" not in record
    assert reply.currency == ""


def test_recovered_unknown_currency_is_not_published_as_a_dollar_quote(monkeypatch):
    monkeypatch.setenv("AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER", "false")
    reply = SupplierReply(**saved_record())
    options = generate_buyer_options(
        BuyerRequirement(project_id="case-fixture", quantity=100, quantity_unit="pcs"),
        [reply], [], "case-fixture",
    )
    assert len(options) == 1
    assert options[0].quote.currency == ""
    assert all("USD" not in line for line in options[0].quote.calculation_trace)


@pytest.mark.parametrize("currency", ["USD", "GBP", ""])
def test_readback_preserves_explicit_currency_without_conversion(currency):
    reply = SupplierReply(**saved_record(currency=currency))
    assert reply.currency == currency
