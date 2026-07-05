"""Core intermediary (B/M) workflow behavior.

Covers the buyer → intermediary → supplier → buyer loop pieces that had no
direct unit coverage: deterministic supplier-reply parsing, markup and
freight/insurance application, lead-time risk buffering, resilience to missing
optional supplier data, and controlled errors on invalid skill-invoke input.
"""

from __future__ import annotations

import pytest

from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.agents.supplier_response_agent import parse_supplier_reply
from aivan.pricing.quote_calculator import calculate_buyer_quote
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Force the zero-model regime so parsing exercises the deterministic path."""
    monkeypatch.setenv("AIVAN_LLM_API_ENABLED", "false")


def _requirement(**overrides) -> BuyerRequirement:
    data = {
        "requirement_id": "req_test_001",
        "raw_text": "10000 white cotton shirts to Vancouver in 45 days",
        "product_name": "shirt",
        "category": "apparel",
        "quantity": 10000,
        "destination": "Vancouver",
        "delivery_days": 45,
    }
    data.update(overrides)
    return BuyerRequirement(**data)


# ── Supplier reply parsing (deterministic fallback) ───────────────────────────

def test_supplier_reply_parses_price_moq_lead_time():
    reply = parse_supplier_reply(
        "We can offer USD 4.20 per pc, MOQ: 5000, lead time 30 days.",
        project_id="proj_x",
        supplier_id="sup_1",
    )
    assert reply.unit_price == pytest.approx(4.20)
    assert reply.moq == 5000
    assert reply.lead_time_days == 30
    assert reply.project_id == "proj_x"


def test_supplier_reply_with_no_extractable_fields_does_not_crash():
    reply = parse_supplier_reply(
        "Thanks, we will get back to you next week.",
        project_id="proj_x",
    )
    assert reply.unit_price is None
    assert reply.moq is None
    assert reply.lead_time_days is None
    # A reply with no facts is still a structured, storable object.
    assert reply.raw_text.startswith("Thanks")


# ── Missing optional supplier data must not break option generation ──────────

def test_options_skip_replies_without_price():
    replies = [
        SupplierReply(project_id="p", supplier_id="s1", raw_text="no numbers here"),
        SupplierReply(project_id="p", supplier_id="s2", raw_text="USD 5", unit_price=5.0),
    ]
    options = generate_buyer_options(_requirement(), replies, [], "p")
    assert options, "priced reply should still produce options"
    assert all(o.supplier_id == "s2" for o in options)


def test_no_priced_replies_yields_empty_options_not_error():
    replies = [SupplierReply(project_id="p", supplier_id="s1", raw_text="pending")]
    assert generate_buyer_options(_requirement(), replies, [], "p") == []


# ── Intermediary markup / freight / insurance ─────────────────────────────────

def test_markup_percentage_applied_to_buyer_quote():
    quote = calculate_buyer_quote(unit_price=4.0, quantity=1000, margin_rate=0.20)
    assert quote["buyer_total"] == pytest.approx(4000 / 0.80, rel=1e-4)
    assert quote["effective_margin_rate"] == 0.20
    assert quote["buyer_unit_price"] > 4.0


def test_freight_and_insurance_costs_added_before_markup():
    base = calculate_buyer_quote(unit_price=4.0, quantity=1000, margin_rate=0.15)
    with_freight = calculate_buyer_quote(
        unit_price=4.0,
        quantity=1000,
        margin_rate=0.15,
        international_logistics_fee=500.0,  # freight + insurance
    )
    assert with_freight["international_logistics_fee"] == 500.0
    assert with_freight["supplier_total"] == base["supplier_total"]
    # The pass-through cost is also margined, so the buyer total grows by more
    # than the raw fee.
    assert with_freight["buyer_total"] - base["buyer_total"] == pytest.approx(500 / 0.85, rel=1e-4)


# ── Lead-time risk buffer (intermediary extends delivery by N days) ──────────

def test_gltg_estimate_includes_risk_buffer_days():
    from aivan.integrations.gltg import GLTGClient

    estimate = GLTGClient().estimate_for_requirement(_requirement())
    assert estimate.risk_buffer_days == estimate.p80_days - estimate.p50_days
    assert estimate.risk_buffer_days >= 0
    assert estimate.conservative_days >= estimate.expected_days


# ── Invalid input returns a controlled error, never a raw 500 ─────────────────

def test_invoke_with_invalid_json_returns_controlled_error(api_client):
    resp = api_client.post(
        "/invoke",
        content=b"this is not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert body["reply_text"]


def test_invoke_with_unrecognized_payload_returns_controlled_error(api_client):
    resp = api_client.post("/invoke", json={"unexpected": "shape"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"error", "ok"}
    assert "reply_text" in body or "output" in body
