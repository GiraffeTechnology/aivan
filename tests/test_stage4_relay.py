from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aivan.api.main import app, get_db
from aivan.db.models import (
    AuditLogRecord,
    Base,
    CaseConversationRecord,
    CaseParticipantRecord,
    RelayReceiptRecord,
)
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.execution.channel_policy import (
    DeliveryMode,
    get_channel_capability,
    list_channel_capabilities,
)


@pytest.fixture
def relay_api():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    def override_db():
        yield db

    os.environ.pop("AIVAN_API_KEY", None)
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, db
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def _draft(db, *, tenant_id="tenant-a", channel="wechat", suffix="1"):
    return DraftRepository(db).create(
        f"case-{suffix}",
        {
            "tenant_id": tenant_id,
            "conversation_id": f"conversation-{suffix}",
            "channel": channel,
            "channel_account_id": f"account-{suffix}",
            "target_peer_id": f"buyer-{suffix}",
            "target_role": "buyer",
            "message_text": f"Approved relay message {suffix}",
            "created_by_agent": "stage4-test",
        },
    )


def _tenant_headers(tenant="tenant-a", **extra):
    return {"X-AIVAN-Tenant-ID": tenant, **extra}


def test_channel_capability_registry_matches_stage4_contract():
    matrix = {item["channel"]: item["delivery_mode"] for item in list_channel_capabilities()}
    assert matrix == {
        "email": "auto_send",
        "line": "auto_send",
        "wechat": "guided_relay",
        "wangwang": "guided_relay",
        "whatsapp": "unsupported",
    }
    assert get_channel_capability("weixin").delivery_mode == DeliveryMode.GUIDED_RELAY
    assert get_channel_capability("ali_wangwang").delivery_mode == DeliveryMode.GUIDED_RELAY
    assert get_channel_capability("unknown").delivery_mode == DeliveryMode.UNSUPPORTED


