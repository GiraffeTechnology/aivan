"""Tests for aiven.openclaw.event_adapter."""
import pytest
from aivan.openclaw.event_adapter import parse_openclaw_event, is_customer_message, is_supplier_reply
from aivan.openclaw.contracts import OpenClawEvent


FULL_CUSTOMER_EVENT = {
    "source": "openclaw",
    "channel": "wangwang",
    "channel_account_id": "acc_001",
    "conversation_id": "conv_abc123",
    "message_id": "msg_001",
    "sender_id": "buyer_001",
    "sender_display_name": "Alice",
    "message_text": "我需要10000件白色纯棉衬衣",
    "message_type": "text",
    "attachments": [],
    "timestamp": "2024-01-01T00:00:00Z",
    "project_id": None,
    "actor_id": None,
    "role_context": "buyer",
    "mode": "auto",
}

FULL_SUPPLIER_EVENT = {
    "source": "openclaw",
    "channel": "wangwang",
    "channel_account_id": "acc_002",
    "conversation_id": "conv_xyz789",
    "message_id": "msg_002",
    "sender_id": "supplier_001",
    "sender_display_name": "Factory ABC",
    "message_text": "我们可以做，单价4.5 USD/件",
    "message_type": "text",
    "attachments": [],
    "timestamp": "2024-01-01T01:00:00Z",
    "project_id": "proj_001",
    "actor_id": None,
    "role_context": "supplier",
    "mode": "auto",
}


# --- parse_openclaw_event ---

def test_parse_returns_openclaw_event():
    event = parse_openclaw_event(FULL_CUSTOMER_EVENT)
    assert isinstance(event, OpenClawEvent)


def test_parse_conversation_id():
    event = parse_openclaw_event(FULL_CUSTOMER_EVENT)
    assert event.conversation_id == "conv_abc123"


def test_parse_sender_id():
    event = parse_openclaw_event(FULL_CUSTOMER_EVENT)
    assert event.sender_id == "buyer_001"


def test_parse_message_text():
    event = parse_openclaw_event(FULL_CUSTOMER_EVENT)
    assert event.message_text == "我需要10000件白色纯棉衬衣"


def test_parse_role_context_buyer():
    event = parse_openclaw_event(FULL_CUSTOMER_EVENT)
    assert event.role_context == "buyer"


def test_parse_role_context_supplier():
    event = parse_openclaw_event(FULL_SUPPLIER_EVENT)
    assert event.role_context == "supplier"


def test_parse_defaults_source():
    event = parse_openclaw_event({"conversation_id": "conv_x"})
    assert event.source == "openclaw"


def test_parse_defaults_mode():
    event = parse_openclaw_event({"conversation_id": "conv_x"})
    assert event.mode == "auto"


def test_parse_project_id_propagated():
    event = parse_openclaw_event(FULL_SUPPLIER_EVENT)
    assert event.project_id == "proj_001"


# --- is_customer_message ---

def test_is_customer_message_buyer_role():
    event = parse_openclaw_event(FULL_CUSTOMER_EVENT)
    assert is_customer_message(event) is True


def test_is_customer_message_auto_mode_no_role():
    event = OpenClawEvent(conversation_id="conv_x", mode="auto", role_context=None)
    assert is_customer_message(event) is True


def test_is_customer_message_customer_role():
    event = OpenClawEvent(conversation_id="conv_x", role_context="customer")
    assert is_customer_message(event) is True


def test_is_customer_message_supplier_role_false():
    event = parse_openclaw_event(FULL_SUPPLIER_EVENT)
    assert is_customer_message(event) is False


# --- is_supplier_reply ---

def test_is_supplier_reply_supplier_role():
    event = parse_openclaw_event(FULL_SUPPLIER_EVENT)
    assert is_supplier_reply(event) is True


def test_is_supplier_reply_seller_role():
    event = OpenClawEvent(conversation_id="conv_x", role_context="seller")
    assert is_supplier_reply(event) is True


def test_is_supplier_reply_buyer_role_false():
    event = parse_openclaw_event(FULL_CUSTOMER_EVENT)
    assert is_supplier_reply(event) is False


def test_is_supplier_reply_no_role_false():
    event = OpenClawEvent(conversation_id="conv_x", role_context=None)
    assert is_supplier_reply(event) is False
