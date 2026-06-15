from __future__ import annotations
from aivan.schemas.execution import ExecutionEvent
from aivan.utils.ids import new_id
from aivan.utils.time_utils import utcnow_iso

EVENT_TYPES = [
    "ACCOUNT_REGISTERED", "ACCOUNT_REVOKED", "ACCOUNT_PERMISSION_CHECKED",
    "OPENCLAW_AUTHORIZED_SEARCH_REQUESTED", "OPENCLAW_AUTHORIZED_MESSAGE_SEND_REQUESTED",
    "OPENCLAW_AUTHORIZED_MESSAGE_SENT",
    "PLATFORM_SUGGESTED", "PLATFORM_APPROVED", "PLATFORM_REJECTED", "PLATFORM_BLOCKED",
    "SUPPLIER_RISK_SEARCH_STARTED", "SUPPLIER_RISK_REPORT_CREATED",
    "LEADTIME_ESTIMATE_CREATED",
    "OUTBOUND_DRAFT_CREATED", "OUTBOUND_DRAFT_APPROVED", "OUTBOUND_DRAFT_REJECTED",
    "OUTBOUND_MESSAGE_SENT",
    "ORDER_CONFIRMED", "PRODUCTION_UPDATE_RECEIVED", "QC_UPDATE_RECEIVED",
    "LOGISTICS_UPDATE_RECEIVED",
    "REQUIREMENT_STRUCTURED", "CLARIFICATION_SENT", "SUPPLIER_MATCHED",
    "MARKETPLACE_SEARCH_STARTED", "MARKETPLACE_CANDIDATES_FOUND",
    "BUYER_OPTIONS_GENERATED", "BUYER_OPTION_APPROVED",
    "SUPPLIER_ACCEPTED", "PRODUCTION_STARTED", "INLINE_QC_PASSED",
    "FINAL_QC_PASSED", "LOGISTICS_HANDOVER", "BUYER_SIGNOFF",
    "EXCEPTION_DETECTED", "EXCEPTION_ESCALATED",
]

def append_event(db_session, project_id: str, event_type: str, summary: str, payload: dict = None, actor: str = "system") -> ExecutionEvent:
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    repo = ExecutionEventRepository(db_session)
    record = repo.append(project_id, event_type, summary, payload, actor)
    return ExecutionEvent(
        event_id=record.event_id,
        project_id=record.project_id,
        event_type=record.event_type,
        actor=record.actor,
        summary=record.summary,
        payload=record.payload_json or {},
        created_at=record.created_at.isoformat() if record.created_at else utcnow_iso(),
    )
