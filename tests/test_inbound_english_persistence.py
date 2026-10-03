"""English-only intake persistence; transports here are unit fixtures, not E2E."""
from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from aivan.integrations import language_skill_client
from aivan.integrations.language_skill import apply_to_requirement
from aivan.openclaw.contracts import OpenClawEvent
from aivan.schemas.requirement import BuyerRequirement

RAW = "询价5000件衬衫，45天交东京"
ENGLISH = "Inquiry for 5000 shirts, delivery to Tokyo within 45 days."


def packet():
    return {
        "normalize": {
            "raw_text": RAW,
            "language": {"detected": "zh"},
            "canonical_language": "en",
            "canonical_text": ENGLISH,
            "field_evidence": {"destination": {"value": "Tokyo", "span": "交东京"}},
            "canonical_packet": {"destination": "Tokyo", "audit": {"raw": RAW}},
            "warnings": ["需核对"],
            "translation": {"provider": "ctranslate2", "source_text": RAW},
            "trace_id": "language-unit-1",
        },
        "structure": {
            "validation_status": "valid",
            "structured": {
                "quantity": 5000, "quantity_unit": "pcs", "product_name": "shirt",
                "product_category": "apparel", "destination": "Tokyo", "lead_time_days": 45,
            },
            "field_sources": {"destination": {"source": "language_skill", "raw": "东京"}},
        },
    }


@pytest.fixture
def translator(monkeypatch):
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "true")
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        key = "normalize" if request.url.path.endswith("normalize") else "structure"
        return httpx.Response(200, json=packet()[key])

    language_skill_client.set_default_transport(httpx.MockTransport(handle))
    yield requests
    language_skill_client.set_default_transport(None)


def assert_no_source(value):
    text = json.dumps(value, ensure_ascii=False)
    assert not any(char in text for char in "询衬东京需核对"), text


def test_requirement_nested_provenance_keeps_hash_not_source():
    req = BuyerRequirement(project_id="p", raw_text=RAW)
    apply_to_requirement(req, packet())
    assert req.raw_text == ENGLISH
    assert req.extra["language_skill"]["source_text_sha256"] == hashlib.sha256(RAW.encode()).hexdigest()
    assert req.destination == "Tokyo"
    assert_no_source(req.model_dump())


def test_requirement_agent_never_reintroduces_source_aliases(translator, monkeypatch):
    from aivan.agents import requirement_agent
    monkeypatch.setattr(requirement_agent, "llm_complete_json", lambda *a, **k: {})
    req = requirement_agent.structure_customer_requirement_with_llm(RAW, project_id="p")
    assert "destination_raw" not in req.extra
    assert "product_raw" not in req.extra
    assert_no_source(req.model_dump())


def test_real_intake_pending_requirement_stores_only_english(translator, db_session):
    from aivan.execution.rfq_execution import create_rfq_from_event
    from aivan.db.models import Project, ExecutionEventRecord
    event = OpenClawEvent(tenant_id="unit-tenant", conversation_id="english-case",
                          sender_id="buyer", business_role="buyer", message_text=RAW,
                          message_id="english-message")
    result = create_rfq_from_event(event, db_session)
    assert result.project_id
    projects = db_session.query(Project).all()
    assert len(projects) == 1
    assert projects[0].requirement_json["raw_text"] == ENGLISH
    assert_no_source(projects[0].requirement_json)
    for row in db_session.query(ExecutionEventRecord).all():
        assert_no_source(row.payload_json)


def test_normalization_runs_before_classifier_with_trusted_tenant(translator, db_session, monkeypatch):
    from aivan.execution import rfq_execution
    captured = []
    def classify(event, db):
        captured.append(event)
        raise RuntimeError("classifier sentinel")
    monkeypatch.setattr(rfq_execution, "classify_event", classify)
    event = OpenClawEvent(tenant_id="unit-tenant", actor_id="actor", conversation_id="c",
                          message_text=RAW, business_role="supplier")
    with pytest.raises(RuntimeError, match="classifier sentinel"):
        rfq_execution.create_rfq_from_event(event, db_session)
    assert captured[0].message_text == ENGLISH
    assert captured[0].tenant_id == "unit-tenant"
    assert captured[0].actor_id == "actor"
    assert translator[0]["conversation_context"]["tenant_id"] == "unit-tenant"
    assert event.message_text == RAW


def test_missing_translation_stops_before_any_db_or_workflow_write(monkeypatch, db_session):
    from aivan.execution import rfq_execution
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")
    calls = []
    monkeypatch.setattr(rfq_execution, "classify_event", lambda *a: calls.append("classified"))
    event = OpenClawEvent(tenant_id="unit-tenant", conversation_id="c", message_text=RAW)
    with pytest.raises(Exception, match="LANGUAGE_NORMALIZATION_REQUIRED"):
        rfq_execution.create_rfq_from_event(event, db_session)
    assert calls == []
    assert not db_session.new and not db_session.dirty


def test_non_english_canonical_packet_is_rejected_before_write(translator, monkeypatch, db_session):
    from aivan.execution import rfq_execution
    bad = packet()
    bad["normalize"]["canonical_text"] = RAW
    monkeypatch.setattr(rfq_execution, "canonicalize_rfq", lambda *a, **k: bad)
    with pytest.raises(Exception, match="LANGUAGE_NORMALIZATION_REQUIRED"):
        rfq_execution.create_rfq_from_event(
            OpenClawEvent(tenant_id="unit-tenant", conversation_id="c", message_text=RAW), db_session
        )
    assert not db_session.new and not db_session.dirty


def test_untranslated_structured_fact_is_not_downgraded_to_digest(translator, monkeypatch, db_session):
    from aivan.execution import rfq_execution
    bad = packet()
    bad["structure"]["structured"]["destination"] = "东京"
    monkeypatch.setattr(rfq_execution, "canonicalize_rfq", lambda *a, **k: bad)
    with pytest.raises(Exception, match="LANGUAGE_NORMALIZATION_REQUIRED"):
        rfq_execution.create_rfq_from_event(
            OpenClawEvent(tenant_id="unit-tenant", conversation_id="c", message_text=RAW), db_session
        )
    assert not db_session.new and not db_session.dirty


def test_api_missing_language_service_returns_safe_retryable_error(api_client, monkeypatch):
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")
    response = api_client.post("/invoke", json={"conversation_id": "c", "message_text": RAW})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "LANGUAGE_NORMALIZATION_REQUIRED"
    assert detail["trace_id"]
    assert RAW not in response.text
