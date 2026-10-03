from __future__ import annotations

import json
import os
import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, ConfigDict, Field

from aivan.api.request_context import (
    RequestContext,
    actor_identity_from_context,
    resolve_request_context,
)
from aivan.db.models.domain import (
    ApprovalRecord,
    AuditLogRecord,
    CaseConversationRecord,
    CaseMessageRecord,
    CaseParticipantRecord,
)
from aivan.db.models.execution import ExecutionEventRecord
from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.db.models.project import Project
from aivan.db.models.relay import RelayReceiptRecord
from aivan.db.repositories.domain_repo import CaseDomainRepository
from aivan.db.repositories.event_repo import ExecutionEventRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.db.session import get_db
from aivan.domain.roles import (
    BusinessRole,
    Capability,
    DEFAULT_CONVERSATION_ROLE,
    ROLE_CAPABILITIES,
    require_capability,
)
from aivan.app.ui_catalog import catalog_version, ready_locales
from aivan.integrations.order_confirmation import (
    GiraffeDBOrderConfirmationClient,
    OrderConfirmationError,
)


router = APIRouter(prefix="/api/workbench", tags=["workbench"])
_INTERNAL_ROLES = {
    BusinessRole.SALES,
    BusinessRole.PROCUREMENT,
    BusinessRole.FOLLOW_UP,
    BusinessRole.QC,
    BusinessRole.LOGISTICS,
    BusinessRole.ADMIN,
    BusinessRole.APPROVER,
    BusinessRole.AUDITOR,
}


def _context(request: Request) -> RequestContext:
    return resolve_request_context(request)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _identity(context: RequestContext):
    return actor_identity_from_context(context, default_mode="audit")


def _visible_conversation_roles(context: RequestContext) -> set[str] | None:
    identity = _identity(context)
    if identity.business_role in _INTERNAL_ROLES:
        return None
    return {DEFAULT_CONVERSATION_ROLE[identity.business_role].value}


def _accessible_case_query(db: Session, context: RequestContext):
    identity = _identity(context)
    query = db.query(Project).filter(Project.tenant_id == context.tenant_id)
    if identity.business_role not in _INTERNAL_ROLES:
        query = query.filter(
            Project.project_id.in_(
                db.query(CaseParticipantRecord.case_id).filter(
                    CaseParticipantRecord.tenant_id == context.tenant_id,
                    CaseParticipantRecord.actor_id == identity.actor_id,
                    CaseParticipantRecord.active.is_(True),
                )
            )
        )
    return query


def _get_case(db: Session, context: RequestContext, case_id: str) -> Project:
    project = _accessible_case_query(db, context).filter(Project.project_id == case_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail={"error": "CASE_NOT_FOUND"})
    return project


def _case_summary(project: Project) -> dict:
    requirement = project.requirement_json or {}
    return {
        "case_id": project.project_id,
        "status": project.status,
        "case_state": project.case_state,
        "category": project.category,
        "customer_id": project.customer_id,
        "customer_display_name": project.customer_display_name,
        "channel": project.channel,
        "source_trace_id": project.source_trace_id,
        "requirement_summary": {
            key: requirement.get(key)
            for key in ("product_name", "quantity", "destination", "deadline")
            if requirement.get(key) is not None
        },
        "created_at": _iso(project.created_at),
        "updated_at": _iso(project.updated_at),
    }


def _serialize_draft(record: InquiryDraftRecord) -> dict:
    return {
        "draft_id": record.draft_id,
        "case_id": record.project_id,
        "target_role": record.target_role,
        "channel": record.channel,
        "status": record.status,
        "message_text": record.message_text,
        "content_sha256": hashlib.sha256(record.message_text.encode("utf-8")).hexdigest(),
        "message_type": record.message_type,
        "attachments": record.attachments_json or [],
        "approval_id": record.approval_id,
        "source_trace_id": record.source_trace_id,
        "created_at": _iso(record.created_at),
        "approved_at": _iso(record.approved_at),
        "delivered_at": _iso(record.sent_at),
    }


