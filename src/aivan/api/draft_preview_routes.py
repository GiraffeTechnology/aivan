"""Authenticated transient preview of the exact commercial message for review."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.orm import Session

from aivan.api.authorization import authorize_draft_action
from aivan.api.request_context import actor_identity_from_context, resolve_request_context
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.session import get_db
from aivan.domain.roles import Capability
from aivan.execution.channel_policy import get_channel_capability
from aivan.execution.draft_preview import PreviewError, create_preview, invalidate_approval, sender_identity

router = APIRouter()


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_language: str = Field(default="en", min_length=2, max_length=3, pattern=r"^[a-z]{2,3}$")
    manual_delivery: StrictBool = False


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str | None = Field(default=None, pattern=r"^render_[a-f0-9]{32}$")
    approved_by: str | None = None  # Ignored legacy field; authenticated identity always wins.


@router.post("/api/drafts/{draft_id}/preview")
@router.post("/api/openclaw/drafts/{draft_id}/preview")
def preview_draft(draft_id: str, body: PreviewRequest, request: Request,
                  db: Session = Depends(get_db)):
    context = resolve_request_context(request)
    draft = DraftRepository(db).get(draft_id, tenant_id=context.tenant_id)
    if draft is None:
        raise HTTPException(404, detail={"error": "DRAFT_NOT_FOUND"})
    identity = actor_identity_from_context(context, default_mode="approval")
    authorize_draft_action(draft=draft, identity=identity, capability=Capability.APPROVE_OUTBOUND,
                           source_trace_id=context.trace_id, db=db)
    # The MyAivan web preview keeps IM delivery manual. Native adapter entry
    # points retain their existing channel capability and approval contract.
    manual = body.manual_delivery or (request.url.path.startswith("/api/drafts/")
                                      and draft.channel not in {"email", "smtp"})
    if draft.status in {"approved", "approved_pending_send"}:
        invalidate_approval(db, draft, "NEW_PREVIEW_REQUESTED")
        db.commit()
    try:
        record, rendered = create_preview(db, draft, body.target_language, identity=identity,
                                          trace_id=context.trace_id, manual=manual)
    except PreviewError as exc:
        raise HTTPException(exc.status_code, detail={"error": exc.code}) from None
    db.commit()
    return JSONResponse({
        "draft_id": draft.draft_id, "case_id": draft.project_id, "preview_id": record.audit_id,
        "target_language": rendered.target_language,
        "sender": sender_identity(draft), "recipient": draft.target_peer_id,
        "channel": draft.channel, "channel_account_id": draft.channel_account_id,
        "message_text": rendered.message_text, "rendered_sha256": rendered.rendered_sha256,
        "source_sha256": rendered.source_sha256, "approval_required": True,
        "delivery_mode": "guided_relay" if manual else get_channel_capability(draft.channel).delivery_mode.value,
        "manual_delivery": manual,
    }, headers={"Cache-Control": "no-store"})
