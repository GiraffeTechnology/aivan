"""Actual relay endpoint and SQLite fixture; language API responses are controlled."""
from __future__ import annotations

import pytest

from aivan.db.models import AuditLogRecord, RelayReceiptRecord
from aivan.integrations.language_skill_client import LanguageSkillClient, LanguageSkillResult
from tests.test_stage4_relay import _draft, _tenant_headers, relay_api  # noqa: F401


def approved_manual_draft(relay_api):
    client, db = relay_api
    draft = _draft(db, suffix="metadata-language")
    db.commit()
    proof = client.post(f"/api/drafts/{draft.draft_id}/preview", headers=_tenant_headers(),
                        json={"target_language": "en", "manual_delivery": True})
    assert proof.status_code == 200
    proof = proof.json()
    approved = client.post(f"/api/drafts/{draft.draft_id}/approve", headers=_tenant_headers(),
                           json={"preview_id": proof["preview_id"]})
    assert approved.status_code == 200 and approved.json()["sent"] is False
    return client, db, draft, proof


def validator(monkeypatch, result):
    calls = []

    def request(_self, method, path, json=None):
        calls.append({"method": method, "path": path, "body": json})
        assert method == "POST" and path == "/api/language/canonical-db/validate"
        return result

    monkeypatch.setattr(LanguageSkillClient, "_request", request)
    return calls


def confirm(client, draft, proof, metadata, **extra):
    return client.post(f"/api/relay/{draft.draft_id}/confirm",
        headers=_tenant_headers(**{"Idempotency-Key": "synthetic-metadata-receipt"}),
        json={"receipt_reference": "synthetic-human-receipt", "preview_id": proof["preview_id"],
              "content_sha256": proof["rendered_sha256"], "metadata": metadata, **extra})


@pytest.mark.parametrize("metadata", [
    {"note": "\u5df2\u53d1\u7ed9\u4f9b\u5e94\u5546"},
    {"delivery": {"notes": ["Bonjour, le message a ete envoye au fournisseur."]}},
    {"\u56de\u6267\u8bf4\u660e": "Synthetic receipt note"},
])
def test_non_english_receipt_metadata_cannot_be_committed(relay_api, monkeypatch, metadata):
    client, db, draft, proof = approved_manual_draft(relay_api)
    calls = validator(monkeypatch, LanguageSkillResult(True,
        {"valid": False, "violations": [{"field": "metadata_json.note", "code": "NON_ENGLISH_TEXT"}]}, None, 200))
    audit_count = db.query(AuditLogRecord).count()
    approval = draft.approval_id
    result = confirm(client, draft, proof, metadata)
    stored = db.query(RelayReceiptRecord).first()
    print({"observed_http": result.status_code, "language_calls": len(calls),
           "original_metadata_persisted": bool(stored and all(stored.metadata_json.get(key) == value
                                                            for key, value in metadata.items()))})
    assert result.status_code == 422
    assert result.json()["detail"]["error"] == "RELAY_RECEIPT_LANGUAGE_NORMALIZATION_REQUIRED"
    assert len(calls) == 1
    assert db.query(RelayReceiptRecord).count() == 0
    assert draft.status == "approved_pending_send" and draft.approval_id == approval
    assert db.query(AuditLogRecord).count() == audit_count


@pytest.mark.parametrize("result", [
    LanguageSkillResult(False, None, "sensitive synthetic upstream detail", None),
    LanguageSkillResult(True, {"valid": "true", "violations": []}, None, 200),
    LanguageSkillResult(True, {"valid": True, "violations": ["unexpected"]}, None, 200),
    LanguageSkillResult(True, {"valid": False, "violations": []}, None, 200),
    LanguageSkillResult(True, None, None, 200),
])
def test_unknown_language_result_leaves_manual_approval_recoverable(relay_api, monkeypatch, result):
    client, db, draft, proof = approved_manual_draft(relay_api)
    validator(monkeypatch, result)
    approval = draft.approval_id
    response = confirm(client, draft, proof, {"note": "Human copied the reviewed message."})
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "RELAY_RECEIPT_LANGUAGE_VALIDATION_UNAVAILABLE"
    assert "sensitive synthetic" not in response.text
    assert db.query(RelayReceiptRecord).count() == 0
    assert draft.status == "approved_pending_send" and draft.approval_id == approval


