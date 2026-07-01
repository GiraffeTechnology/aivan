"""Screenshot regression + RFQ execution reliability tests (PRD §17, §18.3).

These pin the two observed production failures:
  * Chinese RFQ replied "ready for approval to TBD" with English debug text.
  * English Osaka RFQ returned a generic backend dependency error.

They monkeypatch the structuring step to control provenance so the tests target
the EXECUTION GATE wiring (which §17 is about), not the extraction layer.
"""
from __future__ import annotations

import pytest

import aivan.execution.rfq_execution as rfq_execution
from aivan.execution.rfq_execution import create_rfq_from_event
from aivan.integrations.gltg import GLTGUnavailableError
from aivan.openclaw.contracts import OpenClawEvent
from aivan.schemas.requirement import BuyerRequirement


def _event(text: str, lang_zh: bool = True) -> OpenClawEvent:
    return OpenClawEvent(
        source="openclaw",
        channel="wechat",
        conversation_id="conv_regression_001",
        message_id="msg_regression_001",
        sender_id="user_001",
        sender_display_name="Operator",
        message_text=text,
        role_context="user",
        mode="command",
    )


def _authoritative_req(**overrides) -> BuyerRequirement:
    req = BuyerRequirement(
        project_id="",
        raw_text=overrides.pop("raw_text", "询价 5000 件格子衬衫，45天交东京，高品质"),
        language=overrides.pop("language", "zh"),
        category="apparel",
        product_type="plaid shirt",
        quantity=5000,
        destination="Tokyo",
        delivery_days=45,
    )
    req.extra["field_sources"] = {"product_type": "language_skill", "destination": "language_skill"}
    req.extra["quality_level"] = "high"
    for k, v in overrides.items():
        setattr(req, k, v)
    return req


def _unresolved_dest_req() -> BuyerRequirement:
    req = BuyerRequirement(
        raw_text="询价 5000 件格子衬衫，45天交东京，高品质",
        language="zh",
        category="apparel",
        product_type="plaid shirt",
        quantity=5000,
        destination="",
        delivery_days=45,
    )
    req.extra["field_sources"] = {"product_type": "language_skill", "destination": "raw_text_only"}
    req.extra["destination_raw"] = "东京"
    return req


def test_chinese_rfq_tokyo_plaid_high_quality_e2e(db_session, monkeypatch):
    monkeypatch.setattr(rfq_execution, "structure_customer_requirement_with_llm",
                        lambda **kw: _authoritative_req())
    result = create_rfq_from_event(_event("询价 5000 件格子衬衫，45天交东京，高品质"), db_session)

    assert result.action == "pending_email_approval"
    assert result.drafts_created
    assert result.requirement["destination"] == "Tokyo"
    assert result.requirement["quantity"] == 5000
    assert result.requirement["delivery_days"] == 45


def test_chinese_rfq_does_not_reply_tbd_or_english_debug_text(db_session, monkeypatch):
    monkeypatch.setattr(rfq_execution, "structure_customer_requirement_with_llm",
                        lambda **kw: _authoritative_req())
    result = create_rfq_from_event(_event("询价 5000 件格子衬衫，45天交东京，高品质"), db_session)
    reply = result.user_control_message

    assert "TBD" not in reply
    assert "Strategy=" not in reply
    assert "draft_" not in reply
    assert "GLTG P50" not in reply
    assert "RFQ 已创建" in reply or "RFQ 已记录" in reply
    assert "仍需人工审批" in reply or "等待人工审批" in reply


def test_chinese_rfq_unresolved_destination_blocks_gltg_and_drafts(db_session, monkeypatch):
    monkeypatch.setattr(rfq_execution, "structure_customer_requirement_with_llm",
                        lambda **kw: _unresolved_dest_req())

    def _boom(*a, **k):
        raise AssertionError("GLTG must not be called before requirement gate passes")

    monkeypatch.setattr(rfq_execution.GLTGClient, "simulate", _boom)

    result = create_rfq_from_event(_event("询价 5000 件格子衬衫，45天交东京，高品质"), db_session)

    assert result.action == "pending_destination_confirmation"
    assert result.drafts_created == []
    assert result.gltg_simulation.p50_days == 0  # GLTG not run
    reply = result.user_control_message
    assert "东京" in reply
    assert "目的地" in reply
    assert "TBD" not in reply


def test_english_osaka_rfq_does_not_generic_backend_error(db_session, monkeypatch):
    req = _authoritative_req(
        raw_text="Inquiry: Order 5000 plaid shirts, to be shipped to Osaka within 45 days.",
        language="en",
        destination="Osaka",
    )
    monkeypatch.setattr(rfq_execution, "structure_customer_requirement_with_llm", lambda **kw: req)

    result = create_rfq_from_event(
        _event("Inquiry: Order 5000 plaid shirts, to be shipped to Osaka within 45 days."),
        db_session,
    )

    assert result.action in {
        "pending_email_approval",
        "pending_supplier_selection",
        "pending_dependency_recovery",
    }
    assert result.requirement["destination"] == "Osaka"
    assert "后端依赖错误" not in result.user_control_message
    assert "后端依赖错误" not in result.message


def test_gltg_unavailable_returns_structured_dependency_recovery(db_session, monkeypatch):
    monkeypatch.setattr(rfq_execution, "structure_customer_requirement_with_llm",
                        lambda **kw: _authoritative_req(language="en", destination="Osaka"))

    def _unavailable(*a, **k):
        raise GLTGUnavailableError("GLTG service down")

    monkeypatch.setattr(rfq_execution.GLTGClient, "simulate", _unavailable)

    result = create_rfq_from_event(_event("Order 5000 plaid shirts to Osaka in 45 days", lang_zh=False), db_session)

    assert result.action == "pending_dependency_recovery"
    assert result.drafts_created == []
    reply = result.user_control_message
    assert "GLTG" in reply
    assert "后端依赖错误" not in reply
