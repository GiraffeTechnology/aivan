"""Actual Core routes and records; synthetic language/client unit boundaries."""
from __future__ import annotations

import pytest

from aivan.db.models import AuditLogRecord
from aivan.db.models.domain import ApprovalRecord
from aivan.integrations.language_skill_client import LanguageSkillClient, LanguageSkillResult
from tests.test_stage4_relay import _draft, _tenant_headers, relay_api  # noqa: F401


@pytest.fixture
def language(monkeypatch):
    state = {"calls": [], "text": "Please revise the price before approval.", "ok": True, "language": "en"}

    def normalize(_self, **kwargs):
        state["calls"].append(kwargs)
        return LanguageSkillResult(state["ok"], {
            "canonical_text": state["text"], "canonical_language": state["language"],
        }, None if state["ok"] else "Synthetic dependency unavailable", 200 if state["ok"] else 503)

    monkeypatch.setattr(LanguageSkillClient, "normalize", normalize)
    return state


@pytest.mark.parametrize("alias", ["/api/drafts", "/api/openclaw/drafts"])
@pytest.mark.parametrize("reason", ["Please revise the price before approval.", "请修改报价。"])
def test_operator_reason_is_canonicalized_and_read_back_in_rejection_records(relay_api, language, alias, reason):
    client, db = relay_api
    draft = _draft(db)
    db.commit()
    response = client.post(f"{alias}/{draft.draft_id}/reject", headers=_tenant_headers(), json={"reason": reason})
    assert response.status_code == 200 and response.json()["status"] == "rejected"
    db.expire_all()
    approval = db.query(ApprovalRecord).filter_by(draft_id=draft.draft_id, status="rejected").one()
    audit = db.query(AuditLogRecord).filter_by(event_type="DRAFT_REJECTED").one()
    assert approval.rejection_reason == audit.rejection_reason == language["text"]
    assert language["calls"][0]["source_text"] == reason
    assert language["calls"][0]["conversation_context"]["tenant_id"] == "tenant-a"
    assert draft.status == "rejected"
    assert client.post(f"{alias}/{draft.draft_id}/reject", headers=_tenant_headers(), json={"reason": reason}).status_code == 409
    assert db.query(ApprovalRecord).count() == 1
    if reason != language["text"]:
        assert reason not in str(audit.after_json) and reason not in approval.rejection_reason


@pytest.mark.parametrize("alias", ["/api/drafts", "/api/openclaw/drafts"])
def test_language_failure_keeps_pending_without_decision_or_reason_leak(relay_api, language, alias):
    client, db = relay_api
    draft = _draft(db)
    db.commit()
    language["ok"] = False
    source = "拒绝原因不应泄漏。"
    response = client.post(f"{alias}/{draft.draft_id}/reject", headers=_tenant_headers(), json={"reason": source})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "LANGUAGE_NORMALIZATION_REQUIRED"
    assert response.json()["detail"]["trace_id"]
    assert source not in response.text
    assert draft.status == "pending_approval"
    assert db.query(ApprovalRecord).count() == 0
    assert db.query(AuditLogRecord).filter_by(event_type="DRAFT_REJECTED").count() == 0


@pytest.mark.parametrize("bad", ["text", "language"])
def test_unverified_canonical_reason_is_not_stored(relay_api, language, bad):
    client, db = relay_api
    draft = _draft(db)
    db.commit()
    language[bad] = "未翻译" if bad == "text" else "fr"
    response = client.post(f"/api/drafts/{draft.draft_id}/reject", headers=_tenant_headers(), json={"reason": "Revise this quote."})
    assert response.status_code == 503
    assert draft.status == "pending_approval" and db.query(ApprovalRecord).count() == 0


@pytest.mark.parametrize("body", [None, {}, {"reason": ""}, {"reason": "rejected by operator"}])
def test_legacy_or_fixed_operator_rejection_does_not_require_language_call(relay_api, language, body):
    client, db = relay_api
    draft = _draft(db)
    db.commit()
    response = client.post(f"/api/drafts/{draft.draft_id}/reject", headers=_tenant_headers(), json=body)
    assert response.status_code == 200 and draft.status == "rejected"
    assert not language["calls"]
    expected = "rejected by operator" if body and body.get("reason") else ""
    assert db.query(ApprovalRecord).one().rejection_reason == expected


@pytest.mark.parametrize("boundary", ["tenant", "auditor", "superseded"])
def test_rejection_identity_and_state_fail_before_language_or_mutation(relay_api, language, boundary):
    client, db = relay_api
    draft = _draft(db)
    headers = _tenant_headers("tenant-b" if boundary == "tenant" else "tenant-a")
    if boundary == "auditor":
        headers["X-AIVAN-Role-Context"] = "auditor"
    if boundary == "superseded":
        draft.status = "superseded"
    db.commit()
    response = client.post(f"/api/drafts/{draft.draft_id}/reject", headers=headers, json={"reason": "Revise price."})
    assert response.status_code == {"tenant": 404, "auditor": 403, "superseded": 409}[boundary]
    assert not language["calls"] and db.query(ApprovalRecord).count() == 0
    assert draft.status == ("superseded" if boundary == "superseded" else "pending_approval")


def test_rejection_reason_size_and_unknown_identity_fields_are_rejected(relay_api, language):
    client, db = relay_api
    draft = _draft(db)
    db.commit()
    for body in ({"reason": "x" * 4001}, {"reason": "Revise", "approved_by": "someone-else"}):
        response = client.post(f"/api/drafts/{draft.draft_id}/reject", headers=_tenant_headers(), json=body)
        assert response.status_code == 422
    assert not language["calls"] and draft.status == "pending_approval"
    assert db.query(ApprovalRecord).count() == 0
