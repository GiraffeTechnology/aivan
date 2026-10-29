"""Invalidate derived commercial authorization when an inbound requirement changes."""
from fastapi import HTTPException

from aivan.db.repositories.domain_repo import CaseDomainRepository
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.event_repo import ExecutionEventRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.execution.requirement_clarification import MATERIAL_FIELDS


def lock_requirement_case(project, event, db):
    """Serialize with quotation decisions and use the latest committed case."""
    project = ProjectRepository(db).get_for_update(project.project_id, tenant_id=project.tenant_id)
    if project is None:
        raise HTTPException(404, detail={"error": "CASE_NOT_FOUND"})
    confirmation = (project.requirement_json or {}).get("order_confirmation")
    if isinstance(confirmation, dict) and confirmation.get("status") == "confirmed":
        # The existing clarification API requires a separate amendment too.
        raise HTTPException(409, detail={"error": "CONFIRMED_ORDER_REQUIRES_AMENDMENT"})
    return project


def invalidate_material_revision(project, before, requirement, event, db):
    """Stay in the caller's transaction; all recovery commits include revocation."""
    if before is None:
        return
    changed = sorted(key for key in MATERIAL_FIELDS | {"cad_attachment"}
                     if getattr(before, key) != getattr(requirement, key))
    if not changed:
        return
    if project.case_state in {"completed", "cancelled", "qc", "logistics"}:
        raise HTTPException(409, detail={"error": "REQUIREMENT_REVISION_INVALID_CASE_STATE"})
    previous_state = project.case_state
    previous_selection = project.selected_option_json
    payload = dict(project.requirement_json or {})
    graph = payload.get("giraffe_db_graph")
    if isinstance(graph, dict):
        provider_case = graph.get("procurement_case_id")
        if isinstance(provider_case, str) and provider_case:
            # Attachment ownership is stable evidence, not commercial approval.
            payload["attachment_case_reference"] = {"procurement_case_id": provider_case}
    # Historical source events/drafts remain. These fields are only the current
    # recommendation and graph pointers, not a valid quote for the revised facts.
    for key in ("buyer_options", "supplier_replies", "lead_time_estimates", "gltg_simulation",
                "gpm_guidance", "giraffe_db_graph", "execution_gate"):
        payload.pop(key, None)
    project.requirement_json = payload
    project.selected_option_json = None
    project.case_state = "inquiry"
    superseded = DraftRepository(db).supersede_requirement_drafts(
        project.project_id, tenant_id=project.tenant_id,
    )
    identity = CaseDomainRepository.identity_for_event(event)
    before_state = {"case_state": previous_state, "selected_option": previous_selection}
    after_state = {"case_state": project.case_state, "changed_fields": changed,
                   "superseded_draft_ids": superseded}
    CaseDomainRepository(db).record_audit(
        tenant_id=project.tenant_id, case_id=project.project_id,
        event_type="REQUIREMENT_APPROVAL_INVALIDATED", identity=identity,
        source_trace_id=event.source_trace_id, before=before_state, after=after_state,
    )
    ExecutionEventRepository(db).append(
        project.project_id, "REQUIREMENT_APPROVAL_INVALIDATED",
        "Material inbound requirement changed; prior commercial drafts require fresh review.",
        payload=after_state, tenant_id=project.tenant_id, source_trace_id=event.source_trace_id,
        actor=identity.actor_id, before=before_state, after=after_state,
    )
