"""Canonical commercial drafts preserve actual quote figures and uncertainty."""

import pytest
from decimal import Decimal

from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.execution.rfq_execution import _create_customer_quote_email_draft
from aivan.openclaw.contracts import OpenClawEvent
from aivan.pricing.customer_quote import _display_amount, deadline_warning, format_customer_quote_draft
from aivan.schemas.leadtime import LeadTimeEstimate
from aivan.schemas.quote import BuyerOption, QuoteCalculation
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply


def _requirement(**updates):
    values = {
        "project_id": "commercial-project",
        "product_type": "cotton polo shirts",
        "quantity": 1200,
        "quantity_unit": "pcs",
        "delivery_days": 60,
    }
    values.update(updates)
    return BuyerRequirement(**values)


def _estimate(**updates):
    values = {
        "estimate_id": "commercial-estimate",
        "project_id": "commercial-project",
        "supplier_id": "private-supplier",
        "category": "apparel",
        "calculated_lead_time_days": 56.0,
        "expected_days": 56.0,
        "conservative_days": 66.08,
        "p50_days": 56.0,
        "p80_days": 66.08,
        "p90_days": 75.6,
        "risk_buffer_days": 10.08,
        "deadline_days": 60,
        "deadline_feasible": False,
        "deadline_risk_level": "high",
    }
    values.update(updates)
    return LeadTimeEstimate(**values)


def _option(**updates):
    values = {
        "option_id": "commercial-option",
        "project_id": "commercial-project",
        "option_label": "Option A — Fastest",
        "option_type": "fastest",
        "supplier_id": "private-supplier",
        "reasoning": "Private supplier cost USD 8.5 from private-supplier",
        "lead_time_estimate": _estimate(),
        "quote": QuoteCalculation(
            supplier_id="private-supplier",
            unit_price=0.0,
            quantity=1200,
            currency="USD",
            buyer_unit_price=10.0,
            buyer_total=12000.0,
            calculation_trace=["Private supplier cost USD 8.5"],
        ),
    }
    values.update(updates)
    return BuyerOption(**values)


def test_generated_warning_uses_actual_p80_without_changing_gltg_or_pricing(monkeypatch):
    monkeypatch.setenv("AIVAN_DEFAULT_MARGIN_RATE", "0.15")
    monkeypatch.setenv("AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER", "true")
    monkeypatch.setenv("AIVAN_HIDE_SUPPLIER_IDENTITY_FROM_BUYER", "true")
    requirement = _requirement()
    estimate = _estimate()
    original_estimate = estimate.model_dump()
    reply = SupplierReply(
        project_id=requirement.project_id,
        supplier_id="private-supplier",
        raw_text="Synthetic supplier quotation",
        unit_price=8.5,
        currency="USD",
        moq=1000,
    )

    options = generate_buyer_options(requirement, [reply], [estimate], requirement.project_id)

    assert len(options) == 1 and options[0].option_type == "fastest"
    assert options[0].warnings == [
        "The P80 lead-time estimate (66.08 days) exceeds the 60-day deadline."
    ]
    assert options[0].warnings[0] in options[0].reasoning
    assert options[0].lead_time_estimate.model_dump() == original_estimate
    assert estimate.model_dump() == original_estimate
    assert options[0].quote.quantity == 1200
    assert options[0].quote.buyer_unit_price == 10.0
    assert options[0].quote.buyer_total == 12000.0
    assert options[0].quote.unit_price == 0.0
    assert options[0].supplier_display_name == "Supplier (confidential)"


