from __future__ import annotations

import pytest

from aivan.db.repositories.draft_repo import DraftRepository
from aivan.openclaw.outbound_approval import send_if_approved
from aivan.openclaw.email_transport import fetch_real_test_pop3_messages, redact_secret


def _draft(db, *, target: str, status: str = "approved") -> str:
    repo = DraftRepository(db)
    draft = repo.create(
        "proj_email_test",
        {
            "conversation_id": "conv_email_test",
            "channel": "email",
            "target_peer_id": target,
            "target_role": "supplier",
            "message_text": (
                "Subject: RFQ: 5,000 High-Quality Plaid Shirts for Delivery to Tokyo Within 45 Days\n\n"
                "Dear Michael,\n\n"
                "Please quote 5,000 high-quality plaid shirts for delivery to Tokyo within 45 days."
            ),
            "status": status,
            "created_by_agent": "test",
        },
    )
    if status == "approved":
        # Explicit synthetic human-approval proof for transport-only tests.
        from aivan.execution.draft_preview import bind_approval, create_preview
        draft.status = "pending_approval"
        proof, _ = create_preview(db, draft, "en")
        draft.status = "approved"
        draft.approval_id = "synthetic-smtp-approval"
        bind_approval(db, draft, proof)
    db.commit()
    return draft.draft_id


def _real_test_env(monkeypatch):
    monkeypatch.setenv("AIVAN_EMAIL_SEND_MODE", "real_test")
    monkeypatch.setenv("AIVAN_EMAIL_GATEWAY", "openclaw_real_test")
    monkeypatch.setenv("AIVAN_EMAIL_ALLOWED_RECIPIENTS", "approved.recipient@example.invalid")
    monkeypatch.setenv("AIVAN_PRESET_MAILBOX", "sender@example.invalid")
    monkeypatch.setenv("AIVAN_SMTP_HOST", "smtp.example.invalid")
    monkeypatch.setenv("AIVAN_SMTP_PORT", "465")
    monkeypatch.setenv("AIVAN_SMTP_USE_SSL", "true")
    monkeypatch.setenv("AIVAN_SMTP_USE_TLS", "false")
    monkeypatch.setenv("AIVAN_SMTP_USERNAME", "sender@example.invalid")
    monkeypatch.setenv("AIVAN_SMTP_PASSWORD", "super-secret-app-password")
    monkeypatch.setenv("AIVAN_POP3_HOST", "pop3.example.invalid")
    monkeypatch.setenv("AIVAN_POP3_PORT", "995")
    monkeypatch.setenv("AIVAN_POP3_USE_SSL", "true")
    monkeypatch.setenv("AIVAN_POP3_USERNAME", "sender@example.invalid")
    monkeypatch.setenv("AIVAN_POP3_PASSWORD", "super-secret-app-password")


def test_real_test_email_blocks_unapproved_recipient(db_session, monkeypatch):
    _real_test_env(monkeypatch)
    calls = {"smtp": 0}

    class _SMTP:
        def __init__(self, *args, **kwargs):
            calls["smtp"] += 1

    monkeypatch.setattr("aivan.openclaw.email_transport.smtplib.SMTP_SSL", _SMTP)

    draft_id = _draft(db_session, target="supplier@example.com")
    result = send_if_approved(draft_id, db_session)

    assert result.success is False
    assert "allowlisted" in (result.error or "")
    assert calls["smtp"] == 0
    assert DraftRepository(db_session).get(draft_id).status == "send_failed"


def test_real_test_email_requires_openclaw_gateway_marker(db_session, monkeypatch):
    _real_test_env(monkeypatch)
    monkeypatch.delenv("AIVAN_EMAIL_GATEWAY", raising=False)
    calls = {"smtp": 0}

    class _SMTP:
        def __init__(self, *args, **kwargs):
            calls["smtp"] += 1

    monkeypatch.setattr("aivan.openclaw.email_transport.smtplib.SMTP_SSL", _SMTP)

    draft_id = _draft(db_session, target="approved.recipient@example.invalid")
    result = send_if_approved(draft_id, db_session)

    assert result.success is False
    assert "AIVAN_EMAIL_GATEWAY" in (result.error or "")
    assert calls["smtp"] == 0
    assert DraftRepository(db_session).get(draft_id).status == "send_failed"


