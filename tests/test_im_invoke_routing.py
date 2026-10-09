"""Synthetic inbound adapters retain DB routing and replay identity.

These tests do not connect to a WeChat/WeCom account or send real messages.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from aivan.api.main import _normalize_invoke_payload
from aivan.api.request_context import RequestContext, apply_trusted_identity
from aivan.db.models import ProcessedInboundEvent
from aivan.db.repositories.inbound_event_repo import build_inbound_idempotency_key
from aivan.execution.rfq_execution import create_rfq_from_event
from aivan.openclaw.event_adapter import parse_openclaw_event


def payload(shape, **fields):
    text = "Please request a quote for 5000 plaid shirts to Tokyo within 45 days."
    if shape == "wechat":
        return {"content": text, "from_user": "buyer-1", "room_id": "thread-1", **fields}
    return {"user_input": text, "session_id": "thread-1", "context": {
        "channel": "email", "sender_id": "buyer-1", **fields}}


def context(**fields):
    values = dict(tenant_id="tenant-a", trace_id="trace-1", idempotency_key="",
                  actor_id="service-1", role_context="operator", conversation_role="internal_thread",
                  execution_mode="auto", channel_account_id="account-trusted",
                  participant_actor_id="participant-1", participant_role_context="buyer",
                  participant_conversation_role="buyer_thread", authorization_basis="tenant_api_key",
                  production=True)
    values.update(fields)
    return RequestContext(**values)


@pytest.mark.parametrize("shape", ["wechat", "standard"])
def test_normalization_preserves_stable_routing_fields(shape):
    fields = dict(message_id="message-1", channel_account_id="account-1",
                  idempotency_key="delivery-1", project_id="project-1")
    normalized = _normalize_invoke_payload(payload(shape, **fields))
    for key, value in fields.items():
        assert normalized.get(key) == value


@pytest.mark.parametrize("shape", ["wechat", "standard"])
def test_distinct_message_ids_do_not_collapse_in_same_thread(shape):
    keys = []
    for message_id in ("message-1", "message-2"):
        event = parse_openclaw_event(_normalize_invoke_payload(payload(shape, message_id=message_id)))
        keys.append(build_inbound_idempotency_key(tenant_id="tenant-a", source=event.source,
            channel=event.channel, channel_account_id=event.channel_account_id,
            conversation_id=event.conversation_id, message_id=event.message_id))
    assert keys[0] != keys[1]


@pytest.mark.parametrize("shape", ["wechat", "standard"])
def test_body_fields_do_not_replace_trusted_identity(shape):
    normalized = _normalize_invoke_payload(payload(shape, message_id="message-1",
        channel_account_id="forged-account", tenant_id="forged-tenant", actor_id="forged-admin",
        authenticated_actor_id="forged-admin", business_role="admin"))
    event = apply_trusted_identity(normalized, context())
    assert event["tenant_id"] == "tenant-a"
    assert event["actor_id"] == "participant-1"
    assert event["authenticated_actor_id"] == "service-1"
    assert event["business_role"] == "buyer"
    assert event["channel_account_id"] == "account-trusted"


@pytest.mark.parametrize("shape", ["wechat", "standard"])
def test_untrusted_account_fails_closed(shape):
    normalized = _normalize_invoke_payload(payload(shape, channel_account_id="untrusted-account"))
    with pytest.raises(HTTPException) as exc:
        apply_trusted_identity(normalized, context(channel_account_id=""))
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "UNTRUSTED_CHANNEL_ACCOUNT"


@pytest.mark.parametrize("shape", ["wechat", "standard"])
def test_normalized_replay_survives_session_reset_and_is_tenant_scoped(shape, db_session):
    raw = payload(shape, message_id="message-1", idempotency_key="delivery-1")
    first_event = apply_trusted_identity(_normalize_invoke_payload(raw), context())
    first = create_rfq_from_event(parse_openclaw_event(first_event), db_session)
    db_session.commit()
    db_session.expunge_all()
    replay = create_rfq_from_event(parse_openclaw_event(first_event), db_session)
    assert replay.project_id == first.project_id
    assert db_session.query(ProcessedInboundEvent).count() == 1
    other = apply_trusted_identity(_normalize_invoke_payload(raw), context(tenant_id="tenant-b"))
    other_result = create_rfq_from_event(parse_openclaw_event(other), db_session)
    assert other_result.project_id != first.project_id
    assert db_session.query(ProcessedInboundEvent).count() == 2


@pytest.mark.parametrize("shape", ["wechat", "standard"])
def test_api_preserves_distinct_messages_and_replays_across_new_clients(shape, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from aivan.api.main import app, get_db
    from aivan.db.models import Base

    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_TENANT_API_KEYS", '{"tenant-a":"synthetic-a","tenant-b":"synthetic-b"}')
    monkeypatch.delenv("AIVAN_TENANT_ID", raising=False)
    url = f"sqlite:///{tmp_path / 'inbound.sqlite'}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    engine.dispose()
    headers = {"X-AIVAN-Tenant-ID": "tenant-a", "X-AIVAN-API-Key": "synthetic-a",
               "X-AIVAN-Actor-ID": "service-1", "X-AIVAN-Role-Context": "operator",
               "X-AIVAN-Participant-ID": "participant-1", "X-AIVAN-Participant-Role": "buyer",
               "X-AIVAN-Participant-Conversation-Role": "buyer_thread",
               "X-AIVAN-Channel-Account-ID": "account-trusted"}

    def request(raw, supplied_headers):
        # New database engine, ORM session and HTTP client for each delivery.
        engine = create_engine(url, connect_args={"check_same_thread": False})
        Session = sessionmaker(bind=engine)
        def get_test_db():
            with Session() as db:
                yield db
        app.dependency_overrides[get_db] = get_test_db
        try:
            # Schema is initialized above; exercise the ASGI request boundary
            # without the deployment startup lifecycle or its separate DB URL.
            client = TestClient(app, raise_server_exceptions=False)
            try:
                response = client.post("/invoke", json=raw, headers=supplied_headers)
            finally:
                client.close()
            with Session() as db:
                receipts = [(r.tenant_id, r.project_id) for r in db.query(ProcessedInboundEvent).all()]
            return response, receipts
        finally:
            app.dependency_overrides.pop(get_db, None)
            engine.dispose()

    first, rows = request(payload(shape, message_id="message-1"), headers)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "ok", first.text
    assert len(rows) == 1
    original = rows[:]
    replay, rows = request(payload(shape, message_id="message-1"), headers)
    assert replay.json()["status"] == "ok", replay.text
    assert rows == original
    second, rows = request(payload(shape, message_id="message-2"), headers)
    assert second.json()["status"] == "ok", second.text
    assert len(rows) == 2
    denied, rows = request(payload(shape, message_id="message-3"), {**headers, "X-AIVAN-Tenant-ID": "tenant-b"})
    assert denied.status_code == 403
    assert len(rows) == 2
    other, rows = request(payload(shape, message_id="message-1"), {
        **headers, "X-AIVAN-Tenant-ID": "tenant-b", "X-AIVAN-API-Key": "synthetic-b"})
    assert other.json()["status"] == "ok", other.text
    assert len(rows) == 3
    assert {tenant for tenant, _ in rows} == {"tenant-a", "tenant-b"}
    foreign = payload(shape, message_id="foreign-project-message", project_id=original[0][1])
    if shape == "wechat":
        foreign["room_id"] = "unbound-supplier-thread"
    else:
        foreign["session_id"] = "unbound-supplier-thread"
    foreign_response, rows = request(foreign, {
        **headers, "X-AIVAN-Tenant-ID": "tenant-b", "X-AIVAN-API-Key": "synthetic-b",
        "X-AIVAN-Participant-ID": "supplier-b",
        "X-AIVAN-Participant-Role": "supplier",
        "X-AIVAN-Participant-Conversation-Role": "supplier_thread"})
    assert foreign_response.status_code == 200, foreign_response.text
    assert foreign_response.json()["status"] == "error", foreign_response.text
    assert all(tenant == "tenant-a" or project != original[0][1] for tenant, project in rows)
