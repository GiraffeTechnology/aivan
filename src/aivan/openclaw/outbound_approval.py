from __future__ import annotations
import os
from dataclasses import dataclass


def require_human_approval() -> bool:
    return os.environ.get("AIVAN_REQUIRE_HUMAN_APPROVAL", "true").lower() == "true"


@dataclass
class SendDraftResult:
    success: bool
    action: str = ""   # "sent" | "awaiting_relay" | "send_failed"
    receipt: str = ""
    error: str | None = None


def send_draft(draft_id: str, db_session) -> SendDraftResult:
    """Dispatch an approved draft to the correct delivery path.

    - auto channels (email, line): call the channel adapter and mark sent.
    - guided_relay channels (wechat, wangwang): mark awaiting_relay so the
      Giraffe relay UI picks it up; no message is sent by AIVAN.
    - Unknown / legacy channels: fall back to the OpenClaw client (preserves
      existing behaviour for callers that set no channel or an unlisted one).
    """
    from aivan.channels.registry import get_send_mode
    from aivan.db.repositories.draft_repo import DraftRepository

    repo = DraftRepository(db_session)
    draft = repo.get(draft_id)
    if not draft:
        return SendDraftResult(success=False, error=f"Draft {draft_id} not found")
    if draft.status != "approved":
        return SendDraftResult(
            success=False,
            error=f"Draft {draft_id} not approved (status: {draft.status})",
        )

    channel = (draft.channel or "").lower()
    mode = get_send_mode(channel)

    if mode == "guided_relay":
        repo.mark_awaiting_relay(draft_id)
        return SendDraftResult(success=True, action="awaiting_relay")

    if mode == "auto":
        return _send_auto(draft, repo, channel)

    # Unknown channel – legacy OpenClaw path
    return _send_via_openclaw(draft, repo)


def _send_auto(draft, repo, channel: str) -> SendDraftResult:
    if channel == "email":
        from aivan.channels.email import send_email
        result = send_email(
            to_address=draft.target_peer_id or "",
            subject="AIVAN – New Message",
            body=draft.message_text or "",
        )
        if result.success:
            repo.mark_sent(
                draft.draft_id,
                receipt={"message_id": result.message_id, "sent_at": result.sent_at},
            )
            return SendDraftResult(success=True, action="sent", receipt=result.message_id)
        repo.mark_send_failed(draft.draft_id, error=result.error)
        return SendDraftResult(success=False, action="send_failed", error=result.error)

    if channel == "line":
        from aivan.channels.line import send_line_push
        result = send_line_push(
            user_id=draft.target_peer_id or "",
            message_text=draft.message_text or "",
        )
        if result.success:
            repo.mark_sent(
                draft.draft_id,
                receipt={"message_id": result.message_id, "sent_at": result.sent_at},
            )
            return SendDraftResult(success=True, action="sent", receipt=result.message_id)
        repo.mark_send_failed(draft.draft_id, error=result.error)
        return SendDraftResult(success=False, action="send_failed", error=result.error)

    # Registered as "auto" but no specific adapter: treat as legacy
    return _send_via_openclaw(draft, repo)


def _send_via_openclaw(draft, repo) -> SendDraftResult:
    from aivan.openclaw.client import get_openclaw_client
    from aivan.openclaw.contracts import OpenClawSendRequest

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
        repo.mark_sent(
            draft.draft_id,
            receipt={"message_id": response.message_id, "sent_at": response.sent_at},
        )
        return SendDraftResult(success=True, action="sent", receipt=response.message_id)
    repo.mark_send_failed(draft.draft_id, error=response.error or "")
    return SendDraftResult(success=False, action="send_failed", error=response.error)


# ---------------------------------------------------------------------------
# Backward-compat shim used by existing callers (api/main.py _do_approve_draft)
# ---------------------------------------------------------------------------

class _LegacyResponse:
    """Duck-types OpenClawSendResponse for existing callers."""
    def __init__(self, result: SendDraftResult):
        self.success = result.success
        self.error = result.error


def send_if_approved(draft_id: str, db_session) -> _LegacyResponse:
    """Legacy entry point – delegates to send_draft."""
    return _LegacyResponse(send_draft(draft_id, db_session))
