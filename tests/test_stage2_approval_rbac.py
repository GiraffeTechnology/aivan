from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client_and_session(monkeypatch):
    from aivan.api.main import app, get_db
    from aivan.db.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_API_KEY", "stage2-secret")
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-stage2")
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, Session
    app.dependency_overrides.clear()
    engine.dispose()


def _headers(role: str, actor_id: str, *, trace_id: str) -> dict[str, str]:
    conversation_role = {
        "buyer": "buyer_thread",
        "approver": "approval_thread",
        "admin": "internal_thread",
    }[role]
    return {
        "X-AIVAN-API-Key": "stage2-secret",
        "X-AIVAN-Tenant-ID": "tenant-stage2",
        "X-AIVAN-Actor-ID": actor_id,
        "X-AIVAN-Role-Context": role,
        "X-AIVAN-Conversation-Role": conversation_role,
        "X-AIVAN-Execution-Mode": "approval",
        "X-AIVAN-Trace-ID": trace_id,
    }


def _seed_draft(Session, *, status="pending_approval") -> str:
    from aivan.db.repositories.draft_repo import DraftRepository

    db = Session()
    try:
        draft = DraftRepository(db).create(
            "case-stage2-approval",
            {
                "tenant_id": "tenant-stage2",
                "conversation_id": "supplier-thread",
                "channel": "email",
                "target_peer_id": "supplier-1@example.com",
                "target_role": "supplier",
                "message_text": "Approved supplier inquiry",
                "status": status,
                "created_by_actor_id": "sales-1",
                "created_by_actor_role": "sales",
            },
        )
        db.commit()
        return draft.draft_id
    finally:
        db.close()


def test_buyer_cannot_approve_and_rejection_is_audited(client_and_session):
    from aivan.db.models.domain import ApprovalRecord, AuditLogRecord
    from aivan.db.models.inquiry import InquiryDraftRecord

    client, Session = client_and_session
    draft_id = _seed_draft(Session)

    response = client.post(
        f"/api/drafts/{draft_id}/approve",
        headers=_headers("buyer", "buyer-1", trace_id="trace-buyer-denied"),
        json={"approved_by": "spoofed-approver"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "CAPABILITY_FORBIDDEN"
    with Session() as db:
        draft = db.get(InquiryDraftRecord, draft_id)
        assert draft.status == "pending_approval"
        approval = db.query(ApprovalRecord).one()
        assert approval.status == "authorization_rejected"
        assert approval.approver_id == "buyer-1"
        assert approval.approver_role == "buyer"
        assert approval.source_trace_id == "trace-buyer-denied"
        audit = db.query(AuditLogRecord).one()
        assert audit.event_type == "DRAFT_ACTION_REJECTED"
        assert audit.rejection_reason


def test_approver_identity_not_body_controls_approval(client_and_session, monkeypatch):
    from aivan.db.models.domain import ApprovalRecord, AuditLogRecord
    from aivan.db.models.inquiry import InquiryDraftRecord
    from aivan.openclaw import outbound_approval
    from aivan.openclaw.contracts import OpenClawSendResponse

    class Client:
        def send_message(self, _request):
            return OpenClawSendResponse(success=True, message_id="sent-stage2")

    monkeypatch.setattr(outbound_approval, "get_openclaw_client", lambda: Client())
    client, Session = client_and_session
    draft_id = _seed_draft(Session)

    response = client.post(
        f"/api/drafts/{draft_id}/approve",
        headers=_headers("approver", "approver-1", trace_id="trace-approved"),
        json={"approved_by": "spoofed-actor"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["sent"] is True
    with Session() as db:
        draft = db.get(InquiryDraftRecord, draft_id)
        assert draft.status == "sent"
        assert draft.approved_by == "approver-1"
        assert draft.authorization_basis == "deployment_api_key"
        approval = db.query(ApprovalRecord).one()
        assert approval.approver_id == "approver-1"
        assert approval.approver_role == "approver"
        assert approval.source_trace_id == "trace-approved"
        assert draft.approval_id == approval.approval_id
        audit = db.query(AuditLogRecord).one()
        assert audit.before_json["status"] == "pending_approval"
        assert audit.after_json["status"] == "approved"


def test_buyer_cannot_retry_failed_outbound(client_and_session):
    from aivan.db.models.inquiry import InquiryDraftRecord

    client, Session = client_and_session
    draft_id = _seed_draft(Session, status="send_failed")
    response = client.post(
        f"/api/drafts/{draft_id}/retry",
        headers=_headers("buyer", "buyer-1", trace_id="trace-retry-denied"),
    )
    assert response.status_code == 403
    with Session() as db:
        assert db.get(InquiryDraftRecord, draft_id).status == "send_failed"


def test_production_approval_requires_actor_and_role_headers(client_and_session):
    client, Session = client_and_session
    draft_id = _seed_draft(Session)
    response = client.post(
        f"/api/drafts/{draft_id}/approve",
        headers={
            "X-AIVAN-API-Key": "stage2-secret",
            "X-AIVAN-Tenant-ID": "tenant-stage2",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "ACTOR_ID_REQUIRED"