def test_real_test_email_requires_explicit_smtp_endpoint(db_session, monkeypatch):
    _real_test_env(monkeypatch)
    monkeypatch.delenv("AIVAN_SMTP_HOST", raising=False)
    calls = {"smtp": 0}

    class _SMTP:
        def __init__(self, *args, **kwargs):
            calls["smtp"] += 1

    monkeypatch.setattr("aivan.openclaw.email_transport.smtplib.SMTP_SSL", _SMTP)

    draft_id = _draft(db_session, target="approved.recipient@example.invalid")
    result = send_if_approved(draft_id, db_session)

    assert result.success is False
    assert "AIVAN_SMTP_HOST is not configured" in (result.error or "")
    assert calls["smtp"] == 0
    assert DraftRepository(db_session).get(draft_id).status == "send_failed"


def test_real_test_email_allows_configured_recipient_only(db_session, monkeypatch):
    _real_test_env(monkeypatch)
    sent = {}

    class _SMTP:
        def __init__(self, host, port, timeout):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, username, password):
            sent["username"] = username
            sent["password_seen"] = bool(password)

        def send_message(self, msg, from_addr=None, to_addrs=None):
            sent["from"] = msg["From"]
            sent["to"] = msg["To"]
            sent["envelope_from"] = from_addr
            sent["envelope_to"] = to_addrs
            sent["subject"] = msg["Subject"]
            sent["body"] = msg.get_content()
            return {}

    monkeypatch.setattr("aivan.openclaw.email_transport.smtplib.SMTP_SSL", _SMTP)

    draft_id = _draft(db_session, target="Buyer <approved.recipient@example.invalid>")
    result = send_if_approved(draft_id, db_session)

    assert result.success is True
    assert DraftRepository(db_session).get(draft_id).status == "sent"
    assert sent["from"] == "sender@example.invalid"
    assert sent["to"] == "Buyer <approved.recipient@example.invalid>"
    assert sent["envelope_from"] == "sender@example.invalid"
    assert sent["envelope_to"] == ["approved.recipient@example.invalid"]
    assert sent["username"] == "sender@example.invalid"
    assert sent["subject"] == "RFQ: 5,000 High-Quality Plaid Shirts for Delivery to Tokyo Within 45 Days"
    assert "Dear Michael" in sent["body"]


def test_real_test_email_blocks_multiple_recipients(db_session, monkeypatch):
    _real_test_env(monkeypatch)
    calls = {"smtp": 0}

    class _SMTP:
        def __init__(self, *args, **kwargs):
            calls["smtp"] += 1

    monkeypatch.setattr("aivan.openclaw.email_transport.smtplib.SMTP_SSL", _SMTP)

    draft_id = _draft(
        db_session,
        target="approved.recipient@example.invalid, other@example.invalid",
    )
    result = send_if_approved(draft_id, db_session)

    assert result.success is False
    assert "exactly one recipient" in (result.error or "")
    assert calls["smtp"] == 0
    assert DraftRepository(db_session).get(draft_id).status == "send_failed"


def test_real_test_email_blocks_sender_username_mismatch(db_session, monkeypatch):
    _real_test_env(monkeypatch)
    monkeypatch.setenv("AIVAN_PRESET_MAILBOX", "other@example.com")
    calls = {"smtp": 0}

    class _SMTP:
        def __init__(self, *args, **kwargs):
            calls["smtp"] += 1

    monkeypatch.setattr("aivan.openclaw.email_transport.smtplib.SMTP_SSL", _SMTP)

    draft_id = _draft(db_session, target="approved.recipient@example.invalid")
    result = send_if_approved(draft_id, db_session)

    assert result.success is False
    assert "sender must match SMTP username" in (result.error or "")
    assert calls["smtp"] == 0
    assert DraftRepository(db_session).get(draft_id).status == "send_failed"


def test_email_secrets_not_logged(monkeypatch):
    monkeypatch.setenv("AIVAN_SMTP_PASSWORD", "super-secret-app-password")
    monkeypatch.setenv("AIVAN_POP3_PASSWORD", "super-secret-app-password")
    text = redact_secret("SMTP/POP3 failed with password super-secret-app-password")
    assert "super-secret-app-password" not in text
    assert "<redacted>" in text


