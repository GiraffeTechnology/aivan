"""Synthetic translator/transport fixtures; actual approval and durable records."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from aivan.db.models import AuditLogRecord, Base
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.execution.draft_preview import bind_approval, create_preview
from aivan.integrations.outbound_translation import TranslationUnavailable
from aivan.openclaw.contracts import OpenClawSendResponse
from aivan.openclaw.outbound_approval import send_if_approved
from tests.test_stage4_relay import _draft, _tenant_headers, relay_api  # noqa: F401

FRENCH = "\u0042\u006f\u006e\u006a\u006f\u0075\u0072\u002c\u0020\u0076\u006f\u0069\u0063\u0069\u0020\u0076\u006f\u0074\u0072\u0065\u0020\u0064\u0065\u0076\u0069\u0073\u0020\u0070\u006f\u0075\u0072\u0020\u006c\u0065\u0073\u0020\u0063\u0068\u0065\u006d\u0069\u0073\u0065\u0073\u002e"
CHANGED = "\u0042\u006f\u006e\u006a\u006f\u0075\u0072\u002c\u0020\u0063\u0065\u0020\u0064\u0065\u0076\u0069\u0073\u0020\u0065\u0073\u0074\u0020\u0064\u0069\u0066\u0066\u0065\u0072\u0065\u006e\u0074\u002e"


@pytest.fixture
def boundary(monkeypatch):
    state = {"text": FRENCH, "translations": [], "sends": [], "failure": False, "send_ok": True}

    def translate(source, target, **kwargs):
        state["translations"].append((source, target, kwargs))
        if state.get("change_on_call") == len(state["translations"]):
            state["text"] = CHANGED
        if state["failure"]:
            raise TranslationUnavailable("Synthetic translator unavailable")
        return SimpleNamespace(text=state["text"])

    class Sender:
        def send_message(self, request):
            state["sends"].append(request)
            return OpenClawSendResponse(success=state["send_ok"], message_id="synthetic-message", error=None if state["send_ok"] else FRENCH)

    monkeypatch.setattr("aivan.execution.draft_preview.translate_authoritative_english", translate)
    monkeypatch.setattr("aivan.openclaw.outbound_approval.get_openclaw_client", lambda: Sender())
    monkeypatch.setattr("aivan.execution.approval_state.get_openclaw_client", lambda: Sender())
    return state


def setup_draft(relay_api, channel="email"):
    client, db = relay_api
    draft = _draft(db, channel=channel)
    draft.message_text = "Please review the quotation for one hundred cotton shirts."
    db.commit()
    return client, db, draft


def preview(client, draft, language="fr"):
    return client.post(f"/api/drafts/{draft.draft_id}/preview", headers=_tenant_headers(),
                       json={"target_language": language})


def approve(client, draft, proof):
    return client.post(f"/api/drafts/{draft.draft_id}/approve", headers=_tenant_headers(),
                       json={"preview_id": proof["preview_id"]})


def assert_no_localized_rows(db):
    db.flush()
    for table in inspect(db.get_bind()).get_table_names():
        for row in db.execute(text(f'SELECT * FROM "{table}"')):
            for value in row:
                if isinstance(value, str):
                    assert FRENCH not in value and CHANGED not in value, table


@pytest.mark.parametrize("language", ["en", "fr"])
def test_final_body_is_previewed_then_human_approved_and_sent_once(relay_api, boundary, language):
    client, db, draft = setup_draft(relay_api)
    proof = preview(client, draft, language)
    assert proof.status_code == 200, proof.text
    assert proof.headers["cache-control"] == "no-store"
    data = proof.json()
    expected = draft.message_text if language == "en" else FRENCH
    assert data["message_text"] == expected and data["recipient"] == draft.target_peer_id
    assert not boundary["sends"]
    result = approve(client, draft, data)
    assert result.status_code == 200 and result.json()["sent"] is True, result.text
    assert len(boundary["sends"]) == 1
    assert boundary["sends"][0].message_text == expected
    assert boundary["sends"][0].channel_account_id == draft.channel_account_id
    assert approve(client, draft, data).status_code == 409
    assert len(boundary["sends"]) == 1
    assert_no_localized_rows(db)
    assert language != "en" or not boundary["translations"]


@pytest.mark.parametrize("change", ["message_text", "target_peer_id", "channel_account_id", "sender"])
def test_source_recipient_or_sender_change_invalidates_preview_before_approval(relay_api, boundary, monkeypatch, change):
    client, db, draft = setup_draft(relay_api)
    proof = preview(client, draft).json()
    if change == "sender":
        monkeypatch.setenv("AIVAN_PRESET_MAILBOX", "different-sender@example.invalid")
    else:
        setattr(draft, change, "Changed English value")
        db.commit()
    result = approve(client, draft, proof)
    assert result.status_code == 409
    assert result.json()["detail"]["error"] == "DRAFT_PREVIEW_SOURCE_CHANGED"
    assert not boundary["sends"]
    assert_no_localized_rows(db)


def test_changed_translation_cannot_be_approved_as_the_old_preview(relay_api, boundary):
    client, db, draft = setup_draft(relay_api)
    proof = preview(client, draft).json()
    boundary["text"] = CHANGED
    result = approve(client, draft, proof)
    assert result.status_code == 409
    assert not boundary["sends"] and draft.status == "pending_approval"
    assert_no_localized_rows(db)


def test_foreign_preview_cannot_be_bypassed_by_legacy_empty_approval(relay_api, boundary):
    client, _, draft = setup_draft(relay_api)
    assert preview(client, draft).status_code == 200
    result = client.post(f"/api/drafts/{draft.draft_id}/approve", headers=_tenant_headers(), json={})
    assert result.status_code == 409 and not boundary["sends"]


def test_translation_failure_leaves_pending_and_never_persists_rendered_content(relay_api, boundary):
    client, db, draft = setup_draft(relay_api)
    boundary["failure"] = True
    assert preview(client, draft).status_code == 503
    assert draft.status == "pending_approval" and not boundary["sends"]
    assert db.query(AuditLogRecord).filter_by(event_type="DRAFT_CONTENT_PREVIEWED").count() == 0
    assert_no_localized_rows(db)


def test_unknown_preview_fields_cannot_submit_a_rendered_body(relay_api, boundary):
    client, db, draft = setup_draft(relay_api)
    result = client.post(f"/api/drafts/{draft.draft_id}/preview", headers=_tenant_headers(),
                        json={"target_language": "fr", "rendered_text": FRENCH})
    assert result.status_code == 422
    assert not boundary["sends"]
    assert_no_localized_rows(db)


def test_failed_send_retry_with_changed_translation_requires_new_review(relay_api, boundary):
    client, db, draft = setup_draft(relay_api)
    proof = preview(client, draft).json()
    boundary["send_ok"] = False
    result = approve(client, draft, proof)
    assert result.status_code == 200 and result.json()["status"] == "send_failed", result.text
    assert len(boundary["sends"]) == 1
    boundary["text"] = CHANGED
    retry = client.post(f"/api/drafts/{draft.draft_id}/retry", headers=_tenant_headers())
    assert retry.status_code == 200 and retry.json()["status"] == "pending_approval", retry.text
    assert len(boundary["sends"]) == 1
    assert_no_localized_rows(db)


def test_restart_uses_durable_digest_and_rejects_new_translation(tmp_path, boundary):
    url = f"sqlite:///{tmp_path / 'preview.sqlite'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        draft = _draft(db, channel="email")
        record, _ = create_preview(db, draft, "fr")
        draft.status = "approved"
        draft.approval_id = "synthetic-approval"
        bind_approval(db, draft, record)
        draft_id = draft.draft_id
        db.commit()
        assert_no_localized_rows(db)
    engine.dispose()
    engine = create_engine(url)
    boundary["text"] = CHANGED
    with Session(engine) as db:
        result = send_if_approved(draft_id, db)
        db.commit()
        assert result.success is False
        assert DraftRepository(db).get(draft_id).status == "pending_approval"
        assert not boundary["sends"]
        assert_no_localized_rows(db)
    engine.dispose()


def test_translation_change_between_approval_and_transport_sends_nothing(relay_api, boundary):
    client, db, draft = setup_draft(relay_api)
    proof = preview(client, draft).json()
    boundary["change_on_call"] = 3
    result = approve(client, draft, proof)
    assert result.status_code == 200 and result.json()["sent"] is False
    assert result.json()["status"] == "pending_approval"
    assert not boundary["sends"]
    assert_no_localized_rows(db)


@pytest.mark.parametrize("channel", ["wechat", "line"])
def test_web_im_is_approved_for_exact_manual_copy_and_receipt_without_adapter_send(relay_api, boundary, channel):
    client, db, draft = setup_draft(relay_api, channel)
    proof = preview(client, draft).json()
    assert proof["manual_delivery"] is True and proof["delivery_mode"] == "guided_relay"
    result = approve(client, draft, proof)
    assert result.status_code == 200 and result.json()["relay_required"] is True, result.text
    assert result.json()["sent"] is False and not boundary["sends"]
    outbox = client.get("/api/relay/outbox", headers=_tenant_headers()).json()["outbox"]
    assert len(outbox) == 1 and outbox[0]["copy_payload"]["message_text"] == FRENCH
    assert outbox[0]["content_sha256"] == proof["rendered_sha256"]
    receipt = client.post(f"/api/relay/{draft.draft_id}/confirm", headers=_tenant_headers(**{"Idempotency-Key": "manual-preview-1"}),
                          json={"receipt_reference": "human-receipt-1", "preview_id": proof["preview_id"],
                                "content_sha256": proof["rendered_sha256"]})
    assert receipt.status_code == 200 and receipt.json()["status"] == "relayed", receipt.text
    assert not boundary["sends"]
    assert_no_localized_rows(db)


def test_manual_receipt_requires_the_reviewed_preview_digest(relay_api, boundary):
    client, db, draft = setup_draft(relay_api, "line")
    proof = preview(client, draft).json()
    assert approve(client, draft, proof).status_code == 200
    result = client.post(f"/api/relay/{draft.draft_id}/confirm", headers=_tenant_headers(**{"Idempotency-Key": "wrong-preview"}),
                         json={"receipt_reference": "human-receipt-1", "preview_id": proof["preview_id"],
                               "content_sha256": "0" * 64})
    assert result.status_code == 409
    assert draft.status == "pending_approval" and not boundary["sends"]
    assert_no_localized_rows(db)


def test_target_language_change_clears_an_existing_manual_approval(relay_api, boundary):
    client, db, draft = setup_draft(relay_api, "line")
    proof = preview(client, draft).json()
    assert approve(client, draft, proof).status_code == 200
    old_approval = draft.approval_id
    changed = preview(client, draft, "de")
    assert changed.status_code == 200
    assert draft.status == "pending_approval" and not draft.approval_id
    assert db.query(AuditLogRecord).filter_by(event_type="DRAFT_APPROVAL_INVALIDATED").one().after_json["previous_approval_id"] == old_approval
    assert not boundary["sends"]
    assert_no_localized_rows(db)
