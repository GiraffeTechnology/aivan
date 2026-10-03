"""Supplier quotation parsing preserves explicit terms; fixtures are not live acceptance."""
from __future__ import annotations

import pytest

from aivan.agents import supplier_response_agent as parser
from aivan.execution.source_quote import source_quote_reference
from aivan.schemas.response import SupplierReply
from aivan.schemas.requirement import BuyerRequirement
from aivan.integrations.gltg import GLTGClient


@pytest.fixture
def unavailable_parser_model(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("controlled parser model unavailable")
    monkeypatch.setattr(parser, "llm_complete_json", unavailable)


@pytest.mark.parametrize("days", [0.5, 8.5, 29.25])
def test_fallback_preserves_fractional_supplier_lead_time(unavailable_parser_model, days):
    result = parser.parse_supplier_reply(
        f"Unit price: 12.50 GBP; MOQ 100; lead time {days} days.",
        project_id="case-fixture", supplier_id="supplier-fixture",
    )
    assert result.lead_time_days == days
    assert result.unit_price == 12.5
    assert result.currency == "GBP"


@pytest.mark.parametrize("text", ["GBP 12.50 per piece", "Unit price: 12.50 GBP"])
def test_fallback_preserves_explicit_quote_currency(unavailable_parser_model, text):
    result = parser.parse_supplier_reply(text, project_id="case-fixture")
    assert result.unit_price == 12.5
    assert result.currency == "GBP"


def test_missing_currency_remains_missing_without_invented_usd(unavailable_parser_model):
    result = parser.parse_supplier_reply("Unit price: 12.50; lead time 8.5 days", project_id="case-fixture")
    assert result.unit_price == 12.5
    assert result.currency == ""
    assert "currency" in result.missing_info


def test_model_fractional_lead_time_does_not_silently_drop_to_fallback(monkeypatch):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_args: {
        "unit_price": 12.5, "currency": "GBP", "lead_time_days": 8.5,
        "confidence": 0.9, "source_event_id": "model-must-not-supply-identity",
    })
    result = parser.parse_supplier_reply("Unit price: 12.50 GBP; lead time 8.5 days", project_id="case-fixture")
    assert result.lead_time_days == 8.5
    assert result.currency == "GBP"
    assert result.confidence == 0.9
    assert result.source_event_id == ""


def test_model_missing_currency_does_not_receive_schema_default(monkeypatch):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_args: {"unit_price": 12.5, "confidence": 0.9})
    result = parser.parse_supplier_reply("Unit price: 12.50", project_id="case-fixture")
    assert result.currency == ""
    assert "currency" in result.missing_info


def test_legacy_integer_lead_time_keeps_existing_quote_fingerprint():
    result = SupplierReply(
        project_id="case-fixture", supplier_id="supplier-fixture",
        raw_text="Unit price: 12.50 GBP; lead time 35 days",
        unit_price=12.5, currency="GBP", lead_time_days=35,
    )
    assert source_quote_reference(result) == (
        "aivan-source-quote-sha256-"
        "448527f7e76cfa81b5bbf7d1ed8cbf53a4c6efb2bbe1f5c60d91191bd1fb6ee4"
    )


def test_fractional_and_message_revisions_have_distinct_fingerprints():
    first = SupplierReply(project_id="case-fixture", supplier_id="supplier-fixture",
        raw_text="Unit price: 12.50 GBP", unit_price=12.5, currency="GBP",
        lead_time_days=8.5, source_event_id="actual-message-1")
    revised_days = first.model_copy(update={"lead_time_days": 8.75})
    revised_message = first.model_copy(update={"source_event_id": "actual-message-2"})
    assert len({source_quote_reference(item) for item in (first, revised_days, revised_message)}) == 3


@pytest.mark.parametrize("days", ["-8.5", "8,5"])
def test_unsupported_duration_is_not_a_positive_tail_integer(unavailable_parser_model, days):
    result = parser.parse_supplier_reply(f"Price 12.50 GBP; lead time {days} days", project_id="case-fixture")
    assert result.lead_time_days is None


