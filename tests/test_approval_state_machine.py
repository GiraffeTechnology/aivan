"""Draft approval state machine with recoverable send failures (PRD §11, §18.7)."""
from __future__ import annotations

import pytest

from aivan.db.repositories.draft_repo import DraftRepository
from aivan.execution import approval_state
from aivan.execution.approval_state import DraftStateError, approve_and_send


def _draft(db, *, channel="email", target="supplier@example.com", role="supplier") -> str:
    repo = DraftRepository(db)
    d = repo.create(
        "proj_asm_001",
        {
            "conversation_id": "conv_asm",
            "channel": channel,
            "target_peer_id": target,
            "target_role": role,
            "message_text": "Please quote this RFQ.",
            "status": "pending_approval",
            "created_by_agent": "test",
        },
    )
    db.commit()
    return d.draft_id


def test_approve_draft_success_marks_sent(db_session, monkeypatch):
    monkeypatch.setenv("OPENCLAW_MOCK_MODE", "true")
    draft_id = _draft(db_session)
    result = approve_and_send(draft_id, db_session)
    assert result.status == approval_state.SENT
    assert result.sent is True
    assert DraftRepository(db_session).get(draft_id).status == "sent"


def test_approve_draft_send_failure_marks_send_failed(db_session, monkeypatch):
    class _Resp:
        success = False
        error = "transport boom"
        message_id = ""

    class _Client:
        def send_message(self, req):
            return _Resp()

    monkeypatch.setattr(approval_state, "get_openclaw_client", lambda: _Client())
    draft_id = _draft(db_session)
    result = approve_and_send(draft_id, db_session)
    assert result.status == approval_state.SEND_FAILED
    d = DraftRepository(db_session).get(draft_id)
    assert d.status == "send_failed"
    assert d.status != "approved"
    assert "send_failed_reason" in (d.notes or "")


def test_approve_draft_policy_block_does_not_leave_approved(db_session):
    # A personal-IM supplier channel is blocked by channel policy; the draft must
    # not be left in an approved state.
    draft_id = _draft(db_session, channel="wechat", target="supplier_wechat")
    result = approve_and_send(draft_id, db_session)
    assert result.status == approval_state.SEND_FAILED
    d = DraftRepository(db_session).get(draft_id)
    assert d.status != "approved"
    assert d.status != "approved_pending_send"


def test_send_failed_draft_is_recoverable(db_session, monkeypatch):
    calls = {"n": 0}

    class _Resp:
        def __init__(self, ok):
            self.success = ok
            self.error = None if ok else "temporary"
            self.message_id = "m1" if ok else ""

    class _Client:
        def send_message(self, req):
            calls["n"] += 1
            return _Resp(calls["n"] >= 2)  # fail first, succeed on retry

    monkeypatch.setattr(approval_state, "get_openclaw_client", lambda: _Client())
    draft_id = _draft(db_session)
    first = approve_and_send(draft_id, db_session)
    assert first.status == approval_state.SEND_FAILED
    # Retry: send_failed drafts are approvable again.
    second = approve_and_send(draft_id, db_session)
    assert second.status == approval_state.SENT


def test_reject_pending_draft_still_works(db_session):
    draft_id = _draft(db_session)
    result = approval_state.reject(draft_id, db_session)
    assert result.status == approval_state.REJECTED
    assert DraftRepository(db_session).get(draft_id).status == "rejected"


def test_sent_draft_cannot_be_reapproved(db_session, monkeypatch):
    monkeypatch.setenv("OPENCLAW_MOCK_MODE", "true")
    draft_id = _draft(db_session)
    approve_and_send(draft_id, db_session)
    with pytest.raises(DraftStateError):
        approve_and_send(draft_id, db_session)
