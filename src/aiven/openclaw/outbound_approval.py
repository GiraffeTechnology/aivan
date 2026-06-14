from __future__ import annotations
import os
from aiven.openclaw.contracts import OpenClawSendRequest, OpenClawSendResponse
from aiven.openclaw.client import get_openclaw_client

def require_human_approval() -> bool:
    return os.environ.get("AIVEN_REQUIRE_HUMAN_APPROVAL", "true").lower() == "true"

def send_if_approved(draft_id: str, db_session) -> OpenClawSendResponse:
    """Send a draft message if it has been approved. Used after human approves."""
    from aiven.db.repositories.draft_repo import DraftRepository
    from aiven.utils.time_utils import utcnow_iso

    repo = DraftRepository(db_session)
    draft = repo.get(draft_id)
    if not draft:
        return OpenClawSendResponse(success=False, error=f"Draft {draft_id} not found")
    if draft.status != "approved":
        return OpenClawSendResponse(success=False, error=f"Draft {draft_id} not approved (status: {draft.status})")

    client = get_openclaw_client()
    request = OpenClawSendRequest(
        channel=draft.channel or "",
        conversation_id=draft.conversation_id or "",
        target_peer_id=draft.target_peer_id or "",
        message_text=draft.message_text or "",
        message_type=draft.message_type or "text",
        attachments=draft.attachments_json or [],
    )
    response = client.send_message(request)
    if response.success:
        repo.mark_sent(draft_id)
    return response