def test_draft_figures_match_quote_and_distinguish_quantiles_from_deadline():
    option = _option()
    body = format_customer_quote_draft(
        [option], _requirement(),
        gpm_guidance={"recommendation": "human_review_required", "confidence": "low"},
    )

    for field in (
        "Product: cotton polo shirts.",
        "Requested quantity: 1200 pcs.",
        "Buyer unit price: USD 10.0.",
        "Total amount: USD 12,000.0.",
        "Estimated lead time at P50: 56.0 days.",
        "Estimated lead time at P80: 66.08 days.",
        "Estimated lead time at P90: 75.6 days.",
        "Requested deadline: 60 days.",
        "Deadline warning: The P80 lead-time estimate exceeds the assessed deadline.",
        "Deadline risk level: high.",
        "Lead-time estimates are not a delivery guarantee.",
        "Pricing guidance: Human review is required.",
        "Confidence: low.",
        "Human approval is still required.",
    ):
        assert field in body
    assert "56.0 days) exceeds" not in body
    assert "private-supplier" not in body and "USD 8.5" not in body
    assert "human_review_required" not in body and "|" not in body
    assert option.quote.buyer_total == 12000.0


@pytest.mark.parametrize("quantity", [None, 0, 900])
def test_missing_or_mismatched_quantity_never_discloses_fallback_totals(quantity):
    option = _option(quote=QuoteCalculation(
        quantity=1000, currency="USD", buyer_unit_price=10.0, buyer_total=10000.0,
    ))
    body = format_customer_quote_draft([option], _requirement(quantity=quantity))
    assert "Buyer unit price: Not confirmed." in body
    assert "Total amount: Not confirmed." in body
    assert "Please confirm" in body
    assert "USD" not in body and "1000" not in body
    if quantity == 900:
        assert "Requested quantity: 900 pcs." in body
        assert "quotation quantity differs" in body
    else:
        assert "Requested quantity: Not confirmed." in body


def test_generated_fallback_quantity_does_not_become_customer_offer(monkeypatch):
    monkeypatch.setenv("AIVAN_DEFAULT_MARGIN_RATE", "0")
    requirement = _requirement(quantity=None)
    reply = SupplierReply(
        project_id=requirement.project_id, supplier_id="private-supplier",
        raw_text="Synthetic quote without a buyer quantity", unit_price=10.0, currency="USD",
    )
    options = generate_buyer_options(requirement, [reply], [_estimate()], requirement.project_id)
    # The presentation fix does not change legacy pricing math or its inputs.
    assert options[0].quote.quantity == 1000
    body = format_customer_quote_draft(options, requirement)
    assert "1000" not in body and "USD" not in body
    assert "Please confirm the order quantity" in body


@pytest.mark.parametrize("quote", [
    None,
    QuoteCalculation(quantity=1200),
    QuoteCalculation(quantity=1200, currency="", buyer_unit_price=10, buyer_total=12000),
])
def test_missing_prices_or_currency_are_not_filled_from_schema_defaults(quote):
    body = format_customer_quote_draft([_option(quote=quote)], _requirement())
    assert "Buyer unit price: Not confirmed." in body
    assert "Total amount: Not confirmed." in body
    assert "USD" not in body and "12000" not in body


def test_missing_product_and_lead_time_do_not_invent_business_facts():
    body = format_customer_quote_draft(
        [_option(lead_time_estimate=None)], _requirement(product_type="", delivery_days=None)
    )
    assert "Product: Not confirmed." in body
    assert "Lead-time estimate and deadline feasibility: Not confirmed." in body
    assert "Requested deadline:" not in body and "Estimated lead time at P" not in body


def test_amount_precision_and_currency_are_not_recomputed_or_rounded():
    quote = QuoteCalculation(
        quantity=1200, currency="EUR", buyer_unit_price=10.123456,
        buyer_total=12345.6789,
    )
    body = format_customer_quote_draft([_option(quote=quote)], _requirement())
    assert "Buyer unit price: EUR 10.123456." in body
    assert "Total amount: EUR 12,345.6789." in body
    assert "USD" not in body


@pytest.mark.parametrize("value", [0.0, 12000.0, 12001.25, 12345.6789, 10.123456, 1.23456789e-7, 1.23456789e20])
def test_grouped_amount_display_preserves_exact_stored_decimal_value(value):
    displayed = _display_amount(value)
    assert Decimal(displayed.replace(",", "")) == Decimal(str(value))
    assert "e" not in displayed.lower()