def test_verified_english_metadata_and_existing_proof_are_preserved(relay_api, monkeypatch):
    client, db, draft, proof = approved_manual_draft(relay_api)
    calls = validator(monkeypatch, LanguageSkillResult(True, {"valid": True, "violations": []}, None, 200))
    metadata = {"source": "operator_console", "delivery": {"note": "Human copied the reviewed message.", "count": 1}}
    result = confirm(client, draft, proof, metadata)
    assert result.status_code == 200 and result.json()["status"] == "relayed"
    saved = db.query(RelayReceiptRecord).one()
    assert saved.metadata_json["delivery"] == metadata["delivery"]
    assert saved.metadata_json["preview_id"] == proof["preview_id"]
    assert saved.metadata_json["rendered_sha256"] == proof["rendered_sha256"]
    assert calls[0]["body"]["repository"] == "aivan"
    assert calls[0]["body"]["table_name"] == "relay_receipts"
    assert calls[0]["body"]["policy"] == "standard_english_canonical_db_v1"


@pytest.mark.parametrize("metadata", [{}, {"source": "myaivan_mobile"}])
def test_machine_only_receipt_needs_no_text_service_and_preserves_opaque_ids(relay_api, monkeypatch, metadata):
    client, db, draft, proof = approved_manual_draft(relay_api)
    calls = validator(monkeypatch, LanguageSkillResult(False, None, "must not be called", None))
    identifier = "\u56de\u6267-id-123"
    result = confirm(client, draft, proof, metadata, external_message_id=identifier)
    assert result.status_code == 200
    assert db.query(RelayReceiptRecord).one().external_message_id == identifier
    assert calls == []


def test_existing_receipt_replay_does_not_revalidate_or_mutate_saved_proof(relay_api, monkeypatch):
    client, db, draft, proof = approved_manual_draft(relay_api)
    first = confirm(client, draft, proof, {})
    assert first.status_code == 200
    before = dict(db.query(RelayReceiptRecord).one().metadata_json)
    calls = validator(monkeypatch, LanguageSkillResult(False, None, "must not be called", None))
    replay = confirm(client, draft, proof, {"note": "\u4e0d\u5e94\u843d\u5e93"})
    assert replay.status_code == 200 and replay.json()["idempotent_replay"] is True
    assert db.query(RelayReceiptRecord).one().metadata_json == before
    assert calls == []


def test_language_outage_then_same_receipt_retry_commits_once(relay_api, monkeypatch):
    client, db, draft, proof = approved_manual_draft(relay_api)
    metadata = {"note": "Human copied the reviewed message."}
    validator(monkeypatch, LanguageSkillResult(False, None, "unavailable", None))
    assert confirm(client, draft, proof, metadata).status_code == 503
    assert draft.status == "approved_pending_send" and db.query(RelayReceiptRecord).count() == 0
    validator(monkeypatch, LanguageSkillResult(True, {"valid": True, "violations": []}, None, 200))
    first = confirm(client, draft, proof, metadata)
    assert first.status_code == 200 and first.json()["idempotent_replay"] is False
    calls = validator(monkeypatch, LanguageSkillResult(False, None, "unavailable", None))
    replay = confirm(client, draft, proof, metadata)
    assert replay.status_code == 200 and replay.json()["idempotent_replay"] is True
    assert db.query(RelayReceiptRecord).count() == 1 and calls == []
    assert db.query(AuditLogRecord).filter_by(event_type="RELAY_DELIVERY_CONFIRMED").count() == 1
