from __future__ import annotations

from aivan.db.repositories.draft_repo import DraftRepository
from aivan.openclaw.outbound_approval import send_if_approved
from aivan.openclaw.email_transport import redact_secret


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
    db.commit()
    return draft.draft_id


def _real_test_env(monkeypatch):
    monkeypatch.setenv("AIVAN_EMAIL_SEND_MODE", "real_test")
    monkeypatch.setenv("AIVAN_EMAIL_GATEWAY", "openclaw_real_test")
    monkeypatch.setenv("AIVAN_EMAIL_ALLOWED_RECIPIENTS", "mich@giraffe.technology")
    monkeypatch.setenv("AIVAN_PRESET_MAILBOX", "giraffetechnology@163.com")
    monkeypatch.setenv("AIVAN_SMTP_HOST", "smtp.163.com")
    monkeypatch.setenv("AIVAN_SMTP_PORT", "465")
    monkeypatch.setenv("AIVAN_SMTP_USE_SSL", "true")
    monkeypatch.setenv("AIVAN_SMTP_USE_TLS", "false")
    monkeypatch.setenv("AIVAN_SMTP_USERNAME", "giraffetechnology@163.com")
    monkeypatch.setenv("AIVAN_SMTP_PASSWORD", "super-secret-app-password")


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
    assert DraftRepository(db_session).get(draft_id).status == "approved"


def test_real_test_email_requires_openclaw_gateway_marker(db_session, monkeypatch):
    _real_test_env(monkeypatch)
    monkeypatch.delenv("AIVAN_EMAIL_GATEWAY", raising=False)
    calls = {"smtp": 0}

    class _SMTP:
        def __init__(self, *args, **kwargs):
            calls["smtp"] += 1

    monkeypatch.setattr("aivan.openclaw.email_transport.smtplib.SMTP_SSL", _SMTP)

    draft_id = _draft(db_session, target="mich@giraffe.technology")
    result = send_if_approved(draft_id, db_session)

    assert result.success is False
    assert "AIVAN_EMAIL_GATEWAY" in (result.error or "")
    assert calls["smtp"] == 0


def test_real_test_email_allows_mich_giraffe_technology_only(db_session, monkeypatch):
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

    draft_id = _draft(db_session, target="Michael <mich@giraffe.technology>")
    result = send_if_approved(draft_id, db_session)

    assert result.success is True
    assert DraftRepository(db_session).get(draft_id).status == "sent"
    assert sent["from"] == "giraffetechnology@163.com"
    assert sent["to"] == "Michael <mich@giraffe.technology>"
    assert sent["envelope_from"] == "giraffetechnology@163.com"
    assert sent["envelope_to"] == ["mich@giraffe.technology"]
    assert sent["username"] == "giraffetechnology@163.com"
    assert sent["subject"] == "RFQ: 5,000 High-Quality Plaid Shirts for Delivery to Tokyo Within 45 Days"
    assert "Dear Michael" in sent["body"]


def test_real_test_email_blocks_multiple_recipients(db_session, monkeypatch):
    _real_test_env(monkeypatch)
    calls = {"smtp": 0}

    class _SMTP:
        def __init__(self, *args, **kwargs):
            calls["smtp"] += 1

    monkeypatch.setattr("aivan.openclaw.email_transport.smtplib.SMTP_SSL", _SMTP)

    draft_id = _draft(db_session, target="mich@giraffe.technology, other@example.com")
    result = send_if_approved(draft_id, db_session)

    assert result.success is False
    assert "exactly one recipient" in (result.error or "")
    assert calls["smtp"] == 0


def test_real_test_email_blocks_sender_username_mismatch(db_session, monkeypatch):
    _real_test_env(monkeypatch)
    monkeypatch.setenv("AIVAN_PRESET_MAILBOX", "other@example.com")
    calls = {"smtp": 0}

    class _SMTP:
        def __init__(self, *args, **kwargs):
            calls["smtp"] += 1

    monkeypatch.setattr("aivan.openclaw.email_transport.smtplib.SMTP_SSL", _SMTP)

    draft_id = _draft(db_session, target="mich@giraffe.technology")
    result = send_if_approved(draft_id, db_session)

    assert result.success is False
    assert "sender must match SMTP username" in (result.error or "")
    assert calls["smtp"] == 0


def test_email_secrets_not_logged(monkeypatch):
    monkeypatch.setenv("AIVAN_SMTP_PASSWORD", "super-secret-app-password")
    text = redact_secret("SMTP failed with password super-secret-app-password")
    assert "super-secret-app-password" not in text
    assert "<redacted>" in text


def test_no_send_before_approval(db_session, monkeypatch):
    _real_test_env(monkeypatch)
    calls = {"smtp": 0}

    class _SMTP:
        def __init__(self, *args, **kwargs):
            calls["smtp"] += 1

    monkeypatch.setattr("aivan.openclaw.email_transport.smtplib.SMTP_SSL", _SMTP)

    draft_id = _draft(db_session, target="mich@giraffe.technology", status="pending_approval")
    result = send_if_approved(draft_id, db_session)

    assert result.success is False
    assert "not approved" in (result.error or "")
    assert calls["smtp"] == 0
    assert DraftRepository(db_session).get(draft_id).status == "pending_approval"
