"""Mandatory language-service boundary; all provider responses are synthetic.

These tests prove consumer ordering and persistence, not the upstream detector,
real translation model availability, or live multilingual acceptance.
"""
from __future__ import annotations

import base64
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from aivan.integrations import language_skill_client
from aivan.integrations.language_skill import LanguageNormalizationRequired
from aivan.openclaw.contracts import OpenClawEvent


SAMPLES = [
    ("es", "\u004e\u0065\u0063\u0065\u0073\u0069\u0074\u006f\u0020\u0063\u0069\u0065\u006e\u0020\u0063\u0061\u006d\u0069\u0073\u0061\u0073\u0020\u0064\u0065\u0020\u0061\u006c\u0067\u006f\u0064\u006f\u006e\u0020\u0070\u0061\u0072\u0061\u0020\u0065\u006e\u0074\u0072\u0065\u0067\u0061\u0072\u0020\u0065\u006e\u0020\u004d\u0061\u0064\u0072\u0069\u0064\u002e"),
    ("fr", "\u004a\u0065\u0020\u0073\u006f\u0075\u0068\u0061\u0069\u0074\u0065\u0020\u0063\u006f\u006d\u006d\u0061\u006e\u0064\u0065\u0072\u0020\u0063\u0065\u006e\u0074\u0020\u0063\u0068\u0065\u006d\u0069\u0073\u0065\u0073\u0020\u0065\u006e\u0020\u0063\u006f\u0074\u006f\u006e\u0020\u0070\u006f\u0075\u0072\u0020\u0050\u0061\u0072\u0069\u0073\u002e"),
    ("de", "\u0042\u0069\u0074\u0074\u0065\u0020\u0062\u0069\u0065\u0074\u0065\u006e\u0020\u0053\u0069\u0065\u0020\u0068\u0075\u006e\u0064\u0065\u0072\u0074\u0020\u0042\u0061\u0075\u006d\u0077\u006f\u006c\u006c\u0068\u0065\u006d\u0064\u0065\u006e\u0020\u006d\u0069\u0074\u0020\u004c\u0069\u0065\u0066\u0065\u0072\u0075\u006e\u0067\u0020\u006e\u0061\u0063\u0068\u0020\u0042\u0065\u0072\u006c\u0069\u006e\u0020\u0061\u006e\u002e"),
    ("en", "Please quote one hundred cotton shirts for delivery to London."),
]
CANONICAL = "Please quote one hundred cotton shirts for delivery."


def event(text: str) -> OpenClawEvent:
    return OpenClawEvent(tenant_id="test_tenant", sender_id="buyer-1",
                        conversation_id="mandatory-language", message_text=text,
                        message_id="mandatory-language-1", business_role="buyer")


def upload(text: str):
    from aivan.api.attachment_routes import Upload
    content = text.encode()
    return Upload(file_name="inquiry.txt", content_type="text/plain",
                  content_base64=base64.b64encode(content).decode(),
                  sha256=hashlib.sha256(content).hexdigest())


@pytest.mark.parametrize("language,text", SAMPLES)
@pytest.mark.parametrize("failure", ["disabled", "unavailable", "invalid_result"])
def test_no_workflow_or_storage_without_language_service(
    language, text, failure, monkeypatch, db_session,
):
    from aivan.execution import rfq_execution
    from aivan.agents.trade_salesperson_agent import handle_trade_salesperson_event
    from aivan.api.attachment_routes import _input_content
    from aivan.db.models import Project, ExecutionEventRecord

    if failure == "disabled":
        monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")
    else:
        def failed(request):
            if failure == "unavailable":
                return httpx.Response(503)
            return httpx.Response(200, json={
                "canonical_language": "en", "canonical_text": text,
                "translation": {"provider": "fixture", "model": "unavailable"},
            })
        language_skill_client.set_default_transport(httpx.MockTransport(failed))
    calls = []
    monkeypatch.setattr(rfq_execution, "classify_event", lambda *args: calls.append("classified"))
    with pytest.raises(LanguageNormalizationRequired):
        rfq_execution.create_rfq_from_event(event(text), db_session)
    with pytest.raises(LanguageNormalizationRequired):
        handle_trade_salesperson_event(event(text), db_session)
    with pytest.raises(LanguageNormalizationRequired):
        _input_content(upload(text), SimpleNamespace(tenant_id="test_tenant"))
    assert calls == []
    assert db_session.query(Project).count() == 0
    assert db_session.query(ExecutionEventRecord).count() == 0
    assert not db_session.new and not db_session.dirty


@pytest.mark.parametrize("language,text", SAMPLES)
def test_synthetic_normalization_precedes_intake_and_only_english_is_stored(
    language, text, monkeypatch, db_session,
):
    from aivan.execution import rfq_execution
    from aivan.api.attachment_routes import _input_content
    from aivan.db.models import Project, ExecutionEventRecord
    from aivan.agents import requirement_agent

    requests = []
    def provider(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if request.url.path.endswith("/normalize"):
            return httpx.Response(200, json={
                "raw_text": text, "canonical_language": "en", "canonical_text": CANONICAL,
                "language": {"detected": language, "confidence": 0.99},
                "translation": {"provider": "synthetic-fixture", "model": "test-only"},
                "field_evidence": {}, "warnings": [],
            })
        return httpx.Response(200, json={"structured": {}, "validation_status": "incomplete"})
    language_skill_client.set_default_transport(httpx.MockTransport(provider))
    monkeypatch.setattr(requirement_agent, "llm_complete_json", lambda *a, **kw: {})
    original = event(text)
    result = rfq_execution.create_rfq_from_event(original, db_session)
    assert result.project_id
    assert original.message_text == text
    project = db_session.query(Project).one()
    assert project.requirement_json["raw_text"] == CANONICAL
    records = db_session.query(ExecutionEventRecord).all()
    messages = [item for item in records if item.event_type == "CANONICAL_INBOUND_MESSAGE"]
    assert messages[0].payload_json["message_text"] == CANONICAL
    persisted = json.dumps([project.requirement_json, *[item.payload_json for item in records]])
    assert text not in persisted
    content, canonical = _input_content(upload(text), SimpleNamespace(tenant_id="test_tenant"))
    assert content == CANONICAL.encode() and canonical == CANONICAL
    assert all(body["source_language"] == "auto" and body["canonical_language"] == "en"
               for path, body in requests if path.endswith("/normalize"))
