"""Authenticated participants may restore only their own conversation bodies."""
import pytest

from aivan.db.models import CaseMessageRecord, CaseParticipantRecord
from aivan.db.repositories.domain_repo import CaseDomainRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.execution.conversation_history import persist_canonical_message
from tests.test_myaivan_workbench import _buyer_event, _login, workbench  # noqa: F401


def seed_thread(db, project, actor, thread, role, body):
    event = _buyer_event(actor, thread).model_copy(update={
        "project_id": project.project_id, "business_role": role,
        "conversation_role": f"{role}_thread", "message_text": body,
    })
    CaseDomainRepository(db).bind_inbound_event(project.project_id, event)
    message = db.query(CaseMessageRecord).filter_by(case_id=project.project_id, source_message_id=event.message_id).one()
    persist_canonical_message(db, project=project, event=event, message=message)
    db.commit()
    return message


def select_role(client, role):
    login = _login(client)
    response = client.post("/api/session/role", headers={"X-AIVAN-CSRF": login["csrf_token"]}, json={"role": role})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("role", ["buyer", "supplier"])
def test_same_role_participant_cannot_read_other_conversations(workbench, monkeypatch, role):
    client, db = workbench
    monkeypatch.setenv("AIVAN_UI_ALLOWED_ROLES", "admin,buyer,supplier,approver,auditor")
    project = ProjectRepository(db).create(conversation_id="shared-case", customer_id="operator-1", tenant_id="test_tenant")
    own = seed_thread(db, project, "operator-1", "own-thread", role, "This is the requesting participant's quotation.")
    also_own = seed_thread(db, project, "operator-1", "another-own-thread", role, "This is the participant's second authorized message.")
    other = seed_thread(db, project, "other-participant", "other-thread", role, "This is another participant's private quotation.")
    inactive = seed_thread(db, project, "operator-1", "inactive-thread", role, "This message belongs to an inactive membership.")
    db.query(CaseParticipantRecord).filter_by(conversation_record_id=inactive.conversation_record_id).one().active = False
    db.commit()
    # Same actor text in a different tenant/case must not grant this thread.
    db.add_all([
        CaseParticipantRecord(participant_id="foreign-tenant-membership", tenant_id="other-tenant",
            case_id=project.project_id, conversation_record_id=other.conversation_record_id,
            actor_id="operator-1", business_role=role, conversation_role=f"{role}_thread", active=True),
        CaseParticipantRecord(participant_id="foreign-case-membership", tenant_id="test_tenant",
            case_id="other-case", conversation_record_id=other.conversation_record_id,
            actor_id="operator-1", business_role=role, conversation_role=f"{role}_thread", active=True),
    ])
    db.commit()
    from aivan.api import workbench_routes
    original_resolver = workbench_routes.resolve_canonical_message
    resolved = []
    def resolve(message, events):
        resolved.append(message.message_record_id)
        return original_resolver(message, events)
    monkeypatch.setattr(workbench_routes, "resolve_canonical_message", resolve)
    select_role(client, role)
    response = client.get(f"/api/workbench/cases/{project.project_id}")
    assert response.status_code == 200, response.text
    payload = response.json()
    allowed = {own.conversation_record_id, also_own.conversation_record_id}
    assert {item["conversation_id"] for item in payload["conversations"]} == allowed
    assert {item["conversation_id"] for item in payload["participants"]} == allowed
    assert {item["message_id"] for item in payload["messages"]} == {own.message_record_id, also_own.message_record_id}
    assert all(item["body_resolution"] == "resolved" for item in payload["messages"])
    assert other.message_record_id not in response.text and inactive.message_record_id not in response.text
    assert "another participant's private quotation" not in response.text
    assert set(resolved) == {own.message_record_id, also_own.message_record_id}
    db.query(CaseParticipantRecord).filter_by(conversation_record_id=own.conversation_record_id).one().active = False
    db.commit()
    result = client.get(f"/api/workbench/cases/{project.project_id}")
    assert {item["message_id"] for item in result.json()["messages"]} == {also_own.message_record_id}


@pytest.mark.parametrize("role", ["admin", "approver", "auditor"])
def test_authorized_internal_role_keeps_all_case_conversations(workbench, role):
    client, db = workbench
    project = ProjectRepository(db).create(conversation_id="internal-case", customer_id="buyer-a", tenant_id="test_tenant")
    buyer = seed_thread(db, project, "buyer-a", "buyer-thread", "buyer", "The buyer requests one hundred shirts.")
    supplier = seed_thread(db, project, "supplier-b", "supplier-thread", "supplier", "The supplier quotes twelve dollars per shirt.")
    select_role(client, role)
    response = client.get(f"/api/workbench/cases/{project.project_id}")
    assert response.status_code == 200
    assert {item["message_id"] for item in response.json()["messages"]} == {buyer.message_record_id, supplier.message_record_id}
    assert all(item["body_resolution"] == "resolved" for item in response.json()["messages"])