def test_guided_relay_approval_outbox_confirmation_and_audit(relay_api):
    client, db = relay_api
    draft = _draft(db)
    db.commit()

    approved = client.post(
        f"/api/drafts/{draft.draft_id}/approve", headers=_tenant_headers()
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved_pending_send"
    assert approved.json()["relay_required"] is True

    outbox = client.get("/api/relay/outbox", headers=_tenant_headers())
    assert outbox.status_code == 200
    assert outbox.json()["total"] == 1
    assert outbox.json()["outbox"][0]["channel_account_id"] == "account-1"

    headers = _tenant_headers(**{"Idempotency-Key": "manual-send-1"})
    confirmed = client.post(
        f"/api/relay/{draft.draft_id}/confirm",
        headers=headers,
        json={"receipt_reference": "wechat-screen-1"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "sent"
    assert confirmed.json()["idempotent_replay"] is False

    replay = client.post(
        f"/api/relay/{draft.draft_id}/confirm",
        headers=headers,
        json={"receipt_reference": "wechat-screen-1"},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["receipt"]["receipt_id"] == confirmed.json()["receipt"]["receipt_id"]
    assert db.query(RelayReceiptRecord).count() == 1
    assert DraftRepository(db).get(draft.draft_id).status == "sent"
    assert db.query(AuditLogRecord).filter(
        AuditLogRecord.event_type == "RELAY_DELIVERY_CONFIRMED"
    ).count() == 1


def test_relay_outbox_and_confirmation_are_tenant_scoped(relay_api):
    client, db = relay_api
    a = _draft(db, tenant_id="tenant-a", suffix="a")
    b = _draft(db, tenant_id="tenant-b", suffix="b")
    DraftRepository(db).mark_approved_pending_send(a.draft_id)
    DraftRepository(db).mark_approved_pending_send(b.draft_id)
    db.commit()

    outbox = client.get("/api/relay/outbox", headers=_tenant_headers("tenant-a")).json()
    assert [item["draft_id"] for item in outbox["outbox"]] == [a.draft_id]
    denied = client.post(
        f"/api/relay/{b.draft_id}/confirm",
        headers=_tenant_headers("tenant-a", **{"Idempotency-Key": "cross-tenant"}),
        json={"receipt_reference": "must-not-work"},
    )
    assert denied.status_code == 404


def test_whatsapp_fails_closed_and_email_never_enters_relay_outbox(relay_api):
    client, db = relay_api
    blocked = _draft(db, channel="whatsapp", suffix="wa")
    email = _draft(db, channel="email", suffix="email")
    DraftRepository(db).mark_approved_pending_send(email.draft_id)
    db.commit()

    response = client.post(
        f"/api/drafts/{blocked.draft_id}/approve", headers=_tenant_headers()
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "CHANNEL_UNSUPPORTED"
    assert client.get("/api/relay/outbox", headers=_tenant_headers()).json()["total"] == 0


def test_guided_relay_approval_requires_account_conversation_and_peer_binding(relay_api):
    client, db = relay_api
    draft = _draft(db, suffix="missing-binding")
    draft.channel_account_id = ""
    draft.target_peer_id = ""
    db.commit()

    response = client.post(
        f"/api/drafts/{draft.draft_id}/approve", headers=_tenant_headers()
    )
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "error": "RELAY_BINDING_INCOMPLETE",
        "missing": ["channel_account_id", "target_peer_id"],
    }


def test_relay_inbound_replays_and_binds_real_external_participant(relay_api):
    client, db = relay_api
    headers = _tenant_headers(**{"Idempotency-Key": "wechat-inbound-42"})
    payload = {
        "source": "untrusted-body-source",
        "channel": "wechat",
        "channel_account_id": "wechat-business-1",
        "conversation_id": "wechat-conversation-42",
        "message_id": "wechat-message-42",
        "sender_id": "external-buyer-42",
        "sender_display_name": "External Buyer",
        "message_text": "Please quote 100 blue cotton shirts.",
        "business_role": "buyer",
        "mode": "auto",
    }
    first = client.post("/api/relay/inbound", headers=headers, json=payload)
    second = client.post("/api/relay/inbound", headers=headers, json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["project_id"] == second.json()["project_id"]
    assert first.json()["idempotent_replay"] is False
    assert second.json()["idempotent_replay"] is True

    conversation = db.query(CaseConversationRecord).one()
    participant = db.query(CaseParticipantRecord).one()
    assert conversation.channel == "wechat"
    assert conversation.channel_account_id == "wechat-business-1"
    assert participant.actor_id == "external-buyer-42"
    assert participant.business_role == "buyer"


def test_relay_inbound_dependency_failure_is_user_visible_and_fail_soft(
    relay_api, monkeypatch
):
    client, _db = relay_api

    async def fail_pipeline(*_args, **_kwargs):
        raise RuntimeError("sensitive dependency detail")

    monkeypatch.setattr(
        "aivan.api.main._run_skill_event_with_abort", fail_pipeline
    )
    response = client.post(
        "/api/relay/inbound",
        headers=_tenant_headers(**{"Idempotency-Key": "relay-failure-1"}),
        json={
            "channel": "wechat",
            "channel_account_id": "wechat-business-1",
            "conversation_id": "failure-conversation",
            "message_id": "failure-message",
            "sender_id": "external-buyer-failure",
            "message_text": "Please quote 10 shirts.",
            "business_role": "buyer",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert response.json()["reply_text"]
    assert "sensitive dependency detail" not in response.text


def test_wechat_guided_relay_acceptance_runs_five_consecutive_times(relay_api):
    client, db = relay_api
    for run in range(1, 6):
        draft = _draft(db, suffix=f"acceptance-{run}")
        db.commit()
        approved = client.post(
            f"/api/drafts/{draft.draft_id}/approve", headers=_tenant_headers()
        )
        assert approved.status_code == 200, f"run {run}: approval failed"
        confirmed = client.post(
            f"/api/relay/{draft.draft_id}/confirm",
            headers=_tenant_headers(**{"Idempotency-Key": f"acceptance-{run}"}),
            json={"receipt_reference": f"manual-proof-{run}"},
        )
        assert confirmed.status_code == 200, f"run {run}: confirmation failed"
        assert confirmed.json()["status"] == "sent"
    assert db.query(RelayReceiptRecord).count() == 5
