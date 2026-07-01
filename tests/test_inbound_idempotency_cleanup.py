"""PR22 cleanup regression tests: idempotency for repeated inbound events.

Duplicate/retried inbound events (IM/email/OpenClaw/webhook retries) must not
create duplicate projects, RFQs, drafts, or execution events. See CLAUDE task
Part C (§7).
"""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aivan.db.models import Base
from aivan.db.models.execution import ExecutionEventRecord, ProcessedInboundEvent
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.inbound_event_repo import build_inbound_idempotency_key
from aivan.execution.rfq_execution import create_rfq_from_event
from aivan.openclaw.contracts import OpenClawEvent


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _customer_event(message_id="msg_1", conversation_id="conv_1"):
    return OpenClawEvent(
        source="openclaw",
        channel="email",
        channel_account_id="acc_1",
        conversation_id=conversation_id,
        message_id=message_id,
        sender_id="customer_1",
        sender_display_name="Vancouver Buyer",
        role_context="customer",
        mode="auto",
        message_text="We need 10,000 white 100% cotton shirts delivered to Vancouver within 45 days.",
    )


def test_duplicate_inbound_event_creates_one_project_and_one_draft_set(db):
    event = _customer_event()
    r1 = create_rfq_from_event(event, db)
    drafts_1 = DraftRepository(db).list_for_project(r1.project_id)
    events_1 = db.query(ExecutionEventRecord).count()

    r2 = create_rfq_from_event(event, db)  # exact retry
    drafts_2 = DraftRepository(db).list_for_project(r2.project_id)
    events_2 = db.query(ExecutionEventRecord).count()

    assert r1.project_id == r2.project_id
    assert len(drafts_1) == len(drafts_2)  # no duplicate drafts
    assert events_1 == events_2  # no duplicate execution events
    assert db.query(ProcessedInboundEvent).count() == 1


def test_triple_retry_still_idempotent(db):
    event = _customer_event()
    first = create_rfq_from_event(event, db)
    baseline = len(DraftRepository(db).list_for_project(first.project_id))
    for _ in range(2):
        create_rfq_from_event(event, db)
    assert len(DraftRepository(db).list_for_project(first.project_id)) == baseline
    assert db.query(ProcessedInboundEvent).count() == 1


def test_distinct_message_ids_are_processed_separately(db):
    r1 = create_rfq_from_event(_customer_event(message_id="msg_1"), db)
    r2 = create_rfq_from_event(_customer_event(message_id="msg_2"), db)
    # Same conversation → same project, but two distinct processed events.
    assert r1.project_id == r2.project_id
    assert db.query(ProcessedInboundEvent).count() == 2


def test_idempotency_key_is_stable_and_scoped():
    a = build_inbound_idempotency_key(
        source="openclaw", channel="email", channel_account_id="acc",
        conversation_id="c", message_id="m",
    )
    b = build_inbound_idempotency_key(
        source="openclaw", channel="email", channel_account_id="acc",
        conversation_id="c", message_id="m",
    )
    c = build_inbound_idempotency_key(
        source="openclaw", channel="email", channel_account_id="acc",
        conversation_id="c", message_id="m2",
    )
    assert a == b  # stable
    assert a != c  # different message → different key


def test_idempotency_key_none_without_identity():
    assert build_inbound_idempotency_key(
        source="openclaw", channel="email", channel_account_id="",
        conversation_id="", message_id="",
    ) is None


# ── Approval retries do not double-send (existing guard, regression) ───────


@pytest.fixture
def api_db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def api_client(api_db):
    from aivan.api.main import app, get_db

    def override_db():
        yield api_db

    os.environ.pop("AIVAN_API_KEY", None)
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


def test_duplicate_event_via_api_is_idempotent(api_client, api_db):
    payload = {
        "source": "openclaw",
        "channel": "email",
        "channel_account_id": "acc_api",
        "conversation_id": "conv_api_1",
        "message_id": "msg_api_1",
        "sender_id": "customer_api",
        "role_context": "customer",
        "mode": "auto",
        "message_text": "We need 5,000 cotton shirts to Vancouver within 40 days.",
    }
    r1 = api_client.post("/api/openclaw/events", json=payload)
    r2 = api_client.post("/api/openclaw/events", json=payload)
    assert r1.status_code == 200 and r2.status_code == 200
    assert api_db.query(ProcessedInboundEvent).count() == 1


def test_duplicate_approval_does_not_double_send(api_client, api_db):
    payload = {
        "source": "openclaw",
        "channel": "email",
        "channel_account_id": "acc_api2",
        "conversation_id": "conv_api_2",
        "message_id": "msg_api_2",
        "sender_id": "customer_api2",
        "role_context": "customer",
        "mode": "auto",
        "message_text": "We need 8,000 cotton shirts to Toronto within 50 days.",
    }
    resp = api_client.post("/api/openclaw/events", json=payload).json()
    draft_ids = resp.get("drafts_created") or []
    if not draft_ids:
        pytest.skip("no supplier drafts generated in this environment")
    draft_id = draft_ids[0]
    first = api_client.post(f"/api/openclaw/drafts/{draft_id}/approve", json={"approved_by": "user"})
    second = api_client.post(f"/api/openclaw/drafts/{draft_id}/approve", json={"approved_by": "user"})
    assert first.status_code == 200
    # Second approval is rejected (already handled) — no second send.
    assert second.status_code == 409
