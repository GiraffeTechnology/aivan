from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session


def authorize_draft_action(
    *, draft, identity, capability, source_trace_id: str, db: Session
) -> None:
    from aivan.db.repositories.domain_repo import CaseDomainRepository
    from aivan.domain.roles import RoleAuthorizationError, require_capability

    try:
        require_capability(identity, capability)
    except RoleAuthorizationError as exc:
        domain_repo = CaseDomainRepository(db)
        domain_repo.record_approval(
            tenant_id=draft.tenant_id,
            case_id=draft.project_id,
            draft_id=draft.draft_id,
            identity=identity,
            source_trace_id=source_trace_id,
            status="authorization_rejected",
            requested_by_actor_id=draft.created_by_actor_id,
            requested_by_actor_role=draft.created_by_actor_role,
            rejection_reason=exc.reason,
        )
        domain_repo.record_audit(
            tenant_id=draft.tenant_id,
            case_id=draft.project_id,
            event_type="DRAFT_ACTION_REJECTED",
            identity=identity,
            source_trace_id=source_trace_id,
            before={"draft_id": draft.draft_id, "status": draft.status},
            rejection_reason=exc.reason,
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail={"error": exc.code, "reason": exc.reason},
        ) from exc