@router.get("/bootstrap")
def bootstrap(context: RequestContext = Depends(_context)):
    identity = _identity(context)
    candidate = os.environ.get("AIVAN_CANDIDATE_SHA", "").strip() or None
    return {
        "api_version": "0.3.0",
        "candidate_sha": candidate,
        "ui_catalog_version": catalog_version(),
        "ready_locales": ["en", "zh", "zht", *ready_locales(candidate)],
        "tenant_id": context.tenant_id,
        "actor": {
            "actor_id": identity.actor_id,
            "role": identity.business_role.value,
            "conversation_role": identity.conversation_role.value,
            "capabilities": sorted(item.value for item in ROLE_CAPABILITIES[identity.business_role]),
        },
        "features": {
            "guided_relay": True,
            "event_correction": True,
            "audit_export": Capability.VIEW_AUDIT in ROLE_CAPABILITIES[identity.business_role],
            "attachments": "metadata_only",
        },
    }


@router.get("/health")
def dependency_health(context: RequestContext = Depends(_context)):
    _identity(context)
    production = os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"
    return {
        "status": "ok",
        "environment": "production" if production else "non_production",
        "database": {"configured": bool(os.environ.get("AIVAN_DB_URL", "").strip())},
        "gpm": {
            "backend": os.environ.get("AIVAN_GPM_BACKEND", "memory").strip(),
            "durable_required": production,
        },
        "openclaw": {"configured": bool(os.environ.get("OPENCLAW_BASE_URL", "").strip())},
        "model": {"configured": bool(os.environ.get("AIVAN_LLM_MODEL", "").strip())},
        "candidate_sha": os.environ.get("AIVAN_CANDIDATE_SHA", "").strip() or None,
    }


@router.get("/cases")
def list_cases(
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    state: str = "",
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_context),
):
    query = _accessible_case_query(db, context)
    if state.strip():
        query = query.filter(Project.case_state == state.strip())
    total = query.count()
    records = query.order_by(Project.updated_at.desc(), Project.project_id).offset(offset).limit(limit).all()
    return {
        "items": [_case_summary(record) for record in records],
        "page": {"offset": offset, "limit": limit, "total": total, "has_more": offset + len(records) < total},
    }