def test_no_send_before_approval(db_session, monkeypatch):
    _real_test_env(monkeypatch)
    calls = {"smtp": 0}

    class _SMTP:
        def __init__(self, *args, **kwargs):
            calls["smtp"] += 1

    monkeypatch.setattr("aivan.openclaw.email_transport.smtplib.SMTP_SSL", _SMTP)

    draft_id = _draft(
        db_session,
        target="approved.recipient@example.invalid",
        status="pending_approval",
    )
    result = send_if_approved(draft_id, db_session)

    assert result.success is False
    assert "not approved" in (result.error or "")
    assert calls["smtp"] == 0
    assert DraftRepository(db_session).get(draft_id).status == "pending_approval"


def test_real_test_pop3_receive_requires_openclaw_gateway_marker(monkeypatch):
    _real_test_env(monkeypatch)
    monkeypatch.delenv("AIVAN_EMAIL_GATEWAY", raising=False)

    try:
        fetch_real_test_pop3_messages()
    except ValueError as exc:
        assert "AIVAN_EMAIL_GATEWAY" in str(exc)
    else:
        raise AssertionError("POP3 receive should require explicit OpenClaw real-test marker")


def test_real_test_pop3_receive_requires_explicit_endpoint(monkeypatch):
    _real_test_env(monkeypatch)
    monkeypatch.delenv("AIVAN_POP3_HOST", raising=False)
    calls = {"pop3": 0}

    class _POP3:
        def __init__(self, *args, **kwargs):
            calls["pop3"] += 1

    monkeypatch.setattr("aivan.openclaw.email_transport.poplib.POP3_SSL", _POP3)

    with pytest.raises(ValueError, match="AIVAN_POP3_HOST is not configured"):
        fetch_real_test_pop3_messages()
    assert calls["pop3"] == 0


def test_real_test_pop3_receive_fetches_recent_messages(monkeypatch):
    _real_test_env(monkeypatch)
    calls = {}

    raw_message = (
        b"From: Buyer <approved.recipient@example.invalid>\r\n"
        b"To: sender@example.invalid\r\n"
        b"Subject: Re: RFQ: 5,000 High-Quality Plaid Shirts\r\n"
        b"Date: Fri, 03 Jul 2026 04:20:00 +0000\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Quote received. We can reply within 60 minutes.\r\n"
    )

    class _POP3:
        def __init__(self, host, port, timeout):
            calls["host"] = host
            calls["port"] = port
            calls["timeout"] = timeout

        def user(self, username):
            calls["username"] = username

        def pass_(self, password):
            calls["password_seen"] = bool(password)

        def stat(self):
            return (1, len(raw_message))

        def retr(self, index):
            calls["retr_index"] = index
            return b"+OK", raw_message.split(b"\r\n"), len(raw_message)

        def quit(self):
            calls["quit"] = True

    monkeypatch.setattr("aivan.openclaw.email_transport.poplib.POP3_SSL", _POP3)

    messages = fetch_real_test_pop3_messages(limit=5)

    assert calls["host"] == "pop3.example.invalid"
    assert calls["port"] == 995
    assert calls["username"] == "sender@example.invalid"
    assert calls["password_seen"] is True
    assert calls["retr_index"] == 1
    assert calls["quit"] is True
    assert len(messages) == 1
    assert messages[0].from_address == "Buyer <approved.recipient@example.invalid>"
    assert messages[0].to_address == "sender@example.invalid"
    assert messages[0].subject == "Re: RFQ: 5,000 High-Quality Plaid Shirts"
    assert "within 60 minutes" in messages[0].body_excerpt


def test_real_test_pop3_receive_redacts_secret_on_error(monkeypatch):
    _real_test_env(monkeypatch)

    class _POP3:
        def __init__(self, *args, **kwargs):
            pass

        def user(self, username):
            pass

        def pass_(self, password):
            raise RuntimeError(f"bad password {password}")

        def quit(self):
            pass

    monkeypatch.setattr("aivan.openclaw.email_transport.poplib.POP3_SSL", _POP3)

    try:
        fetch_real_test_pop3_messages()
    except RuntimeError as exc:
        assert "super-secret-app-password" not in str(exc)
        assert "<redacted>" in str(exc)
    else:
        raise AssertionError("POP3 receive failure should redact configured secrets")
