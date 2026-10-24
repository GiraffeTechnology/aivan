"""Real correction endpoints with controlled language replies; not live DB/model proof."""
from __future__ import annotations

import json

import pytest

from aivan.db.models import AuditLogRecord, EventReversalRecord, ExecutionEventRecord
from aivan.integrations.language_skill_client import LanguageSkillClient, LanguageSkillResult
from tests.test_stage5a_event_correction import _case_state_event, _headers, correction_api  # noqa: F401

CANONICAL = "The operator selected the wrong case state."


def language_result(monkeypatch, result):
    calls = []

    def normalize(_self, **kwargs):
        calls.append(kwargs)
        return result

    monkeypatch.setattr(LanguageSkillClient, "normalize", normalize)
    return calls


def valid():
    return LanguageSkillResult(True, {"canonical_language": "en", "canonical_text": CANONICAL}, None, 200)


@pytest.mark.parametrize("source", [
    "\u64cd\u4f5c\u5458\u9009\u9519\u4e86\u72b6\u6001", "L'operateur a choisi le mauvais etat.", CANONICAL,
])
def test_correction_reason_uses_shared_canonical_english_before_any_write(correction_api, monkeypatch, source):
    client, db = correction_api
    project, event = _case_state_event(db)
    original = event.payload_digest
    calls = language_result(monkeypatch, valid())
    response = client.post(f"/api/events/{event.event_id}/reverse",
        headers=_headers(idempotency_key="canonical-correction"), json={"reason": source})
    assert response.status_code == 200
    reversal = db.query(EventReversalRecord).one()
    assert reversal.reason == CANONICAL
    assert len(calls) == 1
    assert calls[0]["conversation_context"]["tenant_id"] == "tenant-a"
    correction = db.get(ExecutionEventRecord, reversal.correction_event_id)
    assert correction.payload_json["reason"] == CANONICAL and CANONICAL in correction.summary
    if source != CANONICAL:
        assert source not in json.dumps(correction.payload_json)
        assert source not in reversal.reason and source not in correction.summary
    assert project.case_state == "inquiry" and event.payload_digest == original


@pytest.mark.parametrize("result", [
    LanguageSkillResult(False, None, "sensitive synthetic language failure", None),
    LanguageSkillResult(True, {"canonical_language": "fr", "canonical_text": "Bonjour"}, None, 200),
    LanguageSkillResult(True, {"canonical_language": "en", "canonical_text": "\u672a\u7ffb\u8bd1"}, None, 200),
    LanguageSkillResult(True, None, None, 200),
])
def test_failed_correction_canonicalization_keeps_state_and_history_recoverable(correction_api, monkeypatch, result):
    client, db = correction_api
    project, event = _case_state_event(db)
    language_result(monkeypatch, result)
    before = db.query(AuditLogRecord).count()
    response = client.post(f"/api/events/{event.event_id}/reverse",
        headers=_headers(idempotency_key="blocked-language"), json={"reason": "Synthetic correction reason"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "LANGUAGE_NORMALIZATION_REQUIRED"
    assert response.json()["detail"]["trace_id"]
    assert "sensitive synthetic" not in response.text
    assert project.case_state == "sourcing"
    assert db.query(EventReversalRecord).count() == 0
    assert db.query(ExecutionEventRecord).filter_by(derived_from_event_id=event.event_id).count() == 0
    assert db.query(AuditLogRecord).count() == before


def test_committed_correction_replay_survives_language_service_unavailability(correction_api, monkeypatch):
    client, db = correction_api
    _project, event = _case_state_event(db)
    calls = language_result(monkeypatch, valid())
    request = {"headers": _headers(idempotency_key="language-replay"), "json": {"reason": CANONICAL}}
    assert client.post(f"/api/events/{event.event_id}/reverse", **request).status_code == 200
    assert len(calls) == 1
    blocked_calls = language_result(monkeypatch, LanguageSkillResult(False, None, "unavailable", None))
    replay = client.post(f"/api/events/{event.event_id}/reverse", **request)
    assert replay.status_code == 200 and replay.json()["idempotent_replay"] is True
    assert db.query(EventReversalRecord).count() == 1 and blocked_calls == []


@pytest.mark.parametrize("tenant,role,status", [("tenant-b", "admin", 404), ("tenant-a", "auditor", 403)])
def test_unauthorized_correction_never_sends_text_to_language_service(correction_api, monkeypatch, tenant, role, status):
    client, db = correction_api
    _project, event = _case_state_event(db)
    calls = language_result(monkeypatch, valid())
    response = client.post(f"/api/events/{event.event_id}/reverse",
        headers=_headers(tenant=tenant, role=role, idempotency_key="denied-language"),
        json={"reason": "Private synthetic correction reason"})
    assert response.status_code == status
    assert calls == [] and db.query(EventReversalRecord).count() == 0


def test_compensation_reason_is_canonical_without_reversing_original_state(correction_api, monkeypatch):
    client, db = correction_api
    project, event = _case_state_event(db)
    calls = language_result(monkeypatch, valid())
    response = client.post(f"/api/events/{event.event_id}/reverse",
        headers=_headers(idempotency_key="canonical-compensation"),
        json={"reason": "L'operateur a choisi le mauvais etat.", "compensation_only": True})
    assert response.status_code == 200 and response.json()["status"] == "compensation_required"
    record = db.query(EventReversalRecord).one()
    assert record.reason == CANONICAL and project.case_state == "sourcing"
    assert len(calls) == 1
    correction = db.get(ExecutionEventRecord, record.correction_event_id)
    assert correction.payload_json["reason"] == CANONICAL and CANONICAL in correction.summary
