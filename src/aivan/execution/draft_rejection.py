"""Atomic draft rejection and bounded customer-quote recovery."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from aivan.api.serializers import draft_type_from_notes
from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.db.repositories.domain_repo import CaseDomainRepository
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.domain.roles import ActorIdentity
from aivan.execution.approval_state import DraftStateError


@dataclass(frozen=True)
class DraftRejectionOutcome:
    status: str
    reopened_case_state: str | None = None


def reject_draft_atomically(
    *,
    db: Session,
    draft: InquiryDraftRecord,
    identity: ActorIdentity,
    source_trace_id: str,
) -> DraftRejectionOutcome:
    """Reject a draft and reopen a completed quote approval step when needed.

    Customer quote rejection and supplier-reply regeneration lock the same
    project row before changing drafts, so they cannot commit a pending quote
    against a case left in ``supplier_replied``.
    """

    draft_repo = DraftRepository(db)
    domain_repo = CaseDomainRepository(db)
    is_customer_quote = (
        draft.target_role == "customer"
        and draft_type_from_notes(draft) == "customer_quote_email"
    )
    project_repo = ProjectRepository(db)
    project = (
        project_repo.get_for_update(draft.project_id, tenant_id=draft.tenant_id)
        if is_customer_quote
        else project_repo.get(draft.project_id, tenant_id=draft.tenant_id)
    )

    # The request may have loaded this draft before a regeneration committed.
    # Recheck under the project transaction lock; never reject a superseded draft.
    db.refresh(draft, with_for_update=True)
    if draft.status != "pending_approval":
        raise DraftStateError("Draft is no longer pending approval")
    draft_repo.reject(draft.draft_id)
    domain_repo.record_approval(
        tenant_id=draft.tenant_id,
        case_id=draft.project_id,
        draft_id=draft.draft_id,
        identity=identity,
        source_trace_id=source_trace_id,
        status="rejected",
        requested_by_actor_id=draft.created_by_actor_id,
        requested_by_actor_role=draft.created_by_actor_role,
    )
    domain_repo.record_audit(
        tenant_id=draft.tenant_id,
        case_id=draft.project_id,
        event_type="DRAFT_REJECTED",
        identity=identity,
        source_trace_id=source_trace_id,
        before={"draft_id": draft.draft_id, "status": "pending_approval"},
        after={"draft_id": draft.draft_id, "status": "rejected"},
    )

    if project is None or project.case_state != "awaiting_approval" or not is_customer_quote:
        return DraftRejectionOutcome(status="rejected")

    pending_customer_quotes = [
        pending
        for pending in draft_repo.list_pending(
            draft.project_id, tenant_id=draft.tenant_id
        )
        if pending.target_role == "customer"
        and draft_type_from_notes(pending) == "customer_quote_email"
    ]
    if pending_customer_quotes:
        return DraftRejectionOutcome(status="rejected")

    project_repo.update_selected_option(project.project_id, None)
    domain_repo.transition_case(
        project=project,
        after="supplier_replied",
        identity=identity,
        source_trace_id=source_trace_id,
    )
    db.flush()
    return DraftRejectionOutcome(
        status="rejected", reopened_case_state="supplier_replied"
    )
