"""Manual web delivery needs human review, not a connected transport account."""
from __future__ import annotations

import pytest

from aivan.db.models import AuditLogRecord, RelayReceiptRecord
from tests.test_localized_draft_preview import boundary  # noqa: F401
from tests.test_stage4_relay import _draft, _tenant_headers, relay_api  # noqa: F401


def accountless_draft(relay_api, channel="line"):
    client, db = relay_api
    draft = _draft(db, channel=channel)
    draft.channel_account_id = ""
    db.commit()
    return client, db, draft


def manual_preview(client, draft):
    response = client.post(
        f"/api/drafts/{draft.draft_id}/preview", headers=_tenant_headers(),
        json={"target_language": "en", "manual_delivery": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def approve(client, draft, proof, headers=None):
    return client.post(
        f"/api/drafts/{draft.draft_id}/approve",
        headers=headers or _tenant_headers(), json={"preview_id": proof["preview_id"]},
    )


def confirm(client, draft, proof, headers=None):
    return client.post(
        f"/api/relay/{draft.draft_id}/confirm",
        headers=headers or _tenant_headers(**{"Idempotency-Key": "accountless-manual-receipt"}),
        json={"receipt_reference": "human-confirmed-external-send",
              "preview_id": proof["preview_id"], "content_sha256": proof["rendered_sha256"]},
    )


@pytest.mark.parametrize("channel", ["email", "smtp", "wechat", "wangwang", "line", "whatsapp"])
def test_reviewed_manual_delivery_without_account_records_only_human_receipt(
    relay_api, boundary, monkeypatch, channel,
):
    client, db, draft = accountless_draft(relay_api, channel)
    # A configured email adapter does not identify the sender of a message the
    # human will send from their own external application.
    monkeypatch.setenv("AIVAN_PRESET_MAILBOX", "adapter@example.invalid")
    proof = manual_preview(client, draft)
    assert proof["manual_delivery"] is True
    assert proof["sender"] == "Manual sender (account not recorded)"
    assert proof["channel_account_id"] == ""
    assert draft.status == "pending_approval" and not boundary["sends"]
    assert db.query(RelayReceiptRecord).count() == 0
    assert confirm(client, draft, proof).status_code == 409
    assert draft.status == "pending_approval"

    approved = approve(client, draft, proof)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved_pending_send"
    assert approved.json()["relay_required"] is True
    assert approved.json()["sent"] is False
    assert not boundary["sends"] and db.query(RelayReceiptRecord).count() == 0
    assert approve(client, draft, proof).status_code == 409

    outbox = client.get("/api/relay/outbox", headers=_tenant_headers()).json()["outbox"]
    assert len(outbox) == 1 and outbox[0]["draft_id"] == draft.draft_id
    assert outbox[0]["channel_account_id"] == ""
    assert outbox[0]["copy_payload"]["message_text"] == proof["message_text"]
    assert outbox[0]["content_sha256"] == proof["rendered_sha256"]
    result = confirm(client, draft, proof)
    assert result.status_code == 200, result.text
    receipt = result.json()["receipt"]
    assert result.json()["status"] == "relayed"
    assert receipt["draft_id"] == draft.draft_id and receipt["case_id"] == draft.project_id
    assert receipt["channel_account_id"] == "" and receipt["external_message_id"] == ""
    assert receipt["receipt_reference"] == "human-confirmed-external-send"
    assert confirm(client, draft, proof).json()["idempotent_replay"] is True
    assert db.query(RelayReceiptRecord).count() == 1
    assert db.query(AuditLogRecord).filter_by(event_type="RELAY_DELIVERY_CONFIRMED").count() == 1
    assert not boundary["sends"] and draft.channel_account_id == ""


@pytest.mark.parametrize("channel", ["email", "line", "whatsapp"])
@pytest.mark.parametrize("missing", ["conversation_id", "target_peer_id"])
def test_manual_delivery_still_requires_conversation_and_recipient(
    relay_api, boundary, channel, missing,
):
    client, db, draft = accountless_draft(relay_api, channel)
    setattr(draft, missing, "")
    db.commit()
    proof = manual_preview(client, draft)
    result = approve(client, draft, proof)
    assert result.status_code == 409
    assert result.json()["detail"] == {"error": "RELAY_BINDING_INCOMPLETE", "missing": [missing]}
    assert draft.status == "pending_approval"
    assert db.query(RelayReceiptRecord).count() == 0 and not boundary["sends"]


@pytest.mark.parametrize("channel", ["wechat", "wangwang"])
def test_native_relay_without_account_still_fails_closed(relay_api, boundary, channel):
    client, db, draft = accountless_draft(relay_api, channel)
    preview = client.post(
        f"/api/openclaw/drafts/{draft.draft_id}/preview", headers=_tenant_headers(),
        json={"target_language": "en"},
    )
    assert preview.status_code == 200 and preview.json()["manual_delivery"] is False
    result = client.post(
        f"/api/openclaw/drafts/{draft.draft_id}/approve", headers=_tenant_headers(),
        json={"preview_id": preview.json()["preview_id"]},
    )
    assert result.status_code == 409
    assert result.json()["detail"] == {
        "error": "RELAY_BINDING_INCOMPLETE", "missing": ["channel_account_id"],
    }
    assert draft.status == "pending_approval" and not boundary["sends"]
    assert db.query(RelayReceiptRecord).count() == 0


def test_accountless_manual_delivery_remains_tenant_scoped(relay_api, boundary):
    client, db, draft = accountless_draft(relay_api)
    proof = manual_preview(client, draft)
    foreign = _tenant_headers("tenant-b", **{"Idempotency-Key": "foreign-confirm"})
    assert client.post(f"/api/drafts/{draft.draft_id}/preview", headers=foreign,
                       json={"target_language": "en"}).status_code == 404
    assert approve(client, draft, proof, foreign).status_code == 404
    assert confirm(client, draft, proof, foreign).status_code == 404
    assert draft.status == "pending_approval"
    assert approve(client, draft, proof).status_code == 200
    assert client.get("/api/relay/outbox", headers=foreign).json()["outbox"] == []
    assert confirm(client, draft, proof, foreign).status_code == 404
    assert draft.status == "approved_pending_send"
    assert db.query(RelayReceiptRecord).count() == 0 and not boundary["sends"]


@pytest.mark.parametrize("other_tenant", ["tenant-a", "tenant-b"])
def test_accountless_manual_approval_rejects_another_drafts_preview(
    relay_api, boundary, other_tenant,
):
    client, db, draft = accountless_draft(relay_api)
    other = _draft(db, channel="line", tenant_id=other_tenant, suffix="other")
    other.channel_account_id = ""
    db.commit()
    response = client.post(
        f"/api/drafts/{other.draft_id}/preview", headers=_tenant_headers(other_tenant),
        json={"target_language": "en"},
    )
    assert response.status_code == 200
    result = approve(client, draft, response.json())
    assert result.status_code == 404
    assert result.json()["detail"]["error"] == "DRAFT_PREVIEW_NOT_FOUND"
    assert draft.status == "pending_approval"
    assert db.query(RelayReceiptRecord).count() == 0 and not boundary["sends"]


@pytest.mark.parametrize("change", ["message_text", "channel_account_id", "conversation_id", "target_peer_id"])
def test_accountless_manual_preview_rejects_changed_source(relay_api, boundary, change):
    client, db, draft = accountless_draft(relay_api)
    proof = manual_preview(client, draft)
    setattr(draft, change, "Changed reviewed value")
    db.commit()
    result = approve(client, draft, proof)
    assert result.status_code == 409
    assert result.json()["detail"]["error"] == "DRAFT_PREVIEW_SOURCE_CHANGED"
    assert draft.status == "pending_approval"
    assert db.query(RelayReceiptRecord).count() == 0 and not boundary["sends"]


@pytest.mark.parametrize("field,value", [("preview_id", "render_" + "0" * 32),
                                         ("rendered_sha256", "0" * 64)])
def test_accountless_manual_receipt_rejects_changed_preview(relay_api, boundary, field, value):
    client, db, draft = accountless_draft(relay_api)
    proof = manual_preview(client, draft)
    assert approve(client, draft, proof).status_code == 200
    result = confirm(client, draft, {**proof, field: value})
    assert result.status_code == 409
    assert result.json()["detail"]["error"] == "RELAY_PREVIEW_VERSION_MISMATCH"
    assert draft.status == "pending_approval"
    assert db.query(RelayReceiptRecord).count() == 0 and not boundary["sends"]
