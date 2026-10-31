from aivan.db.models import ExecutionEventRecord, CaseMessageRecord
from aivan.execution.conversation_history import persist_canonical_message, resolve_canonical_message
from tests.test_myaivan_workbench import _buyer_event, _login, _seed_case, workbench  # noqa: F401


def setup_message(workbench):
    client, db = workbench
    session = _login(client)
    project = _seed_case(db, "operator-1", "history-case")
    message = db.query(CaseMessageRecord).filter_by(case_id=project.project_id).one()
    event = _buyer_event("operator-1", "history-case")
    persist_canonical_message(db, project=project, event=event, message=message)
    db.commit()
    db.expire_all()
    return client, db, project, message, event, session


def test_case_api_restores_body_from_db_and_exports_it(workbench):
    client, db, project, message, event, _ = setup_message(workbench)
    result = client.get(f"/api/workbench/cases/{project.project_id}")
    assert result.status_code == 200
    assert result.json()["messages"][0]["message_text"] == event.message_text
    assert result.json()["messages"][0]["body_resolution"] == "resolved"
    persist_canonical_message(db, project=project, event=event, message=message)
    db.commit()
    assert db.query(ExecutionEventRecord).filter_by(event_type="CANONICAL_INBOUND_MESSAGE").count() == 1
    exported = client.get(f"/api/workbench/cases/{project.project_id}/export")
    assert event.message_text in exported.text


def test_wrong_tenant_and_corrupt_content_are_not_resolved(workbench):
    client, db, project, message, _, _ = setup_message(workbench)
    record = db.query(ExecutionEventRecord).filter_by(event_type="CANONICAL_INBOUND_MESSAGE").one()
    record.tenant_id = "another-tenant"
    assert resolve_canonical_message(message, [record])["message_text"] is None
    record.tenant_id = message.tenant_id
    record.payload_json = {**record.payload_json, "message_text": "tampered"}
    assert resolve_canonical_message(message, [record])["body_resolution"] == "integrity_mismatch"
    db.commit()
    assert client.get(f"/api/workbench/cases/{project.project_id}").json()["messages"][0]["message_text"] is None


def test_historical_digest_only_message_does_not_get_invented_body(workbench):
    client, db = workbench
    _login(client)
    project = _seed_case(db, "operator-1", "legacy-history")
    item = client.get(f"/api/workbench/cases/{project.project_id}").json()["messages"][0]
    assert item["message_text"] is None
    assert item["body_resolution"] == "missing_legacy_content"
