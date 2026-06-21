"""Integration tests for the guided-relay flow (Workstream C)."""
from __future__ import annotations
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("AIVAN_LLM_PROVIDER", "mock")
os.environ.setdefault("OPENCLAW_MOCK_MODE", "true")
os.environ.setdefault("AIVAN_LINE_ENABLED", "true")
os.environ.setdefault("AIVAN_LINE_MODE", "mock")
os.environ.setdefault("AIVAN_EMAIL_MODE", "mock")


@pytest.fixture
def db_session():
    from aivan.db.models import Base
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


# ── Outbound guided-relay path ───────────────────────────────────────────────

def _make_approved_draft(db, channel: str, peer_id: str = "wx_contact_001"):
    from aivan.db.repositories.draft_repo import DraftRepository
    repo = DraftRepository(db)
    d = repo.create(
        project_id="proj_relay_001",
        data={
            "channel": channel,
            "target_peer_id": peer_id,
            "message_text": "Test relay message",
            "created_by_agent": "test",
        },
    )
    repo.approve(d.draft_id)
    db.flush()
    return d


def test_wechat_draft_becomes_awaiting_relay(db_session):
    from aivan.openclaw.outbound_approval import send_draft
    d = _make_approved_draft(db_session, "wechat")
    result = send_draft(d.draft_id, db_session)
    assert result.success
    assert result.action == "awaiting_relay"
    db_session.refresh(d)
    assert d.status == "awaiting_relay"


def test_wangwang_draft_becomes_awaiting_relay(db_session):
    from aivan.openclaw.outbound_approval import send_draft
    d = _make_approved_draft(db_session, "wangwang")
    result = send_draft(d.draft_id, db_session)
    assert result.success
    assert result.action == "awaiting_relay"


def test_email_draft_auto_sent(db_session):
    from aivan.openclaw.outbound_approval import send_draft
    d = _make_approved_draft(db_session, "email", peer_id="buyer@example.com")
    result = send_draft(d.draft_id, db_session)
    assert result.success
    assert result.action == "sent"
    db_session.refresh(d)
    assert d.status == "sent"
    assert d.sent_receipt_json is not None


def test_line_draft_auto_sent(db_session):
    from aivan.openclaw.outbound_approval import send_draft
    d = _make_approved_draft(db_session, "line", peer_id="U_line_user_001")
    result = send_draft(d.draft_id, db_session)
    assert result.success
    assert result.action == "sent"
    db_session.refresh(d)
    assert d.status == "sent"


def test_relay_confirm_transitions_to_relayed(db_session):
    from aivan.openclaw.outbound_approval import send_draft
    from aivan.db.repositories.draft_repo import DraftRepository
    d = _make_approved_draft(db_session, "wechat")
    send_draft(d.draft_id, db_session)
    db_session.flush()

    repo = DraftRepository(db_session)
    relayed = repo.mark_relayed(d.draft_id, confirmed_by="operator")
    assert relayed.status == "relayed"
    assert relayed.relay_confirmed_by == "operator"
    assert relayed.relay_confirmed_at is not None


def test_relay_outbox_lists_awaiting(db_session):
    from aivan.openclaw.outbound_approval import send_draft
    from aivan.db.repositories.draft_repo import DraftRepository
    d = _make_approved_draft(db_session, "wechat")
    send_draft(d.draft_id, db_session)
    db_session.flush()

    repo = DraftRepository(db_session)
    outbox = repo.list_awaiting_relay()
    assert any(c.draft_id == d.draft_id for c in outbox)


def test_relay_outbox_excludes_relayed(db_session):
    from aivan.openclaw.outbound_approval import send_draft
    from aivan.db.repositories.draft_repo import DraftRepository
    d = _make_approved_draft(db_session, "wechat")
    send_draft(d.draft_id, db_session)
    db_session.flush()
    repo = DraftRepository(db_session)
    repo.mark_relayed(d.draft_id)
    outbox = repo.list_awaiting_relay()
    assert not any(c.draft_id == d.draft_id for c in outbox)


# ── Inbound paste path ───────────────────────────────────────────────────────

def test_inbound_create_records_event(db_session):
    from aivan.db.repositories.inbound_repo import InboundRelayRepository
    from aivan.db.repositories.event_repo import ExecutionEventRepository

    inbound_repo = InboundRelayRepository(db_session)
    event_repo = ExecutionEventRepository(db_session)

    ev = event_repo.append(
        project_id="thread_abc",
        event_type="inbound_relay_paste",
        summary="Pasted from supplier",
        payload={"pasted_text": "Yes we can ship"},
    )
    inb = inbound_repo.create(
        thread_id="thread_abc",
        counterparty_id="supplier_001",
        pasted_text="Yes we can ship",
        channel="wechat",
        linked_execution_event_id=ev.event_id,
    )
    assert inb.inbound_id.startswith("inb_")
    assert not inb.superseded
    assert inb.linked_execution_event_id == ev.event_id


# ── Mixed-mode: verify no confusion ─────────────────────────────────────────

def test_all_four_channels_dispatch_correctly(db_session):
    """Run approve->send for all 4 channels; assert routing."""
    from aivan.openclaw.outbound_approval import send_draft
    from aivan.db.repositories.draft_repo import DraftRepository
    repo = DraftRepository(db_session)

    cases = [
        ("email",    "sent"),
        ("line",     "sent"),
        ("wechat",   "awaiting_relay"),
        ("wangwang", "awaiting_relay"),
    ]
    for channel, expected_action in cases:
        d = repo.create(
            project_id=f"proj_{channel}",
            data={"channel": channel, "target_peer_id": "peer_x", "message_text": "msg", "created_by_agent": "test"},
        )
        repo.approve(d.draft_id)
        db_session.flush()
        result = send_draft(d.draft_id, db_session)
        assert result.success, f"{channel}: {result.error}"
        assert result.action == expected_action, (
            f"{channel}: expected '{expected_action}', got '{result.action}'"
        )
