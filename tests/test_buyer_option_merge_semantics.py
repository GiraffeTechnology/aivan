"""Combined buyer-option boundaries; synthetic fixtures, not service acceptance."""
from __future__ import annotations

import pytest

from aivan.agents import buyer_option_agent as agent
from aivan.execution.source_quote import source_quote_reference
from aivan.schemas.leadtime import LeadTimeEstimate
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply


@pytest.mark.parametrize("quantity", [None, 0, -1, 2])
@pytest.mark.parametrize("currencies", [("GBP", "GBP", "GBP", "GBP"), ("GBP", "USD", "", "GBP")])
@pytest.mark.parametrize("unit", ["pcs", "kg"])
@pytest.mark.parametrize("hide_price", [False, True])
def test_merged_quantity_risk_provenance_and_comparability_boundaries(
    monkeypatch, quantity, currencies, unit, hide_price,
):
    monkeypatch.setenv("AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER", str(hide_price).lower())
    requirement = BuyerRequirement(
        project_id="merge-case", quantity=quantity, quantity_unit=unit, delivery_days=2,
    )
    replies = [SupplierReply(
        project_id="merge-case", supplier_id=f"supplier-{i}",
        candidate_id=f"candidate-{i}", raw_text=f"Synthetic source quote {i}",
        unit_price=price, currency=currencies[i], moq=10,
        risks=["lead_time_too_aggressive"] if i == 0 else ["unverified note"],
    ) for i, price in enumerate([0.0, 0.0042, 2.5, 5.0])]
    lead = LeadTimeEstimate(
        estimate_id="synthetic-merge-estimate", project_id="merge-case",
        supplier_id="supplier-0", category="apparel",
        calculated_lead_time_days=1.25, expected_days=1.25, conservative_days=2.75,
        p50_days=1.25, p80_days=2.75, p90_days=3.25, risk_buffer_days=1.5,
        deadline_feasible=False, deadline_risk_level="high",
    )
    before = [reply.model_dump() for reply in replies]
    calls = []
    calculate = agent.calculate_buyer_quote

    def capture(*args, **kwargs):
        calls.append(kwargs)
        return calculate(*args, **kwargs)

    monkeypatch.setattr(agent, "calculate_buyer_quote", capture)
    options = agent.generate_buyer_options(requirement, replies, [lead], "merge-case")
    assert len(options) == 3
    assert len({option.supplier_id for option in options}) == 3
    assert all(option.risk_level == "unknown" for option in options)
    assert all(option.option_type != "lowest_cost" or option.supplier_id == "supplier-0"
               for option in options)
    if unit != "pcs" or len(set(currencies)) != 1:
        assert all(option.option_type != "lowest_cost" for option in options)
        assert all(any("not directly comparable" in note for note in option.warnings)
                   for option in options)
    for option in options:
        reply = next(reply for reply in replies if reply.supplier_id == option.supplier_id)
        assert option.candidate_id == reply.candidate_id
        assert option.source_quote_reference == source_quote_reference(reply)
        assert all(f"Parsed reply risk note: {note}" in option.warnings for note in reply.risks)
        if quantity is None or quantity <= 0:
            assert option.quote is None
            assert any("quantity is not confirmed" in note for note in option.warnings)
        else:
            assert option.quote.quantity == quantity
            assert option.quote.moq == 10
            assert option.quote.currency == reply.currency
            assert option.quote.unit_price == (0.0 if hide_price else reply.unit_price)
            assert any("below supplier MOQ" in note for note in option.warnings)
    if quantity is None or quantity <= 0:
        assert calls == []
    else:
        assert len(calls) == 3
        assert all(call["quantity"] == quantity for call in calls)
    fastest = next(option for option in options if option.supplier_id == "supplier-0")
    assert fastest.lead_time_estimate.model_dump() == lead.model_dump()
    assert fastest.lead_time_estimate.earliest_possible_days is None
    assert fastest.deadline_feasible is False
    assert fastest.deadline_risk_level == "high"
    assert "Supplier's stated lead time appears aggressive vs calculated estimate." in fastest.warnings
    assert [reply.model_dump() for reply in replies] == before
