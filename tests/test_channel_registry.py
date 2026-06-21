"""Tests for channel send-mode registry (Workstream A)."""
from __future__ import annotations
import pytest
from aivan.channels.registry import CHANNEL_SEND_MODE, get_send_mode


def test_email_is_auto():
    assert CHANNEL_SEND_MODE["email"] == "auto"
    assert get_send_mode("email") == "auto"


def test_line_is_auto():
    assert CHANNEL_SEND_MODE["line"] == "auto"
    assert get_send_mode("line") == "auto"


def test_wechat_is_guided_relay():
    assert CHANNEL_SEND_MODE["wechat"] == "guided_relay"
    assert get_send_mode("wechat") == "guided_relay"


def test_wangwang_is_guided_relay():
    assert CHANNEL_SEND_MODE["wangwang"] == "guided_relay"
    assert get_send_mode("wangwang") == "guided_relay"


def test_whatsapp_not_registered():
    """WhatsApp must not appear in the registry."""
    assert "whatsapp" not in CHANNEL_SEND_MODE
    assert get_send_mode("whatsapp") is None


def test_unknown_channel_returns_none():
    assert get_send_mode("unknown_channel_xyz") is None


def test_case_insensitive():
    assert get_send_mode("LINE") == "auto"
    assert get_send_mode("WeChat") == "guided_relay"


def test_empty_string_returns_none():
    assert get_send_mode("") is None
    assert get_send_mode(None) is None
