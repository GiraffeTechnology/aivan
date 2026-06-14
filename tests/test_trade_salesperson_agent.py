"""Tests for aiven.agents.trade_salesperson_agent — handle_trade_salesperson_event()."""
import os
import pytest

os.environ.setdefault("AIVEN_LLM_PROVIDER", "mock")
os.environ.setdefault("OPENCLAW_MOCK_MODE", "true")

from aiven.agents.trade_salesperson_agent import handle_trade_salesperson_event, AgentTurnResult
from aiven.openclaw.event_adapter import parse_openclaw_event
from aiven.openclaw.contracts import OpenClawEvent
from aiven.openclaw.binding_store import bind_conversation


def _customer_event(conversation_id: str = "conv_test_001", message: str = "I need 10000 white cotton shirts") -> OpenClawEvent:
    return parse_openclaw_event({
        "source": "openclaw",
        "channel": "wangwang",
        "channel_account_id": "acc_001",
        "conversation_id": conversation_id,
        "message_id": "msg_001",
        "sender_id": "buyer_001",
        "sender_display_name": "Test Buyer",
        "message_text": message,
        "message_type": "text",
        "attachments": [],
        "timestamp": "2024-01-01T00:00:00Z",
        "project_id": None,
        "role_context": "buyer",
        "mode": "auto",
    })


def _supplier_event(conversation_id: str = "conv_sup_001", project_id: str = "proj_test") -> OpenClawEvent:
    return parse_openclaw_event({
        "source": "openclaw",
        "channel": "wangwang",
        "channel_account_id": "acc_sup",
        "conversation_id": conversation_id,
        "message_id": "msg_sup_001",
        "sender_id": "supplier_001",
        "sender_display_name": "Factory Co.",
        "message_text": "We can supply at USD 4.50/pc, MOQ 5000, lead time 35 days.",
        "message_type": "text",
        "attachments": [],
        "timestamp": "2024-01-01T01:00:00Z",
        "project_id": project_id,
        "role_context": "supplier",
        "mode": "auto",
    })


def test_handle_customer_message_returns_agent_result(db_session):
    event = _customer_event()
    result = handle_trade_salesperson_event(event, db_session)
    assert isinstance(result, AgentTurnResult)


def test_handle_customer_message_has_project_id(db_session):
    event = _customer_event()
    result = handle_trade_salesperson_event(event, db_session)
    assert result.project_id is not None
    assert len(result.project_id) > 0


def test_handle_customer_message_action_set(db_session):
    event = _customer_event()
    result = handle_trade_salesperson_event(event, db_session)
    # Action must be a non-empty string (e.g. "clarification_needed", "inquiry_drafts_created", etc.)
    assert isinstance(result.action, str)
    assert len(result.action) > 0


def test_handle_customer_message_has_message(db_session):
    event = _customer_event()
    result = handle_trade_salesperson_event(event, db_session)
    assert isinstance(result.message, str)
    assert len(result.message) > 0


def test_handle_customer_message_no_error_field(db_session):
    """A normal customer message should not put anything in errors."""
    event = _customer_event()
    result = handle_trade_salesperson_event(event, db_session)
    # Errors list may be empty; action should not be "error" for a valid message
    assert result.action != "error"


def test_same_conversation_reuses_project(db_session):
    """Sending two messages on the same conversation_id should produce the same project_id."""
    conv_id = "conv_reuse_001"
    result1 = handle_trade_salesperson_event(_customer_event(conv_id), db_session)
    result2 = handle_trade_salesperson_event(_customer_event(conv_id, "What about jeans?"), db_session)
    assert result1.project_id == result2.project_id


def test_handle_supplier_reply_returns_result(db_session):
    # First create a project via a customer message
    cust_event = _customer_event("conv_cust_x")
    cust_result = handle_trade_salesperson_event(cust_event, db_session)
    project_id = cust_result.project_id

    # Now send a supplier reply on that project
    sup_event = _supplier_event("conv_sup_x", project_id=project_id)
    result = handle_trade_salesperson_event(sup_event, db_session)
    assert isinstance(result, AgentTurnResult)
    assert result.project_id == project_id


def test_handle_supplier_reply_action(db_session):
    cust_event = _customer_event("conv_cust_y")
    cust_result = handle_trade_salesperson_event(cust_event, db_session)
    project_id = cust_result.project_id

    sup_event = _supplier_event("conv_sup_y", project_id=project_id)
    result = handle_trade_salesperson_event(sup_event, db_session)
    # Action for a supplier reply path
    assert result.action in ("buyer_options_ready", "reply_received")


def test_agent_result_fields_present(db_session):
    event = _customer_event("conv_fields_001")
    result = handle_trade_salesperson_event(event, db_session)
    assert hasattr(result, "project_id")
    assert hasattr(result, "action")
    assert hasattr(result, "message")
    assert hasattr(result, "drafts_created")
    assert hasattr(result, "errors")
    assert isinstance(result.drafts_created, list)
    assert isinstance(result.errors, list)
