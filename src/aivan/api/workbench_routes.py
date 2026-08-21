from __future__ import annotations

import json
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

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
from aivan.db.session import get_db
from aivan.domain.roles import (
    BusinessRole,
    Capability,
    DEFAULT_CONVERSATION_ROLE,
    ROLE_CAPABILITIES,
    require_capability,
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
    return {
        "api_version": "0.3.0",
        "candidate_sha": os.environ.get("AIVAN_CANDIDATE_SHA", "").strip() or None,
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
