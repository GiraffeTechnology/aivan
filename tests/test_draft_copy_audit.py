"""Reported clipboard completion is auditable, never a delivery receipt."""
import hashlib

from aivan.db.models import ApprovalRecord, AuditLogRecord, RelayReceiptRecord
from aivan.db.repositories.draft_repo import DraftRepository
from tests.test_myaivan_workbench import _login, _seed_case, workbench  # noqa: F401


def seed(workbench):
    client, db = workbench
    session = _login(client)
    project = _seed_case(db, "operator-1", "copy-case")
    draft = DraftRepository(db).create(project.project_id, {
        "tenant_id": "test_tenant", "message_text": "Please quote 10 shirts.",
        "status": "pending_approval", "target_role": "supplier", "channel": "wechat",
    })
    db.commit()
    return client, db, draft, {
        "X-AIVAN-CSRF": session["csrf_token"], "Idempotency-Key": "copy-1",
    }


def copy(client, draft, headers, digest=None):
    return client.post(f"/api/workbench/cases/{draft.project_id}/drafts/{draft.draft_id}/copy",
                       headers=headers, json={"content_sha256": digest or hashlib.sha256(draft.message_text.encode()).hexdigest()})


def test_copy_is_durable_idempotent_and_not_approval_or_send(workbench):
    client, db, draft, headers = seed(workbench)
    first = copy(client, draft, headers)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "copied"
    assert first.json()["delivery_claim"] is False
    again = copy(client, draft, headers)
    assert again.json()["idempotent_replay"] is True
    db.expire_all()
    assert draft.status == "pending_approval"
    assert db.query(ApprovalRecord).count() == db.query(RelayReceiptRecord).count() == 0
    assert db.query(AuditLogRecord).filter_by(event_type="DRAFT_COPIED").count() == 1


def test_stale_clipboard_digest_is_rejected_without_copy_audit(workbench):
    client, db, draft, headers = seed(workbench)
    response = copy(client, draft, headers, "0" * 64)
    assert response.status_code == 409
    assert db.query(AuditLogRecord).filter_by(event_type="DRAFT_COPIED").count() == 0


def test_reused_copy_key_cannot_attach_to_another_draft(workbench):
    client, db, draft, headers = seed(workbench)
    assert copy(client, draft, headers).status_code == 200
    another = DraftRepository(db).create(draft.project_id, {
        "tenant_id": "test_tenant", "message_text": "Another draft", "target_role": "supplier",
    })
    db.commit()
    assert copy(client, another, headers).status_code == 409


def test_copy_does_not_expose_cross_tenant_case(workbench):
    client, db, draft, headers = seed(workbench)
    draft.tenant_id = "other"
    db.commit()
    assert copy(client, draft, headers).status_code == 404
    assert db.query(AuditLogRecord).filter_by(event_type="DRAFT_COPIED").count() == 0


def test_copy_requires_csrf_and_explicit_idempotency(workbench):
    client, _, draft, headers = seed(workbench)
    assert copy(client, draft, {"Idempotency-Key": "copy-1"}).status_code == 403
    assert copy(client, draft, {"X-AIVAN-CSRF": headers["X-AIVAN-CSRF"]}).status_code == 400


def test_copy_retry_survives_later_draft_status_without_rewriting_history(workbench):
    client, db, draft, headers = seed(workbench)
    original = copy(client, draft, headers)
    assert original.status_code == 200
    draft.status = "approved"
    db.commit()
    repeated = copy(client, draft, headers)
    assert repeated.status_code == 200
    assert repeated.json()["audit_id"] == original.json()["audit_id"]
    assert repeated.json()["idempotent_replay"] is True
    assert db.query(AuditLogRecord).filter_by(event_type="DRAFT_COPIED").count() == 1
