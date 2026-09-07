"""Stage 1 short-form draft retry endpoint contract."""
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
    monkeypatch.setenv("AIVAN_API_KEY", "stage1-secret")
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-a")
    # This suite exercises production authorization against its own fully
    # bootstrapped database. Schema-startup behavior is covered separately.
    monkeypatch.setattr(main, "init_db", lambda: None)
    main.app.dependency_overrides[main.get_db] = override_db
    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client, Session
    main.app.dependency_overrides.clear()
    engine.dispose()


def _headers(tenant="tenant-a"):
    return {
        "X-AIVAN-API-Key": "stage1-secret",
        "X-AIVAN-Tenant-ID": tenant,
        "X-AIVAN-Actor-ID": "approver-001",
        "X-AIVAN-Role-Context": "approver",
        "X-AIVAN-Conversation-Role": "approval_thread",
        "X-AIVAN-Execution-Mode": "approval",
    }


def _seed(Session, *, tenant_id="tenant-a", status="send_failed"):
    from aivan.db.repositories.draft_repo import DraftRepository

    db = Session()
    try:
        draft = DraftRepository(db).create(
            "proj-retry-001",
            {
                "tenant_id": tenant_id,
                "conversation_id": "conv-retry-001",
                "channel": "email",
                "target_peer_id": "supplier@example.com",
                "target_role": "supplier",
                "message_text": "Please retry this approved RFQ.",
                "status": status,
                "approved_by": "operator-001",
            },
        )
        db.commit()
        return draft.draft_id
    finally:
        db.close()


def test_retry_send_failed_draft_marks_sent(client_and_session, monkeypatch):
    from aivan.execution import approval_state
    from aivan.openclaw.contracts import OpenClawSendResponse

    class Client:
        def send_message(self, _request):
            return OpenClawSendResponse(success=True, message_id="msg-retried")

    monkeypatch.setattr(approval_state, "get_openclaw_client", lambda: Client())
    client, Session = client_and_session
    draft_id = _seed(Session)
    response = client.post(f"/api/drafts/{draft_id}/retry", headers=_headers())
    assert response.status_code == 200
    assert response.json() == {
        "draft_id": draft_id,
        "status": "sent",
        "sent": True,
        "error": None,
        "message_id": "msg-retried",
    }


def test_retry_requires_send_failed_state(client_and_session):
    client, Session = client_and_session
    draft_id = _seed(Session, status="pending_approval")
    response = client.post(f"/api/drafts/{draft_id}/retry", headers=_headers())
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "invalid_draft_state"


def test_retry_hides_other_tenant_draft(client_and_session):
    client, Session = client_and_session
    draft_id = _seed(Session, tenant_id="tenant-b")
    response = client.post(f"/api/drafts/{draft_id}/retry", headers=_headers())
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "not_found"
