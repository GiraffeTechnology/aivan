"""Inbound event idempotency (PR27 salvage)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from aivan.db.models import Base, ProcessedInboundEvent
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.event_repo import ExecutionEventRepository
from aivan.db.repositories.inbound_event_repo import (
    InboundEventRepository,
    build_inbound_idempotency_key,
)
from aivan.execution.rfq_execution import create_rfq_from_event
from aivan.openclaw.contracts import OpenClawEvent


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _event(message_id="msg_1", conversation_id="conv_1", **kw) -> OpenClawEvent:
    base = dict(
        source="openclaw", channel="wechat", channel_account_id="acct_1",
        conversation_id=conversation_id, message_id=message_id,
        sender_id="user_001", sender_display_name="Operator",
        message_text="帮我询价 5000 件格子衬衫，45 天内交东京。",
        role_context="user", mode="command",
    )
    base.update(kw)
    return OpenClawEvent(**base)


# ── key construction ─────────────────────────────────────────────────────────

def test_key_is_stable_and_distinct():
    k1 = build_inbound_idempotency_key(source="openclaw", channel="wechat",
                                       channel_account_id="a", conversation_id="c", message_id="m")
    k2 = build_inbound_idempotency_key(source="openclaw", channel="wechat",
                                       channel_account_id="a", conversation_id="c", message_id="m")
    k3 = build_inbound_idempotency_key(source="openclaw", channel="wechat",
                                       channel_account_id="a", conversation_id="c", message_id="OTHER")
    assert k1 == k2 and k1 != k3


def test_event_without_stable_identity_is_not_deduplicated():
    # No message id AND no conversation id -> no key -> processed without dedup.
    assert build_inbound_idempotency_key(source="openclaw", channel="wechat",
                                         channel_account_id="a", conversation_id="", message_id="") is None
    # A conversation id alone is enough to form a key.
    assert build_inbound_idempotency_key(source="openclaw", channel="wechat",
                                         channel_account_id="a", conversation_id="c", message_id="") is not None


# ── replay semantics through create_rfq_from_event ───────────────────────────

def test_duplicate_inbound_event_replays_stored_result(db):
    first = create_rfq_from_event(_event(), db)
    second = create_rfq_from_event(_event(), db)  # identical event

    assert second.project_id == first.project_id
    assert second.action == first.action
    # Exactly one ledger row for the duplicate pair.
    assert db.query(ProcessedInboundEvent).count() == 1


def test_duplicate_inbound_event_creates_no_new_drafts_or_events(db):
    create_rfq_from_event(_event(), db)
    project_id = db.query(ProcessedInboundEvent).first().project_id

    drafts_before = len(DraftRepository(db).list_for_project(project_id))
    events_before = len(ExecutionEventRepository(db).list_for_project(project_id))
    projects_before = _project_count(db)

    create_rfq_from_event(_event(), db)  # duplicate

    assert len(DraftRepository(db).list_for_project(project_id)) == drafts_before
    assert len(ExecutionEventRepository(db).list_for_project(project_id)) == events_before
    assert _project_count(db) == projects_before


def test_distinct_messages_are_processed_independently(db):
    r1 = create_rfq_from_event(_event(message_id="msg_a", conversation_id="conv_a"), db)
    r2 = create_rfq_from_event(_event(message_id="msg_b", conversation_id="conv_b"), db)
    assert r1.project_id != r2.project_id
    assert db.query(ProcessedInboundEvent).count() == 2


def test_repository_record_is_idempotent(db):
    repo = InboundEventRepository(db)
    key = "inb_test"
    a = repo.record(key, project_id="p1", event_type="user_command", result_json={"x": 1})
    b = repo.record(key, project_id="p1", event_type="user_command", result_json={"x": 1})
    assert a.id == b.id
    assert db.query(ProcessedInboundEvent).count() == 1


def _project_count(db) -> int:
    from aivan.db.models.project import Project

    return db.query(Project).count()
