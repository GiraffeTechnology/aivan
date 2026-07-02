"""Execution readiness gate tests (PRD §6, §18.2).

Unready requirements must stop before strategy, GLTG, graph persistence, and
supplier drafts. Raw-text-only product/destination is not authoritative.
"""
from __future__ import annotations

import pytest

from aivan.execution.safety import (
    RequirementNotReady,
    assert_ready_for_gltg,
    assert_ready_for_strategy,
    assert_ready_for_supplier_drafts,
    evaluate_requirement_readiness,
)
from aivan.rfq import semantic_sources
from aivan.schemas.requirement import BuyerRequirement


def _authoritative_requirement(**overrides) -> BuyerRequirement:
    req = BuyerRequirement(
        raw_text="Order 5000 plaid shirts to Osaka within 45 days.",
        product_type="plaid shirt",
        quantity=5000,
        destination="Osaka",
        delivery_days=45,
    )
    req.extra["field_sources"] = {
        "product_type": "language_skill",
        "destination": "language_skill",
    }
    for k, v in overrides.items():
        setattr(req, k, v)
    return req


def _raw_text_only_destination() -> BuyerRequirement:
    req = _authoritative_requirement()
    req.extra["field_sources"]["destination"] = "raw_text_only"
    return req


def test_ready_requirement_allows_gltg_and_supplier_drafts():
    req = _authoritative_requirement()
    gate = evaluate_requirement_readiness(req)
    assert gate.ready
    assert gate.next_action == "proceed"
    # Assertions must not raise for a ready requirement.
    assert_ready_for_strategy(req)
    assert_ready_for_gltg(req)
    assert_ready_for_supplier_drafts(req, [{"supplier_id": "s1", "email": "s@x.com"}])


def test_raw_text_only_destination_is_not_authoritative():
    req = _raw_text_only_destination()
    assert not semantic_sources.has_authoritative_destination(req)
    gate = evaluate_requirement_readiness(req)
    assert not gate.ready
    assert "destination" in gate.missing_fields
    assert gate.next_action == "pending_destination_confirmation"


def test_raw_text_only_product_is_not_authoritative():
    req = _authoritative_requirement()
    req.extra["field_sources"]["product_type"] = "raw_text_only"
    assert not semantic_sources.has_authoritative_product(req)
    gate = evaluate_requirement_readiness(req)
    assert not gate.ready
    assert "product" in gate.missing_fields


def test_unresolved_destination_blocks_before_strategy():
    req = _raw_text_only_destination()
    with pytest.raises(RequirementNotReady):
        assert_ready_for_strategy(req)


def test_unresolved_destination_blocks_before_gltg():
    req = _raw_text_only_destination()
    with pytest.raises(RequirementNotReady):
        assert_ready_for_gltg(req)


def test_unresolved_destination_blocks_before_graph_persistence():
    from aivan.execution.safety import assert_ready_for_giraffe_graph

    req = _raw_text_only_destination()
    with pytest.raises(RequirementNotReady):
        assert_ready_for_giraffe_graph(req)


def test_unresolved_destination_blocks_supplier_drafts():
    req = _raw_text_only_destination()
    with pytest.raises(RequirementNotReady):
        assert_ready_for_supplier_drafts(req, [{"supplier_id": "s1", "email": "s@x.com"}])


def test_missing_quantity_blocks():
    req = _authoritative_requirement(quantity=None)
    gate = evaluate_requirement_readiness(req)
    assert not gate.ready
    assert "quantity" in gate.missing_fields


def test_missing_delivery_blocks():
    req = _authoritative_requirement(delivery_days=None, delivery_deadline_iso=None)
    gate = evaluate_requirement_readiness(req)
    assert not gate.ready
    assert "delivery" in gate.missing_fields


def test_confirmation_message_is_language_matched_chinese():
    req = BuyerRequirement(
        raw_text="询价 5000 件格子衬衫，45天，高品质",
        language="zh",
        product_type="格子衬衫",
        quantity=5000,
        delivery_days=45,
    )
    req.extra["field_sources"] = {"product_type": "language_skill", "destination": "raw_text_only"}
    gate = evaluate_requirement_readiness(req)
    assert not gate.ready
    assert "目的地" in gate.operator_message
    assert "GLTG" in gate.operator_message