def test_moq_billing_is_distinguished_from_requested_quantity():
    quote = QuoteCalculation(
        quantity=1200, moq=1500, currency="USD", buyer_unit_price=10.0, buyer_total=15000.0,
    )
    body = format_customer_quote_draft([_option(quote=quote)], _requirement())
    assert "Requested quantity: 1200 pcs." in body
    assert "Minimum billable quantity: 1500 pcs." in body
    assert "Total amount: USD 15,000.0." in body


def test_deadline_warning_uses_service_threshold_and_does_not_invent_exceedance():
    assert deadline_warning(_estimate(deadline_days=65), 60) == (
        "The P80 lead-time estimate (66.08 days) exceeds the 65-day deadline."
    )
    assert "exceeds" not in deadline_warning(_estimate(p80_days=58), 60)
    assert "not feasible" in deadline_warning(_estimate(p80_days=58), 60)
    assert deadline_warning(_estimate(deadline_feasible=True), 60) is None
    assert deadline_warning(_estimate(deadline_feasible=None), 60) is None


def test_customer_deadline_facts_remain_separately_bound_when_gltg_threshold_differs():
    estimate = _estimate(deadline_days=65)
    original = estimate.model_dump()
    body = format_customer_quote_draft([_option(lead_time_estimate=estimate)], _requirement())
    assert "Requested deadline: 60 days." in body
    assert "Deadline assessed by GLTG: 65 days." in body
    assert "Estimated lead time at P80: 66.08 days." in body
    assert "Deadline warning: The P80 lead-time estimate exceeds the assessed deadline." in body
    assert "(66.08 days) exceeds the 65-day deadline" not in body
    assert estimate.model_dump() == original
    assert "(66.08 days) exceeds the 65-day deadline" in deadline_warning(estimate, 60)


@pytest.mark.parametrize(("risk", "label"), [
    ("low", "low"),
    ("medium", "medium"),
    ("medium_high", "medium to high"),
    ("high", "high"),
    ("unknown", "not confirmed"),
])
def test_actual_gltg_risk_enums_are_rendered_in_plain_english(risk, label):
    body = format_customer_quote_draft(
        [_option(lead_time_estimate=_estimate(deadline_risk_level=risk))], _requirement()
    )
    assert f"Deadline risk level: {label}." in body
    assert "medium_high" not in body


def test_persisted_draft_uses_requirement_and_quote_without_changing_review_binding(db_session):
    project_repo = ProjectRepository(db_session)
    project = project_repo.create(
        conversation_id="buyer-thread", customer_id="buyer-peer", channel="whatsapp",
        channel_account_id="buyer-account", tenant_id="commercial-tenant",
    )
    requirement = _requirement(project_id=project.project_id)
    project_repo.update_requirement(project.project_id, requirement.model_dump())
    option = _option(project_id=project.project_id)
    project_repo.update_selected_option(project.project_id, option.model_dump())
    selected_before = project.selected_option_json.copy()
    event = OpenClawEvent(
        conversation_id="supplier-thread", channel="email",
        channel_account_id="supplier-account", tenant_id="commercial-tenant",
    )
    ids = _create_customer_quote_email_draft(
        project, event, [option], db_session,
        gpm_guidance={"recommendation": "human_review_required", "confidence": "low"},
    )
    db_session.commit()
    db_session.expire_all()
    draft = DraftRepository(db_session).get(ids[0], tenant_id="commercial-tenant")
    assert draft.status == "pending_approval"
    assert draft.channel == "whatsapp" and draft.channel_account_id == "buyer-account"
    assert draft.conversation_id == "buyer-thread" and draft.target_peer_id == "buyer-peer"
    assert "Requested quantity: 1200 pcs." in draft.message_text
    assert "Buyer unit price: USD 10.0." in draft.message_text
    assert "Total amount: USD 12,000.0." in draft.message_text
    assert "P80 lead-time estimate exceeds the assessed deadline" in draft.message_text
    assert project_repo.get(project.project_id).selected_option_json == selected_before
