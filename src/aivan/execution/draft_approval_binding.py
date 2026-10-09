"""Existing approval transition, bound to a reviewed transient rendering."""
from dataclasses import replace
from datetime import datetime, timezone

from fastapi import HTTPException

from aivan.db.repositories.project_repo import ProjectRepository
from aivan.execution.channel_policy import DeliveryMode, get_channel_capability
from aivan.execution.draft_preview import PreviewError, verify_preview


def reviewed_channel(db, draft, preview_id, identity, trace_id):
    ProjectRepository(db).get_for_update(draft.project_id, tenant_id=draft.tenant_id)
    db.refresh(draft)
    if draft.status != "pending_approval":
        raise HTTPException(409, detail={"error": "DRAFT_APPROVAL_CHANGED"})
    try:
        preview, rendered = verify_preview(db, draft, preview_id, identity=identity, trace_id=trace_id)
    except PreviewError as exc:
        raise HTTPException(exc.status_code, detail={"error": exc.code}) from None
    capability = get_channel_capability(draft.channel)
    if rendered.manual_delivery:
        capability = replace(capability, delivery_mode=DeliveryMode.GUIDED_RELAY)
    return preview, capability


def missing_relay_bindings(draft, verified_preview):
    """Keep adapter account binding for native relay, with reviewed manual delivery."""
    manual = verified_preview.after_json.get("manual_delivery") is True
    fields = (
        ("channel_account_id", draft.channel_account_id),
        ("conversation_id", draft.conversation_id),
        ("target_peer_id", draft.target_peer_id),
    )
    return [field for field, value in fields
            if not (value or "").strip() and not (field == "channel_account_id" and manual)]


def claim_pending_approval(db, draft, actor_id, manual):
    status = "approved_pending_send" if manual else "approved"
    changed = db.query(type(draft)).filter(
        type(draft).draft_id == draft.draft_id, type(draft).tenant_id == draft.tenant_id,
        type(draft).status == "pending_approval",
        type(draft).message_text == draft.message_text,
        type(draft).target_peer_id == draft.target_peer_id,
        type(draft).channel_account_id == draft.channel_account_id,
    ).update({"status": status, "approved_by": actor_id,
              "approved_at": datetime.now(timezone.utc)}, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise HTTPException(409, detail={"error": "DRAFT_APPROVAL_CHANGED"})
    db.refresh(draft)
    return status
