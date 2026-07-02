"""P0-1: llm_structured is provisional, not authoritative (PR #29)."""
from __future__ import annotations

from aivan.execution.safety import evaluate_requirement_readiness
from aivan.rfq import semantic_sources
from aivan.schemas.requirement import BuyerRequirement


def _req(dest_source: str = "", product_source: str = "") -> BuyerRequirement:
    req = BuyerRequirement(
        raw_text="Order 5000 plaid shirts to Osaka within 45 days.",
        product_type="plaid shirt",
        quantity=5000,
        destination="Osaka",
        delivery_days=45,
    )
    sources = {}
    if product_source:
        sources["product_type"] = product_source
    if dest_source:
        sources["destination"] = dest_source
    req.extra["field_sources"] = sources
    return req


def test_llm_structured_is_not_in_authoritative_sources():
    assert "llm_structured" not in semantic_sources.AUTHORITATIVE_SOURCES
    assert "llm_structured" in semantic_sources.PROVISIONAL_SOURCES
    assert "local_llm_candidate" in semantic_sources.PROVISIONAL_SOURCES


def test_llm_structured_destination_is_not_authoritative():
    req = _req(dest_source="llm_structured", product_source="language_skill")
    assert not semantic_sources.has_authoritative_destination(req)
    assert semantic_sources.is_provisional(req, "destination")
    gate = evaluate_requirement_readiness(req)
    assert not gate.ready
    assert "destination" in gate.missing_fields
    assert gate.next_action == "pending_destination_confirmation"


def test_llm_structured_product_is_not_authoritative():
    req = _req(dest_source="language_skill", product_source="llm_structured")
    assert not semantic_sources.has_authoritative_product(req)
    gate = evaluate_requirement_readiness(req)
    assert not gate.ready
    assert "product" in gate.missing_fields


def test_local_llm_candidate_requires_confirmation_before_gltg():
    from aivan.execution.safety import RequirementNotReady, assert_ready_for_gltg

    req = _req(dest_source="local_llm_candidate", product_source="local_llm_candidate")
    gate = evaluate_requirement_readiness(req)
    assert not gate.ready
    assert gate.next_action.startswith("pending_")
    import pytest

    with pytest.raises(RequirementNotReady):
        assert_ready_for_gltg(req)


def test_language_skill_destination_remains_authoritative():
    req = _req(dest_source="language_skill", product_source="language_skill")
    assert semantic_sources.has_authoritative_destination(req)
    gate = evaluate_requirement_readiness(req)
    assert gate.ready


def test_operator_confirmed_destination_remains_authoritative():
    req = _req(dest_source="operator_confirmed", product_source="operator_confirmed")
    assert semantic_sources.has_authoritative_destination(req)
    assert semantic_sources.has_authoritative_product(req)
    gate = evaluate_requirement_readiness(req)
    assert gate.ready
