"""Stage 1 contract tests for unified invoke, security, and tenant isolation."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


INVOKE_PATHS = (
    "/invoke",
    "/api/openclaw/events",
    "/api/skill/invoke",
    "/api/rfq/create-from-event",
)


@pytest.fixture
def client(monkeypatch, production_runtime_policy, ready_dependency_probes):
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

    def deterministic_execution(event_data, _db):
        return {
            "status": "ok",
            "output": event_data["message_text"],
            "reply_text": event_data["message_text"],
            "business_result": {
                "conversation_id": event_data["conversation_id"],
                "role_context": event_data.get("role_context"),
                "channel_account_id": event_data.get("channel_account_id"),
            },
        }

    monkeypatch.setattr(main, "_run_skill_event", deterministic_execution)
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_API_KEY", "stage1-secret")
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-a")
    monkeypatch.delenv("AIVAN_TENANT_API_KEYS", raising=False)
    # Schema-startup behavior is tested by the migration-orchestrator suite.
    monkeypatch.setattr(main, "init_db", lambda: None)
    main.app.dependency_overrides[main.get_db] = override_db
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()
    engine.dispose()


def _headers(**overrides):
    headers = {
        "X-AIVAN-API-Key": "stage1-secret",
        "X-AIVAN-Tenant-ID": "tenant-a",
        "X-AIVAN-Trace-ID": "trace-stage1-001",
        "Idempotency-Key": "delivery-stage1-001",
        "X-AIVAN-Role-Context": "buyer",
        "X-AIVAN-Actor-ID": "buyer-001",
        "X-AIVAN-Participant-ID": "participant-buyer-001",
        "X-AIVAN-Participant-Role": "buyer",
        "X-AIVAN-Participant-Conversation-Role": "buyer_thread",
        "X-AIVAN-Channel-Account-ID": "wechat-account-01",
    }
    headers.update(overrides)
    return headers


def _event(**overrides):
    event = {
        "source": "openclaw",
        "channel": "wechat",
        "conversation_id": "conv-stage1-001",
        "message_id": "msg-stage1-001",
        "sender_id": "buyer-001",
        "message_text": "Need 500 cotton shirts",
    }
    event.update(overrides)
    return event


def test_four_routes_share_one_result_trace_and_error_contract(client):
    snapshots = []
    for path in INVOKE_PATHS:
        response = client.post(path, json=_event(), headers=_headers())
        assert response.status_code == 200
        snapshots.append(response.json())
    assert snapshots[1:] == [snapshots[0], snapshots[0], snapshots[0]]
    assert snapshots[0]["tenant_id"] == "tenant-a"
    assert snapshots[0]["trace_id"] == "trace-stage1-001"
    assert snapshots[0]["idempotency_key"] == "delivery-stage1-001"
    assert snapshots[0]["business_result"]["role_context"] == "buyer"


@pytest.mark.parametrize("path", INVOKE_PATHS)
def test_four_routes_reject_missing_and_wrong_keys(client, path):
    missing = client.post(path, json=_event(), headers={"X-AIVAN-Tenant-ID": "tenant-a"})
    assert missing.status_code == 401
    assert missing.json()["detail"]["error"] == "AUTH_REQUIRED"

    wrong = client.post(path, json=_event(), headers=_headers(**{"X-AIVAN-API-Key": "wrong"}))
    assert wrong.status_code == 403
    assert wrong.json()["detail"]["error"] == "INVALID_API_KEY"


def test_cross_tenant_body_and_header_are_rejected(client):
    body_mismatch = client.post(
        "/invoke", json=_event(tenant_id="tenant-b"), headers=_headers()
    )
    assert body_mismatch.status_code == 403
    assert body_mismatch.json()["detail"]["error"] == "TENANT_MISMATCH"

    header_mismatch = client.post(
        "/invoke",
        json=_event(),
        headers=_headers(**{"X-AIVAN-Tenant-ID": "tenant-b"}),
    )
    assert header_mismatch.status_code == 403
    assert header_mismatch.json()["detail"]["error"] == "TENANT_MISMATCH"


def test_body_role_and_channel_account_are_not_trusted_in_production(client):
    headers = _headers()
    headers.pop("X-AIVAN-Participant-Role")
    headers.pop("X-AIVAN-Channel-Account-ID")
    role = client.post("/invoke", json=_event(role_context="admin"), headers=headers)
    assert role.status_code == 403
    assert role.json()["detail"]["error"] == "UNTRUSTED_ROLE_CONTEXT"

    account = client.post(
        "/invoke", json=_event(channel_account_id="forged-account"), headers=headers
    )
    assert account.status_code == 403
    assert account.json()["detail"]["error"] == "UNTRUSTED_CHANNEL_ACCOUNT"

