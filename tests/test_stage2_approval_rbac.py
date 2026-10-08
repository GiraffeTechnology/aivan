from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client_and_session(monkeypatch, production_runtime_policy, ready_dependency_probes):
    from aivan.api import main
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
    # Schema-startup behavior is tested by the migration-orchestrator suite.
    monkeypatch.setattr(main, "init_db", lambda: None)
    main.app.dependency_overrides[main.get_db] = override_db
    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client, Session
    main.app.dependency_overrides.clear()
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


def _seed_customer_quote_case(Session) -> tuple[str, str]:
    from aivan.db.repositories.draft_repo import DraftRepository
    from aivan.db.repositories.project_repo import ProjectRepository

    with Session() as db:
        project = ProjectRepository(db).create(
            conversation_id="customer-quote-rejection",
            customer_id="buyer-1",
            tenant_id="tenant-stage2",
        )
        project.case_state = "awaiting_approval"
        project.requirement_json = {"supplier_replies": [{"supplier_id": "supplier-1"}]}
        draft = DraftRepository(db).create(
            project.project_id,
            {
                "tenant_id": "tenant-stage2",
                "conversation_id": "customer-thread",
                "channel": "email",
                "target_peer_id": "buyer-1@example.com",
                "target_role": "customer",
                "message_text": "Customer quote requiring revision",
                "status": "pending_approval",
                "created_by_actor_id": "sales-1",
                "created_by_actor_role": "sales",
                "notes": "draft_type=customer_quote_email generated_from=supplier_reply",
            },
        )
        db.commit()
        return project.project_id, draft.draft_id


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
        audit = (
            db.query(AuditLogRecord)
            .filter(AuditLogRecord.event_type == "DRAFT_APPROVED")
            .one()
        )
        assert audit.before_json["status"] == "pending_approval"
        assert audit.after_json["status"] == "approved"
        delivery_audit = (
            db.query(AuditLogRecord)
            .filter(AuditLogRecord.event_type == "DRAFT_SENT")
            .one()
        )
        assert delivery_audit.after_json["status"] == "sent"


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


def test_rejecting_only_customer_quote_reopens_existing_supplier_reply_flow(
    client_and_session, monkeypatch
):
    from aivan.db.models.domain import ApprovalRecord, AuditLogRecord
    from aivan.db.models.inquiry import InquiryDraftRecord
    from aivan.db.models.project import Project
    from aivan.openclaw import outbound_approval

    def unexpected_send(*_args, **_kwargs):
        raise AssertionError("rejecting a draft must not invoke outbound delivery")

    monkeypatch.setattr(outbound_approval, "send_if_approved", unexpected_send)
    client, Session = client_and_session
    project_id, draft_id = _seed_customer_quote_case(Session)
    headers = _headers("approver", "approver-1", trace_id="trace-quote-rejected")

    response = client.post(f"/api/drafts/{draft_id}/reject", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "draft_id": draft_id,
        "status": "rejected",
        "case_state": "supplier_replied",
    }
    detail = client.get(
        f"/api/workbench/cases/{project_id}", headers=headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["case"]["case_state"] == "supplier_replied"
    assert [item["status"] for item in detail.json()["drafts"]] == ["rejected"]

    with Session() as db:
        assert db.get(Project, project_id).case_state == "supplier_replied"
        assert db.get(InquiryDraftRecord, draft_id).status == "rejected"
        assert (
            db.query(InquiryDraftRecord)
            .filter_by(
                tenant_id="tenant-stage2",
                project_id=project_id,
                status="pending_approval",
            )
            .count()
            == 0
        )
        approval = db.query(ApprovalRecord).one()
        assert approval.status == "rejected"
        assert approval.approver_id == "approver-1"
        assert approval.approver_role == "approver"
        assert approval.source_trace_id == "trace-quote-rejected"
        audits = db.query(AuditLogRecord).order_by(AuditLogRecord.created_at).all()
        assert [row.event_type for row in audits] == [
            "DRAFT_REJECTED",
            "CASE_STATE_TRANSITION",
        ]
        assert audits[-1].before_json == {"case_state": "awaiting_approval"}
        assert audits[-1].after_json == {"case_state": "supplier_replied"}
        assert all(row.authorization_basis == "deployment_api_key" for row in audits)


def test_rejecting_other_draft_preserves_response_and_case_contract(
    client_and_session
):
    from aivan.db.models.inquiry import InquiryDraftRecord

    client, Session = client_and_session
    draft_id = _seed_draft(Session)
    headers = _headers("approver", "approver-1", trace_id="trace-supplier-rejected")

    response = client.post(f"/api/drafts/{draft_id}/reject", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"draft_id": draft_id, "status": "rejected"}
    with Session() as db:
        assert db.get(InquiryDraftRecord, draft_id).status == "rejected"


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
