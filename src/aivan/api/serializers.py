from __future__ import annotations


def serialize_draft(draft) -> dict:
    draft_type = ""
    for part in (draft.notes or "").split():
        if part.startswith("draft_type="):
            draft_type = part.split("=", 1)[1]
    return {
        "draft_id": draft.draft_id,
        "tenant_id": draft.tenant_id,
        "project_id": draft.project_id,
        "conversation_id": draft.conversation_id,
        "channel": draft.channel,
        "channel_account_id": draft.channel_account_id,
        "target_peer_id": draft.target_peer_id,
        "target_role": draft.target_role,
        "message_text": draft.message_text,
        "message_type": draft.message_type,
        "attachments": draft.attachments_json or [],
        "status": draft.status,
        "created_by_agent": draft.created_by_agent,
        "draft_type": draft_type,
        "approved_by": draft.approved_by,
        "notes": draft.notes,
        "created_at": str(draft.created_at),
        "approved_at": str(draft.approved_at) if draft.approved_at else None,
        "sent_at": str(draft.sent_at) if draft.sent_at else None,
    }


def serialize_preference(record) -> dict:
    return {
        "preference_id": record.preference_id,
        "user_id": record.user_id,
        "preference_type": record.preference_type,
        "value": record.value_json,
        "source": record.source,
        "confidence": record.confidence,
        "created_at": str(record.created_at),
        "updated_at": str(record.updated_at),
    }