@router.get("/cases/{case_id}")
def get_case_detail(
    case_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_context),
):
    project = _get_case(db, context, case_id)
    visible_roles = _visible_conversation_roles(context)
    conversations_query = db.query(CaseConversationRecord).filter(
        CaseConversationRecord.tenant_id == context.tenant_id,
        CaseConversationRecord.case_id == case_id,
    )
    if visible_roles is not None:
        conversations_query = conversations_query.filter(
            CaseConversationRecord.conversation_role.in_(visible_roles)
        )
    conversations = conversations_query.order_by(CaseConversationRecord.created_at).all()
    conversation_ids = [item.conversation_record_id for item in conversations]
    participants = []
    messages = []
    if conversation_ids:
        participants = db.query(CaseParticipantRecord).filter(
            CaseParticipantRecord.tenant_id == context.tenant_id,
            CaseParticipantRecord.case_id == case_id,
            CaseParticipantRecord.conversation_record_id.in_(conversation_ids),
        ).order_by(CaseParticipantRecord.created_at).all()
        messages = db.query(CaseMessageRecord).filter(
            CaseMessageRecord.tenant_id == context.tenant_id,
            CaseMessageRecord.case_id == case_id,
            CaseMessageRecord.conversation_record_id.in_(conversation_ids),
        ).order_by(CaseMessageRecord.created_at).all()

    identity = _identity(context)
    internal = identity.business_role in _INTERNAL_ROLES
    drafts_query = db.query(InquiryDraftRecord).filter(
        InquiryDraftRecord.tenant_id == context.tenant_id,
        InquiryDraftRecord.project_id == case_id,
    )
    if not internal:
        drafts_query = drafts_query.filter(InquiryDraftRecord.target_role == identity.business_role.value)
    drafts = drafts_query.order_by(InquiryDraftRecord.created_at).all()

    approvals = []
    receipts = []
    audits = []
    if internal:
        approvals = db.query(ApprovalRecord).filter(
            ApprovalRecord.tenant_id == context.tenant_id,
            ApprovalRecord.case_id == case_id,
        ).order_by(ApprovalRecord.created_at).all()
        receipts = db.query(RelayReceiptRecord).filter(
            RelayReceiptRecord.tenant_id == context.tenant_id,
            RelayReceiptRecord.case_id == case_id,
        ).order_by(RelayReceiptRecord.confirmed_at).all()
    if identity.business_role in {BusinessRole.ADMIN, BusinessRole.AUDITOR}:
        audits = db.query(AuditLogRecord).filter(
            AuditLogRecord.tenant_id == context.tenant_id,
            AuditLogRecord.case_id == case_id,
        ).order_by(AuditLogRecord.created_at).all()

    events = db.query(ExecutionEventRecord).filter(
        ExecutionEventRecord.tenant_id == context.tenant_id,
        ExecutionEventRecord.project_id == case_id,
    ).order_by(ExecutionEventRecord.created_at).all()
    return {
        "case": {**_case_summary(project), "requirement": project.requirement_json or {}, "selected_option": project.selected_option_json},
        "conversations": [
            {
                "conversation_id": item.conversation_record_id,
                "external_conversation_id": item.external_conversation_id,
                "role": item.conversation_role,
                "channel": item.channel,
                "created_at": _iso(item.created_at),
            }
            for item in conversations
        ],
        "participants": [
            {
                "participant_id": item.participant_id,
                "conversation_id": item.conversation_record_id,
                "actor_id": item.actor_id,
                "business_role": item.business_role,
                "conversation_role": item.conversation_role,
                "display_name": item.display_name,
                "active": item.active,
            }
            for item in participants
        ],
        "messages": [
            {
                "message_id": item.message_record_id,
                "conversation_id": item.conversation_record_id,
                "participant_id": item.participant_id,
                "actor_id": item.actor_id,
                "actor_role": item.actor_role,
                "message_type": item.message_type,
                "payload_digest": item.payload_digest,
                "content_reference": f"aivan://message-evidence/{item.message_record_id}/v1",
                "content_version": 1,
                "source_trace_id": item.source_trace_id,
                "created_at": _iso(item.created_at),
            }
            for item in messages
        ],
        "drafts": [_serialize_draft(item) for item in drafts],
        "approvals": [
            {
                "approval_id": item.approval_id,
                "draft_id": item.draft_id,
                "status": item.status,
                "approver_id": item.approver_id,
                "approver_role": item.approver_role,
                "source_trace_id": item.source_trace_id,
                "created_at": _iso(item.created_at),
                "decided_at": _iso(item.decided_at),
            }
            for item in approvals
        ],
        "receipts": [
            {
                "receipt_id": item.receipt_id,
                "draft_id": item.draft_id,
                "channel": item.channel,
                "external_message_id": item.external_message_id,
                "receipt_reference": item.receipt_reference,
                "confirmed_by": item.confirmed_by,
                "confirmed_at": _iso(item.confirmed_at),
            }
            for item in receipts
        ],
        "events": [
            {
                "event_id": item.event_id,
                "event_type": item.event_type,
                "summary": item.summary,
                "derived_from_event_id": item.derived_from_event_id,
                "payload_digest": item.payload_digest,
                "correction_status": item.correction_status,
                "source_trace_id": item.source_trace_id,
                "created_at": _iso(item.created_at),
            }
            for item in events
        ],
        "audit": [
            {
                "audit_id": item.audit_id,
                "event_type": item.event_type,
                "actor_id": item.actor_id,
                "actor_role": item.actor_role,
                "source_trace_id": item.source_trace_id,
                "rejection_reason": item.rejection_reason,
                "created_at": _iso(item.created_at),
            }
            for item in audits
        ],
    }


class DraftCopyCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.post("/cases/{case_id}/drafts/{draft_id}/copy")
def record_draft_copy(
    case_id: str, draft_id: str, body: DraftCopyCompletion,
    db: Session = Depends(get_db), context: RequestContext = Depends(_context),
):
    """Record a user's clipboard completion report, not provider delivery."""
    _get_case(db, context, case_id)
    identity = _identity(context)
    if identity.business_role == BusinessRole.AUDITOR:
        raise HTTPException(status_code=403, detail={"error": "COPY_AUDIT_READ_ONLY"})
    if not context.idempotency_key:
        raise HTTPException(status_code=400, detail={"error": "IDEMPOTENCY_KEY_REQUIRED"})
    ProjectRepository(db).get_for_update(case_id, tenant_id=context.tenant_id)
    draft = db.query(InquiryDraftRecord).filter_by(
        tenant_id=context.tenant_id, project_id=case_id, draft_id=draft_id,
    ).execution_options(populate_existing=True).first()
    if (draft is None or (identity.business_role not in _INTERNAL_ROLES
                         and draft.target_role != identity.business_role.value)):
        raise HTTPException(status_code=404, detail={"error": "DRAFT_NOT_FOUND"})
    digest = hashlib.sha256(draft.message_text.encode("utf-8")).hexdigest()
    if body.content_sha256 != digest:
        raise HTTPException(status_code=409, detail={"error": "DRAFT_COPY_VERSION_MISMATCH"})
    key = hashlib.sha256(
        f"{context.tenant_id}\0{identity.actor_id}\0{context.idempotency_key}\0copy".encode()
    ).hexdigest()[:56]
    audit_id = f"copy_{key}"
    evidence = {"draft_id": draft_id, "content_sha256": digest, "draft_status": draft.status,
                "action": "copied", "delivery_claim": False}

    def replay(record):
        if (record is None or record.tenant_id != context.tenant_id
                or record.case_id != case_id or record.actor_id != identity.actor_id
                or record.event_type != "DRAFT_COPIED" or record.after_json != evidence):
            raise HTTPException(status_code=409, detail={"error": "COPY_IDEMPOTENCY_CONFLICT"})
        return {"status": "copied", "delivery_claim": False,
                "audit_id": audit_id, "idempotent_replay": True}

    existing = db.get(AuditLogRecord, audit_id)
    if existing is not None:
        return replay(existing)
    record = AuditLogRecord(
        audit_id=audit_id, tenant_id=context.tenant_id, case_id=case_id,
        source_trace_id=context.trace_id, event_type="DRAFT_COPIED",
        actor_id=identity.actor_id, actor_role=identity.business_role.value,
        conversation_role=identity.conversation_role.value,
        authorization_basis=identity.authorization_basis,
        before_json={"draft_id": draft_id, "status": draft.status}, after_json=evidence,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return replay(db.get(AuditLogRecord, audit_id))
    return {"status": "copied", "delivery_claim": False,
            "audit_id": audit_id, "idempotent_replay": False}


def _order_confirmation_error(exc: OrderConfirmationError) -> HTTPException:
    code = exc.code
    client_conflict_codes = {
        "ORDER_CONFIRMATION_ACTOR_REQUIRED",
        "ORDER_CONFIRMATION_DB_GRAPH_REQUIRED",
        "ORDER_CONFIRMATION_IDEMPOTENCY_KEY_REQUIRED",
        "ORDER_CONFIRMATION_PROJECT_REQUIRED",
        "ORDER_CONFIRMATION_SELECTED_OPTION_REQUIRED",
        "ORDER_CONFIRMATION_SUPPLIER_ID_REQUIRED",
        "ORDER_CONFIRMATION_TENANT_REQUIRED",
        "ORDER_CONFIRMATION_TRACE_REQUIRED",
    }
    if code in client_conflict_codes:
        status_code = 409
    elif code.endswith("_NOT_FOUND") or code.endswith("_MISSING"):
        status_code = 409
    elif "IDEMPOTENCY_CONFLICT" in code:
        status_code = 409
    else:
        status_code = 503
    return HTTPException(status_code=status_code, detail={"error": code})


def _order_confirmation_client(
    *, context: RequestContext, case_id: str, option_id: str
) -> GiraffeDBOrderConfirmationClient:
    stable_trace = hashlib.sha256(
        f"{context.tenant_id}\0{case_id}\0{option_id}\0order-confirmation".encode(
            "utf-8"
        )
    ).hexdigest()
    return GiraffeDBOrderConfirmationClient(
        tenant_id=context.tenant_id,
        trace_id=f"order_{stable_trace}",
    )


@router.post("/cases/{case_id}/order-confirmation")
def confirm_case_order(
    case_id: str,
    body: dict,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_context),
):
    """Confirm the selected quote once and verify authoritative DB readback."""

    identity = _identity(context)
    try:
        require_capability(identity, Capability.APPROVE_OUTBOUND)
    except Exception as exc:
        raise HTTPException(
            status_code=403, detail={"error": "ORDER_CONFIRMATION_FORBIDDEN"}
        ) from exc
    if not context.idempotency_key:
        raise HTTPException(
            status_code=400,
            detail={"error": "ORDER_CONFIRMATION_IDEMPOTENCY_KEY_REQUIRED"},
        )

    project = ProjectRepository(db).get_for_update(
        case_id, tenant_id=context.tenant_id
    )
    if project is None:
        raise HTTPException(status_code=404, detail={"error": "CASE_NOT_FOUND"})
    selected_option = project.selected_option_json
    selected_option_id = str(body.get("selected_option_id") or "").strip()
    if not isinstance(selected_option, dict) or not selected_option_id:
        raise HTTPException(
            status_code=409,
            detail={"error": "ORDER_CONFIRMATION_SELECTED_OPTION_REQUIRED"},
        )
    if selected_option.get("option_id") != selected_option_id:
        raise HTTPException(
            status_code=409,
            detail={"error": "ORDER_CONFIRMATION_OPTION_VERSION_MISMATCH"},
        )

    requirement = dict(project.requirement_json or {})
    existing = requirement.get("order_confirmation")
    try:
        client = _order_confirmation_client(
            context=context, case_id=case_id, option_id=selected_option_id
        )
    except OrderConfirmationError as exc:
        raise _order_confirmation_error(exc) from exc
    if isinstance(existing, dict) and existing.get("status") == "confirmed":
        if existing.get("selected_option_id") != selected_option_id:
            raise HTTPException(
                status_code=409,
                detail={"error": "ORDER_CONFIRMATION_ALREADY_COMMITTED"},
            )
        try:
            result = client.reconcile_order(
                procurement_case_id=str(existing.get("procurement_case_id") or ""),
                supplier_quote_id=str(existing.get("supplier_quote_id") or ""),
                purchase_order_id=str(existing.get("purchase_order_id") or ""),
            )
        except OrderConfirmationError as exc:
            raise _order_confirmation_error(exc) from exc
        return {
            **result.as_dict(),
            "selected_option_id": selected_option_id,
            "authoritative_source": "giraffe-db",
            "recovered": True,
        }

    if project.case_state != "approved":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "ORDER_CONFIRMATION_INVALID_CASE_STATE",
                "case_state": project.case_state,
                "required_state": "approved",
            },
        )
    graph_reference = requirement.get("giraffe_db_graph")
    if not isinstance(graph_reference, dict):
        raise HTTPException(
            status_code=409,
            detail={"error": "ORDER_CONFIRMATION_DB_GRAPH_REQUIRED"},
        )
    try:
        result = client.confirm_order(
            project_id=case_id,
            graph_reference=graph_reference,
            selected_option=selected_option,
            identity=identity,
            request_key=context.idempotency_key,
        )
    except OrderConfirmationError as exc:
        db.rollback()
        raise _order_confirmation_error(exc) from exc

    projection = {
        **result.as_dict(),
        "selected_option_id": selected_option_id,
        "authoritative_source": "giraffe-db",
    }
    requirement["order_confirmation"] = projection
    project.requirement_json = requirement
    project.status = "order_confirmed"
    CaseDomainRepository(db).record_audit(
        tenant_id=project.tenant_id,
        case_id=project.project_id,
        event_type="ORDER_CONFIRMED",
        identity=identity,
        source_trace_id=context.trace_id,
        before={
            "selected_option_id": selected_option_id,
            "order_status": "unconfirmed",
        },
        after={
            "selected_option_id": selected_option_id,
            "purchase_order_id": result.purchase_order_id,
            "order_status": result.status,
            "readback_verified": result.readback_verified,
        },
    )
    ExecutionEventRepository(db).append(
        project.project_id,
        "ORDER_CONFIRMATION_PERSISTED",
        "Human-authorized order confirmation persisted and verified by readback",
        payload=projection,
        actor=identity.actor_id,
        tenant_id=project.tenant_id,
        source_trace_id=context.trace_id,
    )
    db.commit()
    return {**projection, "recovered": False}


