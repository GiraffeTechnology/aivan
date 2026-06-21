"""Tests for LINE Push adapter (Workstream B)."""
from __future__ import annotations
import os
import pytest
from aivan.channels.line import send_line_push, verify_line_signature


def test_line_disabled_by_default():
    os.environ.pop("AIVAN_LINE_ENABLED", None)
    result = send_line_push("U123", "hello")
    assert not result.success
    assert "not enabled" in result.error


def test_line_mock_mode_success():
    os.environ["AIVAN_LINE_ENABLED"] = "true"
    os.environ["AIVAN_LINE_MODE"] = "mock"
    result = send_line_push("U_test_user", "Test message")
    assert result.success
    assert result.message_id.startswith("mock_line_")
    assert result.sent_at


def test_line_missing_token_when_live():
    os.environ["AIVAN_LINE_ENABLED"] = "true"
    os.environ["AIVAN_LINE_MODE"] = "live"
    os.environ.pop("LINE_CHANNEL_ACCESS_TOKEN", None)
    result = send_line_push("U123", "hello")
    assert not result.success
    assert "LINE_CHANNEL_ACCESS_TOKEN" in result.error


def test_verify_signature_no_secret():
    os.environ.pop("LINE_CHANNEL_SECRET", None)
    assert not verify_line_signature(b"body", "sig")


def test_verify_signature_correct():
    import hmac, hashlib, base64
    secret = "test_secret_key"
    os.environ["LINE_CHANNEL_SECRET"] = secret
    body = b'{"events":[]}'
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode()
    assert verify_line_signature(body, signature)


def test_verify_signature_wrong():
    os.environ["LINE_CHANNEL_SECRET"] = "correct_secret"
    assert not verify_line_signature(b"body", "wrong_signature")
