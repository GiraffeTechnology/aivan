"""Tests for information rollback / reversal (Workstream D)."""
from __future__ import annotations
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("AIVAN_LLM_PROVIDER", "mock")
os.environ.setdefault("OPENCLAW_MOCK_MODE", "true")
os.environ.setdefault("AIVAN_EMAIL_MODE", "mock")
os.environ.setdefault("AIVAN_LINE_ENABLED", "true")
os.environ.setdefault("AIVAN_LINE_MODE", "mock")


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


def _make_inbound_event(db, project_id="proj_rev_001", text="Wrong supplier info"):
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    from aivan.db.repositories.inbound_repo import InboundRelayRepository

    event_repo = ExecutionEventRepository(db)
    inbound_repo = InboundRelayRepository(db)

    ev = event_repo.append(
        project_id=project_id,
        event_type="inbound_relay_paste",
        summary=f"Pasted: {text[:60]}",
        payload={"pasted_text": text},
    )
    inb = inbound_repo.create(
        thread_id=project_id,
        counterparty_id="supplier_x",
        pasted_text=text,
        linked_execution_event_id=ev.event_id,
    )
    return ev, inb


def _make_derived_draft(db, event_id: str, status: str = "pending_approval"):
    """Create a draft that is derived from *event_id*."""
    from aivan.db.repositories.draft_repo import DraftRepository
    repo = DraftRepository(db)
    d = repo.create(
        project_id="proj_rev_001",
        data={
            "channel": "email",
            "message_text": "Reply based on pasted info",
            "created_by_agent": "test",
            "derived_from_event_id": event_id,
        },
    )
    if status == "sent":
        repo.approve(d.draft_id)
        db.flush()
        repo.mark_sent(d.draft_id)
    elif status == "relayed":
        repo.approve(d.draft_id)
        db.flush()
        repo.mark_awaiting_relay(d.draft_id)
        db.flush()
        repo.mark_relayed(d.draft_id)
    db.flush()
    return d


# ── Core reversal mechanics ──────────────────────────────────────────────────

def test_reversal_marks_original_superseded(db_session):
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    ev, _ = _make_inbound_event(db_session)
    repo = ExecutionEventRepository(db_session)
    reversal = repo.append_reversal(
        project_id="proj_rev_001",
        original_event_id=ev.event_id,
        reason="Wrong info pasted",
    )
    db_session.flush()
    refreshed = repo.get(ev.event_id)
    assert refreshed.superseded is True
    assert reversal.event_type == "reversal"
    assert reversal.references_event_id == ev.event_id


def test_reversal_invalidates_derived_pending_draft(db_session):
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    from aivan.db.repositories.draft_repo import DraftRepository
    ev, _ = _make_inbound_event(db_session)
    d = _make_derived_draft(db_session, ev.event_id, status="pending_approval")

    event_repo = ExecutionEventRepository(db_session)
    draft_repo = DraftRepository(db_session)
    event_repo.append_reversal("proj_rev_001", ev.event_id, "pasted wrong thread")
    affected = draft_repo.invalidate_derived(ev.event_id)

    db_session.flush()
    assert d.draft_id in affected
    db_session.refresh(d)
    assert d.status == "invalidated"


def test_reversal_does_not_change_already_sent_draft(db_session):
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    from aivan.db.repositories.draft_repo import DraftRepository
    ev, _ = _make_inbound_event(db_session)
    d = _make_derived_draft(db_session, ev.event_id, status="sent")

    event_repo = ExecutionEventRepository(db_session)
    draft_repo = DraftRepository(db_session)
    event_repo.append_reversal("proj_rev_001", ev.event_id, "late correction")
    draft_repo.invalidate_derived(ev.event_id)
    db_session.flush()

    # Sent draft must remain 'sent'
    db_session.refresh(d)
    assert d.status == "sent", "Already-sent drafts must not be invalidated"


def test_reversal_does_not_change_relayed_draft(db_session):
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    from aivan.db.repositories.draft_repo import DraftRepository
    ev, _ = _make_inbound_event(db_session)
    d = _make_derived_draft(db_session, ev.event_id, status="relayed")

    event_repo = ExecutionEventRepository(db_session)
    draft_repo = DraftRepository(db_session)
    event_repo.append_reversal("proj_rev_001", ev.event_id, "wrong thread")
    draft_repo.invalidate_derived(ev.event_id)
    db_session.flush()

    db_session.refresh(d)
    assert d.status == "relayed", "Already-relayed drafts must not be invalidated"


def test_reversal_inbound_marked_superseded(db_session):
    from aivan.db.repositories.inbound_repo import InboundRelayRepository
    ev, inb = _make_inbound_event(db_session)
    inbound_repo = InboundRelayRepository(db_session)
    inbound_repo.supersede(inb.inbound_id)
    db_session.flush()
    db_session.refresh(inb)
    assert inb.superseded is True


def test_audit_chain_contains_reversal(db_session):
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    ev, _ = _make_inbound_event(db_session)
    repo = ExecutionEventRepository(db_session)
    reversal = repo.append_reversal("proj_rev_001", ev.event_id, "error")
    db_session.flush()

    all_events = repo.list_for_project("proj_rev_001")
    types = {e.event_type for e in all_events}
    assert "reversal" in types
    reversal_ev = next(e for e in all_events if e.event_type == "reversal")
    assert reversal_ev.references_event_id == ev.event_id


# ── API-level reversal ───────────────────────────────────────────────────────

@pytest.fixture
def api_client(db_session):
    from aivan.api.main import app, get_db
    from fastapi.testclient import TestClient

    os.environ.pop("AIVAN_API_KEY", None)

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def test_api_reverse_requires_confirm(api_client, db_session):
    ev, _ = _make_inbound_event(db_session)
    db_session.commit()
    resp = api_client.post(f"/api/events/{ev.event_id}/reverse", json={"reason": "test"})
    assert resp.status_code == 400


def test_api_reverse_unknown_event_404(api_client):
    resp = api_client.post("/api/events/ev_nonexistent/reverse", json={"reason": "x", "confirm": True})
    assert resp.status_code == 404


def test_api_impact_preview(api_client, db_session):
    ev, _ = _make_inbound_event(db_session)
    _make_derived_draft(db_session, ev.event_id, status="pending_approval")
    db_session.commit()
    resp = api_client.get(f"/api/events/{ev.event_id}/impact")
    assert resp.status_code == 200
    data = resp.json()
    assert "pending_invalidation" in data
    assert len(data["pending_invalidation"]) == 1


def test_api_reverse_generates_correction_for_sent(api_client, db_session):
    ev, _ = _make_inbound_event(db_session)
    _make_derived_draft(db_session, ev.event_id, status="sent")
    db_session.commit()
    resp = api_client.post(
        f"/api/events/{ev.event_id}/reverse",
        json={"reason": "wrong counterparty pasted", "confirm": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["correction_draft_id"] is not None
    assert data["requires_human_review"] is True
    assert len(data["already_sent_cannot_recall"]) == 1