@router.get("/cases/{case_id}/order-confirmation")
def get_case_order_confirmation(
    case_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_context),
):
    """Recover and verify the confirmed order from giraffe-db after restart."""

    project = _get_case(db, context, case_id)
    projection = (project.requirement_json or {}).get("order_confirmation")
    if not isinstance(projection, dict) or projection.get("status") != "confirmed":
        raise HTTPException(
            status_code=404, detail={"error": "ORDER_CONFIRMATION_NOT_FOUND"}
        )
    option_id = str(projection.get("selected_option_id") or "")
    try:
        client = _order_confirmation_client(
            context=context, case_id=case_id, option_id=option_id
        )
        result = client.reconcile_order(
            procurement_case_id=str(projection.get("procurement_case_id") or ""),
            supplier_quote_id=str(projection.get("supplier_quote_id") or ""),
            purchase_order_id=str(projection.get("purchase_order_id") or ""),
        )
    except OrderConfirmationError as exc:
        raise _order_confirmation_error(exc) from exc
    return {
        **result.as_dict(),
        "selected_option_id": option_id,
        "authoritative_source": "giraffe-db",
        "recovered": True,
    }


def _markdown_export(payload: dict) -> str:
    case = payload["case"]
    lines = [
        f"# AIVAN Case {case['case_id']}",
        "",
        f"- State: {case['case_state']}",
        f"- Status: {case['status']}",
        f"- Candidate: {os.environ.get('AIVAN_CANDIDATE_SHA', '').strip() or 'unfrozen'}",
        "",
    ]
    for title, key in (
        ("Conversations", "conversations"),
        ("Participants", "participants"),
        ("Messages (digest-only)", "messages"),
        ("Drafts", "drafts"),
        ("Approvals", "approvals"),
        ("Receipts", "receipts"),
        ("Events", "events"),
        ("Audit", "audit"),
    ):
        lines.extend([f"## {title}", "", "```json", json.dumps(payload[key], ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


@router.get("/cases/{case_id}/export")
def export_case(
    case_id: str,
    format: str = Query("markdown", pattern="^(markdown|json)$"),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_context),
):
    identity = _identity(context)
    try:
        require_capability(identity, Capability.VIEW_AUDIT)
    except Exception as exc:
        raise HTTPException(status_code=403, detail={"error": "AUDIT_EXPORT_FORBIDDEN"}) from exc
    payload = get_case_detail(case_id, db, context)
    candidate = os.environ.get("AIVAN_CANDIDATE_SHA", "").strip() or None
    if format == "json":
        return {"candidate_sha": candidate, "api_version": "0.3.0", **payload}
    return Response(
        _markdown_export(payload),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="aivan-case-{case_id}.md"'},
    )