def test_ambiguous_currency_requires_clarification(unavailable_parser_model):
    result = parser.parse_supplier_reply("Price 12.50 GBP or USD 15.00", project_id="case-fixture")
    assert result.currency == ""
    assert "currency" in result.missing_info


def test_fractional_supplier_declaration_survives_gltg_result_dto(monkeypatch):
    # Controlled HTTP-result shape only; this does not test the external model.
    monkeypatch.setattr(GLTGClient, "_estimate", lambda *_args, **_kwargs: {
        "p50_days": 8.25, "p80_days": 9.75, "p90_days": 10.25,
        "estimated_lead_time_days": 9.75, "risk_level": "low", "feasible": True,
    })
    result = GLTGClient().estimate_for_requirement(
        BuyerRequirement(project_id="case-fixture", quantity=100, delivery_days=12),
        supplier_reply=SupplierReply(project_id="case-fixture", raw_text="8.5 days", lead_time_days=8.5),
    )
    assert result.declared_lead_time_days == 8.5
    assert (result.p50_days, result.p80_days, result.p90_days) == (8.25, 9.75, 10.25)
    assert result.earliest_possible_days is None


@pytest.mark.parametrize("currency", ["GBP", ""])
def test_buyer_quote_explanation_uses_selected_currency_without_default_usd(monkeypatch, currency):
    from aivan.agents.buyer_option_agent import generate_buyer_options

    monkeypatch.setenv("AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER", "false")
    reply = SupplierReply(project_id="case-fixture", supplier_id="supplier-fixture",
        raw_text=f"Unit price: 12.50 {currency}", unit_price=12.5, currency=currency)
    option = generate_buyer_options(
        BuyerRequirement(project_id="case-fixture", quantity=100, quantity_unit="pcs"),
        [reply], [], "case-fixture",
    )[0]
    assert option.quote.currency == currency
    buyer_unit_trace = [line for line in option.quote.calculation_trace if line.startswith("Buyer unit price:")]
    assert len(buyer_unit_trace) == 1
    assert "USD" not in buyer_unit_trace[0]
    if currency:
        assert buyer_unit_trace[0].endswith(f" {currency}")


@pytest.mark.parametrize("text,currency", [
    ("Unit price: 12.50; freight: GBP 5.00; lead time 8.5 days.", ""),
    ("Unit price: 12.50 GBP; freight: USD 5.00; lead time 8.5 days.", "GBP"),
])
def test_freight_currency_does_not_supply_or_override_unit_quote(unavailable_parser_model, text, currency):
    result = parser.parse_supplier_reply(text, project_id="case-fixture")
    assert result.unit_price == 12.5
    assert result.currency == currency
    assert ("currency" in result.missing_info) == (not currency)


@pytest.mark.parametrize("text,days", [
    ("Unit price: 12.50 GBP; offer valid for 2 days; production lead time 8.5 days.", 8.5),
    ("Unit price: 12.50 GBP; offer valid for 2 days.", None),
    ("Unit price: 12.50 GBP; lead time 8.5 days; payment due in 30 days.", 8.5),
    ("Unit price: 12.50 GBP; lead time 8.5 days or 10 days.", None),
])
def test_declared_lead_time_is_not_validity_payment_or_ambiguous_days(unavailable_parser_model, text, days):
    result = parser.parse_supplier_reply(text, project_id="case-fixture")
    assert result.lead_time_days == days


@pytest.mark.parametrize("condition", ["including shipping", "including freight", "including packaging"])
def test_explicit_unit_price_retains_included_cost_condition(unavailable_parser_model, condition):
    result = parser.parse_supplier_reply(
        f"Unit price: 12.50 GBP {condition}; lead time 8.5 days.", project_id="case-fixture")
    assert result.unit_price == 12.5
    assert result.currency == "GBP"
    assert result.lead_time_days == 8.5


def test_fee_only_message_does_not_create_a_unit_quote(unavailable_parser_model):
    result = parser.parse_supplier_reply("Freight: GBP 5.00; lead time 8.5 days.", project_id="case-fixture")
    assert result.unit_price is None
    assert result.currency == ""
