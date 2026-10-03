"""Case-state recovery helpers for inquiry draft decisions."""

from __future__ import annotations

from sqlalchemy.orm import Session

from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.db.repositories.domain_repo import CaseDomainRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.domain.roles import ActorIdentity


def recover_case_after_quote_rejection(
    *,
    db: Session,
    draft: InquiryDraftRecord,
    identity: ActorIdentity,
    source_trace_id: str,
) -> None:
    """Return a case to supplier review only when its last quote draft is rejected.

    The caller must already hold the project row lock acquired before changing
    the draft.  Re-checking pending drafts while that lock is held prevents a
    rejection from overwriting a newer quote recommendation's case state on
    databases that implement ``SELECT ... FOR UPDATE``.
    """

    if "draft_type=customer_quote_email" not in (draft.notes or ""):
        return
    project_repo = ProjectRepository(db)
    project = project_repo.get(draft.project_id, tenant_id=draft.tenant_id)
    if project is None or project.case_state != "awaiting_approval":
        return
    pending_quote_exists = (
        db.query(InquiryDraftRecord)
        .filter(
            InquiryDraftRecord.tenant_id == draft.tenant_id,
            InquiryDraftRecord.project_id == draft.project_id,
            InquiryDraftRecord.status == "pending_approval",
            InquiryDraftRecord.notes.contains("draft_type=customer_quote_email"),
        )
        .first()
        is not None
    )
    if pending_quote_exists:
        return
    project_repo.update_selected_option(project.project_id, None)
    CaseDomainRepository(db).transition_case(
        project=project,
        after="supplier_replied",
        identity=identity,
        source_trace_id=source_trace_id,
    )
