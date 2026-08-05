from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aivan.api.main import app, get_db
from aivan.db.models import Base, EventReversalRecord, ExecutionEventRecord
from aivan.db.repositories.event_repo import ExecutionEventRepository
from aivan.db.repositories.project_repo import ProjectRepository


@pytest.fixture
def correction_api():
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


def _headers(tenant="tenant-a", role="admin", idempotency_key=""):
    headers = {
        "X-AIVAN-Tenant-ID": tenant,
        "X-AIVAN-Actor-ID": f"{role}-1",
        "X-AIVAN-Role-Context": role,
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _case_state_event(db, *, tenant="tenant-a", suffix="1"):
    project = ProjectRepository(db).create(
        f"conversation-{suffix}", f"buyer-{suffix}", tenant_id=tenant
    )
    project.case_state = "sourcing"
    event = ExecutionEventRepository(db).append(
        project.project_id,
        "CASE_STATE_TRANSITION",
        "Case moved from inquiry to sourcing",
        tenant_id=tenant,
        before={"case_state": "inquiry"},
        after={"case_state": "sourcing"},
    )
    db.commit()
    return project, event


def test_impact_and_reverse_restore_state_without_mutating_source(correction_api):
    client, db = correction_api
    project, event = _case_state_event(db)
    source_digest = event.payload_digest

    impact = client.get(
        f"/api/events/{event.event_id}/impact", headers=_headers(role="auditor")
    )
    assert impact.status_code == 200
    assert impact.json()["automatic_reverse_allowed"] is True
    assert impact.json()["affected"]["restore_value"] == "inquiry"

    reversed_response = client.post(
        f"/api/events/{event.event_id}/reverse",
        headers=_headers(idempotency_key="reverse-1"),
        json={"reason": "Operator selected the wrong state."},
    )
    assert reversed_response.status_code == 200
    payload = reversed_response.json()
    assert payload["status"] == "applied"
    assert payload["idempotent_replay"] is False
    assert project.case_state == "inquiry"
    db.refresh(event)
    assert event.payload_digest == source_digest
    assert event.correction_status == ""
    correction = db.get(
        ExecutionEventRecord, payload["reversal"]["correction_event_id"]
    )
    assert correction.derived_from_event_id == event.event_id
    assert correction.correction_status == "applied"
    assert correction.before_json == {"case_state": "sourcing"}
    assert correction.after_json == {"case_state": "inquiry"}


def test_reverse_is_idempotent_and_creates_one_correction(correction_api):
    client, db = correction_api
    _project, event = _case_state_event(db)
    request = dict(
        headers=_headers(idempotency_key="reverse-repeat"),
        json={"reason": "Correct state"},
    )
    first = client.post(f"/api/events/{event.event_id}/reverse", **request)
    second = client.post(f"/api/events/{event.event_id}/reverse", **request)
    assert first.status_code == second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert db.query(EventReversalRecord).count() == 1
    assert db.query(ExecutionEventRecord).filter(
        ExecutionEventRecord.derived_from_event_id == event.event_id
    ).count() == 1


def test_cross_tenant_event_is_hidden_and_auditor_cannot_reverse(correction_api):
    client, db = correction_api
    _project, event = _case_state_event(db, tenant="tenant-b")
    hidden = client.get(
        f"/api/events/{event.event_id}/impact", headers=_headers("tenant-a")
    )
    assert hidden.status_code == 404
    denied = client.post(
        f"/api/events/{event.event_id}/reverse",
        headers=_headers("tenant-b", role="auditor", idempotency_key="denied"),
        json={"reason": "Must not work"},
    )
    assert denied.status_code == 403
    assert db.query(EventReversalRecord).count() == 0


def test_later_same_field_mutation_blocks_reverse_but_allows_compensation(correction_api):
    client, db = correction_api
    project, event = _case_state_event(db)
    project.case_state = "awaiting_supplier"
    ExecutionEventRepository(db).append(
        project.project_id,
        "CASE_STATE_TRANSITION",
        "Case moved again",
        tenant_id="tenant-a",
        before={"case_state": "sourcing"},
        after={"case_state": "awaiting_supplier"},
    )
    db.commit()

    blocked = client.post(
        f"/api/events/{event.event_id}/reverse",
        headers=_headers(idempotency_key="unsafe"),
        json={"reason": "Too late for automatic reversal"},
    )
    assert blocked.status_code == 409
    assert "later_mutation_exists" in blocked.json()["detail"]["impact"]["blockers"]
    assert project.case_state == "awaiting_supplier"

    compensation = client.post(
        f"/api/events/{event.event_id}/reverse",
        headers=_headers(idempotency_key="compensation"),
        json={
            "reason": "Notify operator and create a corrective follow-up.",
            "compensation_only": True,
        },
    )
    assert compensation.status_code == 200
    assert compensation.json()["status"] == "compensation_required"
    assert project.case_state == "awaiting_supplier"
    correction = db.get(
        ExecutionEventRecord,
        compensation.json()["reversal"]["correction_event_id"],
    )
    assert correction.event_type == "EVENT_COMPENSATION_REQUIRED"
    assert correction.before_json == correction.after_json


def test_strategy_reversal_restores_previous_strategy(correction_api):
    client, db = correction_api
    project = ProjectRepository(db).create(
        "strategy-conversation", "buyer-strategy", tenant_id="tenant-a"
    )
    project.requirement_json = {"strategy": {"priority": "speed"}}
    event = ExecutionEventRepository(db).append(
        project.project_id,
        "STRATEGY_UPDATED",
        "Strategy changed",
        tenant_id="tenant-a",
        before={"strategy": {"priority": "cost"}},
        after={"strategy": {"priority": "speed"}},
    )
    db.commit()
    response = client.post(
        f"/api/events/{event.event_id}/reverse",
        headers=_headers(idempotency_key="reverse-strategy"),
        json={"reason": "Restore the approved cost strategy."},
    )
    assert response.status_code == 200
    assert project.requirement_json["strategy"] == {"priority": "cost"}


def test_event_append_persists_stable_payload_digest(correction_api):
    _client, db = correction_api
    project = ProjectRepository(db).create(
        "digest-conversation", "buyer-digest", tenant_id="tenant-a"
    )
    first = ExecutionEventRepository(db).append(
        project.project_id,
        "DIGEST_TEST",
        "Stable evidence",
        tenant_id="tenant-a",
        payload={"b": 2, "a": 1},
        before={"value": 1},
        after={"value": 2},
    )
    second = ExecutionEventRepository(db).append(
        project.project_id,
        "DIGEST_TEST",
        "Stable evidence",
        tenant_id="tenant-a",
        payload={"a": 1, "b": 2},
        before={"value": 1},
        after={"value": 2},
    )
    assert len(first.payload_digest) == 64
    assert first.payload_digest == second.payload_digest


def test_impact_reports_event_already_corrected(correction_api):
    client, _db = correction_api
    _project, event = _case_state_event(_db, suffix="already-corrected")
    reversed_response = client.post(
        f"/api/events/{event.event_id}/reverse",
        headers=_headers(idempotency_key="already-corrected"),
        json={"reason": "Create immutable correction evidence."},
    )
    assert reversed_response.status_code == 200

    impact = client.get(
        f"/api/events/{event.event_id}/impact", headers=_headers(role="auditor")
    )
    assert impact.status_code == 200
    payload = impact.json()
    assert payload["automatic_reverse_allowed"] is False
    assert "event_already_corrected" in payload["blockers"]
    assert payload["existing_reversal"]["source_event_id"] == event.event_id


def test_impact_reports_correction_events_cannot_be_reversed(correction_api):
    client, db = correction_api
    _project, event = _case_state_event(db, suffix="correction-event")
    reversed_response = client.post(
        f"/api/events/{event.event_id}/reverse",
        headers=_headers(idempotency_key="make-correction-event"),
        json={"reason": "Create correction event for blocker coverage."},
    )
    correction_event_id = reversed_response.json()["reversal"]["correction_event_id"]

    impact = client.get(
        f"/api/events/{correction_event_id}/impact", headers=_headers(role="auditor")
    )
    assert impact.status_code == 200
    assert impact.json()["automatic_reverse_allowed"] is False
    assert "correction_events_cannot_be_reversed" in impact.json()["blockers"]
    assert db.query(EventReversalRecord).count() == 1


def test_impact_reports_case_not_found(correction_api):
    client, db = correction_api
    event = ExecutionEventRepository(db).append(
        "missing-case",
        "CASE_STATE_TRANSITION",
        "Orphan event retained for audit",
        tenant_id="tenant-a",
        before={"case_state": "inquiry"},
        after={"case_state": "sourcing"},
    )
    db.commit()

    impact = client.get(
        f"/api/events/{event.event_id}/impact", headers=_headers(role="auditor")
    )
    assert impact.status_code == 200
    assert impact.json()["automatic_reverse_allowed"] is False
    assert "case_not_found" in impact.json()["blockers"]
    assert db.query(EventReversalRecord).count() == 0


def test_impact_reports_no_supported_materialized_state(correction_api):
    client, db = correction_api
    project = ProjectRepository(db).create(
        "unsupported-conversation", "unsupported-buyer", tenant_id="tenant-a"
    )
    event = ExecutionEventRepository(db).append(
        project.project_id,
        "UNSUPPORTED_STATE_CHANGED",
        "Unsupported field changed",
        tenant_id="tenant-a",
        before={"unsupported_field": "before"},
        after={"unsupported_field": "after"},
    )
    db.commit()

    impact = client.get(
        f"/api/events/{event.event_id}/impact", headers=_headers(role="auditor")
    )
    assert impact.status_code == 200
    assert impact.json()["affected"]["materialized_field"] == ""
    assert "no_supported_materialized_state" in impact.json()["blockers"]
    assert db.query(EventReversalRecord).count() == 0


def test_impact_reports_materialized_state_diverged(correction_api):
    client, db = correction_api
    project, event = _case_state_event(db, suffix="state-diverged")
    project.case_state = "awaiting_supplier"
    db.commit()

    impact = client.get(
        f"/api/events/{event.event_id}/impact", headers=_headers(role="auditor")
    )
    assert impact.status_code == 200
    payload = impact.json()
    assert payload["automatic_reverse_allowed"] is False
    assert "materialized_state_diverged" in payload["blockers"]
    assert payload["affected"]["current_value"] == "awaiting_supplier"
    assert project.case_state == "awaiting_supplier"
    assert db.query(EventReversalRecord).count() == 0


def test_impact_reports_derived_events_exist(correction_api):
    client, db = correction_api
    project, event = _case_state_event(db, suffix="derived-event")
    derived = ExecutionEventRepository(db).append(
        project.project_id,
        "DOWNSTREAM_ARTIFACT_CREATED",
        "Derived business artifact",
        tenant_id="tenant-a",
        derived_from_event_id=event.event_id,
    )
    db.commit()

    impact = client.get(
        f"/api/events/{event.event_id}/impact", headers=_headers(role="auditor")
    )
    assert impact.status_code == 200
    payload = impact.json()
    assert payload["automatic_reverse_allowed"] is False
    assert "derived_events_exist" in payload["blockers"]
    assert [item["event_id"] for item in payload["derived_events"]] == [
        derived.event_id
    ]
    assert project.case_state == "sourcing"
    assert db.query(EventReversalRecord).count() == 0
