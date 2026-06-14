"""Tests for aiven.db.repositories.draft_repo — DraftRepository."""
import pytest
from aiven.db.repositories.draft_repo import DraftRepository
from aiven.db.models.inquiry import InquiryDraftRecord


def _create_draft(repo: DraftRepository, project_id: str = "proj_001", message: str = "Hello supplier") -> InquiryDraftRecord:
    return repo.create(
        project_id=project_id,
        data={
            "message_text": message,
            "channel": "email",
            "target_peer_id": "supplier@example.com",
            "target_role": "supplier",
            "created_by_agent": "test_agent",
        },
    )


def test_create_draft(db_session):
    repo = DraftRepository(db_session)
    draft = _create_draft(repo)
    assert draft is not None
    assert draft.draft_id is not None
    assert draft.project_id == "proj_001"
    assert draft.status == "pending"


def test_get_draft_by_id(db_session):
    repo = DraftRepository(db_session)
    draft = _create_draft(repo)
    fetched = repo.get(draft.draft_id)
    assert fetched is not None
    assert fetched.draft_id == draft.draft_id


def test_get_nonexistent_draft_returns_none(db_session):
    repo = DraftRepository(db_session)
    assert repo.get("nonexistent_id_xyz") is None


def test_list_pending(db_session):
    repo = DraftRepository(db_session)
    _create_draft(repo, "proj_A")
    _create_draft(repo, "proj_A")
    pending = repo.list_pending("proj_A")
    assert len(pending) == 2


def test_list_pending_excludes_other_projects(db_session):
    repo = DraftRepository(db_session)
    _create_draft(repo, "proj_A")
    _create_draft(repo, "proj_B")
    pending = repo.list_pending("proj_A")
    assert len(pending) == 1


def test_approve_draft(db_session):
    repo = DraftRepository(db_session)
    draft = _create_draft(repo)
    approved = repo.approve(draft.draft_id, approved_by="manager")
    assert approved is not None
    assert approved.status == "approved"
    assert approved.approved_by == "manager"
    assert approved.approved_at is not None


def test_approve_already_approved_does_nothing(db_session):
    repo = DraftRepository(db_session)
    draft = _create_draft(repo)
    repo.approve(draft.draft_id)
    # Second approve should not change status (already approved, not pending)
    result = repo.approve(draft.draft_id)
    assert result is not None
    # Status remains approved (not reset)
    assert result.status == "approved"


def test_reject_draft(db_session):
    repo = DraftRepository(db_session)
    draft = _create_draft(repo)
    rejected = repo.reject(draft.draft_id)
    assert rejected is not None
    assert rejected.status == "rejected"


def test_reject_approved_draft_no_change(db_session):
    """reject() only acts on pending drafts."""
    repo = DraftRepository(db_session)
    draft = _create_draft(repo)
    repo.approve(draft.draft_id)
    result = repo.reject(draft.draft_id)
    # Should still be approved (not pending, so reject has no effect)
    assert result.status == "approved"


def test_mark_sent(db_session):
    repo = DraftRepository(db_session)
    draft = _create_draft(repo)
    repo.approve(draft.draft_id)
    sent = repo.mark_sent(draft.draft_id)
    assert sent is not None
    assert sent.status == "sent"
    assert sent.sent_at is not None


def test_list_all_pending(db_session):
    repo = DraftRepository(db_session)
    _create_draft(repo, "proj_A")
    _create_draft(repo, "proj_B")
    all_pending = repo.list_all_pending()
    assert len(all_pending) >= 2


def test_message_text_stored(db_session):
    repo = DraftRepository(db_session)
    draft = _create_draft(repo, message_text="Custom message for supplier")
    fetched = repo.get(draft.draft_id)
    assert fetched.message_text == "Custom message for supplier"


def _create_draft(repo: DraftRepository, project_id: str = "proj_001", message_text: str = "Hello supplier") -> InquiryDraftRecord:
    return repo.create(
        project_id=project_id,
        data={
            "message_text": message_text,
            "channel": "email",
            "target_peer_id": "supplier@example.com",
            "target_role": "supplier",
            "created_by_agent": "test_agent",
        },
    )
