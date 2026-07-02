"""Deterministic operator reply renderer tests (PRD §9)."""
from __future__ import annotations

from aivan.rfq.operator_reply import render_operator_reply
from aivan.schemas.rfq import (
    GiraffeContext,
    GLTGSimulation,
    RFQExecutionResult,
    RFQStrategy,
    SupplierRoutingDecision,
    FallbackTrigger,
)


def _gltg() -> GLTGSimulation:
    return GLTGSimulation(
        p50_days=30, p80_days=38, p90_days=45, minimum_feasible_days=25,
        supplier_set_feasibility="sufficient", known_suppliers_first_feasibility="feasible",
        public_bidding_time_cost_days=5, fallback_trigger_recommendation=FallbackTrigger(),
        selected_confidence_days=38,
    )


def _result(action: str, requirement: dict, drafts: list[str], user_message: str = "") -> RFQExecutionResult:
    return RFQExecutionResult(
        project_id="p1", event_type="user_command", action=action, message="",
        strategy=RFQStrategy(), requirement=requirement, giraffe_context=GiraffeContext(),
        gltg_simulation=_gltg(), supplier_routing=SupplierRoutingDecision(),
        drafts_created=drafts, user_control_message=user_message,
    )


def _chinese_requirement() -> dict:
    return {
        "raw_text": "询价 5000 件格子衬衫，45天交东京，高品质",
        "language": "zh", "product_type": "格子衬衫", "quantity": 5000,
        "quantity_unit": "件", "destination": "Tokyo", "delivery_days": 45,
        "extra": {"quality_level": "high", "destination_raw": "东京"},
    }


def test_chinese_input_gets_chinese_reply_no_debug_fields():
    result = _result("pending_email_approval", _chinese_requirement(), ["draft_abc", "draft_def"])
    reply = render_operator_reply(result, "zh")

    assert "RFQ 已创建" in reply
    assert "等待人工审批" in reply or "仍需人工审批" in reply
    # No internal debug leakage.
    assert "TBD" not in reply
    assert "Strategy=" not in reply
    assert "GLTG P50" not in reply
    assert "draft_abc" not in reply and "draft_def" not in reply
    # Draft count is allowed instead of raw ids.
    assert "草稿数量：2" in reply
    assert "Tokyo" in reply


def test_reply_does_not_claim_drafts_when_none_created():
    req = _chinese_requirement()
    result = _result("pending_email_approval", req, [])
    reply = render_operator_reply(result, "zh")
    assert "草稿数量" not in reply  # no drafts => no draft-count claim


def test_destination_confirmation_action_does_not_say_ready():
    req = {"raw_text": "询价 5000 件，45天", "language": "zh", "quantity": 5000, "delivery_days": 45,
           "extra": {"destination_raw": "东京"}}
    result = _result(
        "pending_destination_confirmation", req, [],
        user_message="RFQ 已记录，但目的地尚未确认：请确认交货城市。",
    )
    reply = render_operator_reply(result, "zh")
    assert "等待人工审批" not in reply
    assert "尚未确认" in reply


def test_english_input_gets_english_reply():
    req = {"raw_text": "Order 5000 plaid shirts to Osaka in 45 days.", "language": "en",
           "product_type": "plaid shirt", "quantity": 5000, "quantity_unit": "pcs",
           "destination": "Osaka", "delivery_days": 45, "extra": {}}
    result = _result("pending_email_approval", req, ["draft_x"])
    reply = render_operator_reply(result, "en")
    assert "pending human approval" in reply.lower()
    assert "draft_x" not in reply
    assert "Osaka" in reply
