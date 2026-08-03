import pytest

from aivan.db.models.domain import (
    AuditLogRecord,
    CaseConversationRecord,
    CaseMessageRecord,
    CaseParticipantRecord,
)
from aivan.db.models.project import Project
from aivan.db.repositories.domain_repo import CaseDomainRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.domain.roles import RoleAuthorizationError
from aivan.execution.rfq_execution import classify_event, create_rfq_from_event
from aivan.openclaw.contracts import OpenClawEvent


def _event(*, role: str, conversation_id: str, message_id: str, actor_id: str, project_id=None):
    conversation_role = {
        "buyer": "buyer_thread",
        "supplier": "supplier_thread",
    }[role]
    return OpenClawEvent(
        tenant_id="tenant_stage2",
        source_trace_id=f"trace_{message_id}",
        source="openclaw",
        channel="wechat",
        channel_account_id="acct_stage2",
        conversation_id=conversation_id,
        message_id=message_id,
        sender_id=actor_id,
        actor_id=actor_id,
        sender_display_name=actor_id,
        message_text="Quote USD 4.50, lead time 30 days" if role == "supplier" else "Need 100 units",
        project_id=project_id,
        business_role=role,
        conversation_role=conversation_role,
        execution_mode="auto",
        authorization_basis="trusted_test_gateway",
        role_context=role,
    )


def test_case_domain_keeps_buyer_and_supplier_in_distinct_threads(db_session):
    project = ProjectRepository(db_session).create(
        conversation_id="buyer-thread",
        customer_id="buyer-1",
        tenant_id="tenant_stage2",
    )
    repo = CaseDomainRepository(db_session)
    buyer = _event(
        role="buyer",
        conversation_id="buyer-thread",
        message_id="buyer-message-1",
        actor_id="buyer-1",
        project_id=project.project_id,
    )
    supplier = _event(
        role="supplier",
        conversation_id="supplier-thread",
        message_id="supplier-message-1",
        actor_id="supplier-1",
        project_id=project.project_id,
    )

    buyer_binding = repo.bind_inbound_event(project.project_id, buyer)
    supplier_binding = repo.bind_inbound_event(project.project_id, supplier)
    duplicate_binding = repo.bind_inbound_event(project.project_id, supplier)
    buyer_followup = buyer.model_copy(update={"message_id": "buyer-message-2"})
    buyer_followup_binding = repo.bind_inbound_event(
        project.project_id, buyer_followup
    )

    assert buyer_binding[0].case_id == supplier_binding[0].case_id == project.project_id
    assert buyer_binding[0].conversation_record_id != supplier_binding[0].conversation_record_id
    assert buyer_binding[1].participant_id != supplier_binding[1].participant_id
    assert duplicate_binding[2].message_record_id == supplier_binding[2].message_record_id
    assert duplicate_binding[3] is False
    assert (
        buyer_followup_binding[0].conversation_record_id
        == buyer_binding[0].conversation_record_id
    )
    assert buyer_followup_binding[1].participant_id == buyer_binding[1].participant_id
    assert db_session.query(CaseConversationRecord).count() == 2
    assert db_session.query(CaseParticipantRecord).count() == 2
    assert db_session.query(CaseMessageRecord).count() == 3


def test_bound_supplier_thread_resolves_original_case_without_new_rfq(db_session):
    project = ProjectRepository(db_session).create(
        conversation_id="buyer-thread",
        customer_id="buyer-1",
        tenant_id="tenant_stage2",
    )
    event = _event(
        role="supplier",
        conversation_id="supplier-thread",
        message_id="supplier-message-1",
        actor_id="supplier-1",
        project_id=project.project_id,
    )
    CaseDomainRepository(db_session).bind_inbound_event(project.project_id, event)
    followup = event.model_copy(
        update={"project_id": None, "message_id": "supplier-message-2"}
    )

    classification = classify_event(followup, db_session)

    assert classification.event_type == "supplier_reply"
    assert classification.project_id == project.project_id
    assert classification.validated_project_attachment is True
    assert db_session.query(Project).count() == 1


def test_unbound_supplier_reply_is_rejected_without_creating_case(db_session):
    event = _event(
        role="supplier",
        conversation_id="unknown-supplier-thread",
        message_id="unknown-message",
        actor_id="supplier-unknown",
    )

    with pytest.raises(RoleAuthorizationError) as caught:
        create_rfq_from_event(event, db_session)

    assert caught.value.code == "SUPPLIER_CASE_BINDING_REQUIRED"
    assert db_session.query(Project).count() == 0
    audit = db_session.query(AuditLogRecord).one()
    assert audit.event_type == "SUPPLIER_REPLY_REJECTED"
    assert audit.actor_id == "supplier-unknown"
    assert audit.actor_role == "supplier"
    assert audit.source_trace_id == "trace_unknown-message"
    assert audit.rejection_reason == "supplier_reply_requires_validated_case_binding"


def test_transition_audit_keeps_before_after_actor_trace_and_basis(db_session):
    identity = CaseDomainRepository.identity_for_event(
        OpenClawEvent(
            tenant_id="tenant_stage2",
            source_trace_id="trace-transition",
            conversation_id="approval-thread",
            actor_id="approver-1",
            business_role="approver",
            conversation_role="approval_thread",
            execution_mode="approval",
            authorization_basis="tenant_api_key",
        )
    )
    audit = CaseDomainRepository(db_session).record_audit(
        tenant_id="tenant_stage2",
        case_id="case-1",
        event_type="CASE_STATE_TRANSITION",
        identity=identity,
        source_trace_id="trace-transition",
        before={"case_state": "awaiting_approval"},
        after={"case_state": "approved"},
    )

    assert audit.before_json == {"case_state": "awaiting_approval"}
    assert audit.after_json == {"case_state": "approved"}
    assert audit.actor_id == "approver-1"
    assert audit.actor_role == "approver"
    assert audit.authorization_basis == "tenant_api_key"
