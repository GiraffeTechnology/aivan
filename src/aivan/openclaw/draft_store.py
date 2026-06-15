from __future__ import annotations
from aivan.utils.ids import new_draft_id
from aivan.utils.time_utils import utcnow_iso

def create_draft_in_db(
    db_session,
    project_id: str,
    conversation_id: str,
    channel: str,
    target_peer_id: str,
    target_role: str,
    message_text: str,
    message_type: str = "text",
    attachments: list = None,
    created_by_agent: str = "trade_salesperson_agent",
    notes: str = "",
) -> str:
    """Create a draft in the database and return the draft_id."""
    from aivan.db.repositories.draft_repo import DraftRepository
    repo = DraftRepository(db_session)
    record = repo.create(project_id, {
        "conversation_id": conversation_id,
        "channel": channel,
        "target_peer_id": target_peer_id,
        "target_role": target_role,
        "message_text": message_text,
        "message_type": message_type,
        "attachments_json": attachments or [],
        "status": "pending",
        "created_by_agent": created_by_agent,
        "notes": notes,
    })
    return record.draft_id

def get_pending_drafts(db_session, project_id: str) -> list[dict]:
    from aivan.db.repositories.draft_repo import DraftRepository
    repo = DraftRepository(db_session)
    drafts = repo.list_pending(project_id)
    return [
        {
            "draft_id": d.draft_id,
            "project_id": d.project_id,
            "target_peer_id": d.target_peer_id,
            "target_role": d.target_role,
            "message_text": d.message_text,
            "status": d.status,
            "created_by_agent": d.created_by_agent,
            "created_at": d.created_at.isoformat() if d.created_at else "",
        }
        for d in drafts
    ]
