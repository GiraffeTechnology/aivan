from __future__ import annotations
import os
from aivan.openclaw.contracts import OpenClawSendRequest, OpenClawSendResponse
from aivan.openclaw.client import get_openclaw_client

def require_human_approval() -> bool:
    return os.environ.get("AIVAN_REQUIRE_HUMAN_APPROVAL", "true").lower() == "true"

def send_if_approved(draft_id: str, db_session) -> OpenClawSendResponse:
    """Send a draft message if it has been approved. Used after human approves."""
    from aivan.db.repositories.draft_repo import DraftRepository
    from aivan.utils.time_utils import utcnow_iso

    repo = DraftRepository(db_session)
    draft = repo.get(draft_id)
    if not draft:
        return OpenClawSendResponse(success=False, error=f"Draft {draft_id} not found")
    if draft.status != "approved":
        return OpenClawSendResponse(success=False, error=f"Draft {draft_id} not approved (status: {draft.status})")
    try:
        from aivan.execution.channel_policy import validate_draft_send_policy
        validate_draft_send_policy(draft)
    except ValueError:
        repo.mark_send_failed(draft_id, reason="channel_policy_blocked")
        return OpenClawSendResponse(success=False, error="CHANNEL_POLICY_BLOCKED")

    if (draft.channel or "").strip().lower() in {"email", "smtp"}:
        from aivan.openclaw.email_transport import is_real_test_email_mode, send_real_test_email

        if is_real_test_email_mode():
            try:
                response = send_real_test_email(draft)
            except Exception:
                repo.mark_send_failed(draft_id, reason="email_transport_error")
                return OpenClawSendResponse(success=False, error="email transport failed")
            if response.success:
                repo.mark_sent(draft_id)
            else:
                repo.mark_send_failed(draft_id, reason="email_transport_failed")
            return response

    client = get_openclaw_client()
    request = OpenClawSendRequest(
        channel=draft.channel or "",
        conversation_id=draft.conversation_id or "",
        target_peer_id=draft.target_peer_id or "",
        message_text=draft.message_text or "",
        message_type=draft.message_type or "text",
        attachments=draft.attachments_json or [],
    )
    try:
        response = client.send_message(request)
    except Exception:
        repo.mark_send_failed(draft_id, reason="transport_error")
        return OpenClawSendResponse(success=False, error="outbound transport failed")
    if response.success:
        repo.mark_sent(draft_id)
    else:
        repo.mark_send_failed(draft_id, reason="transport_failed")
    return response
