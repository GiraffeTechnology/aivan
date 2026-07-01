"""Draft approval state machine with recoverable send failures.

States (PRD §11):
    pending_approval -> approved_pending_send -> sent
                                              \\-> send_failed (recoverable)
    pending_approval -> rejected
    (any) -> superseded

The key invariant: a failed send must NEVER be left as ``approved`` /
``approved_pending_send``. It transitions to ``send_failed`` with a reason and
can be retried.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from aivan.db.repositories.draft_repo import DraftRepository
from aivan.openclaw.client import get_openclaw_client
from aivan.openclaw.contracts import OpenClawSendRequest

PENDING_APPROVAL = "pending_approval"
APPROVED_PENDING_SEND = "approved_pending_send"
SENT = "sent"
SEND_FAILED = "send_failed"
REJECTED = "rejected"
SUPERSEDED = "superseded"

TERMINAL_STATES = frozenset({SENT, REJECTED, SUPERSEDED})
APPROVABLE_STATES = frozenset({PENDING_APPROVAL, SEND_FAILED})


class DraftStateError(RuntimeError):
    """Raised for an invalid state transition."""


@dataclass
class ApprovalResult:
    draft_id: str
    status: str
    sent: bool
    error: str | None = None
    message_id: str = ""


def approve_and_send(draft_id: str, db: Session, approved_by: str = "user") -> ApprovalResult:
    """Approve a draft and attempt to send it, tracking the send outcome.

    A pending (or previously send-failed) draft is validated against channel
    policy, moved to ``approved_pending_send``, then sent. On success it becomes
    ``sent``; on failure (policy or transport) it becomes ``send_failed`` and
    remains recoverable — it is never left ``approved``.
    """
    repo = DraftRepository(db)
    draft = repo.get(draft_id)
    if draft is None:
        raise DraftStateError(f"Draft {draft_id} not found")
    if draft.status in TERMINAL_STATES:
        raise DraftStateError(
            f"Draft {draft_id} is {draft.status} and cannot be re-approved"
        )
    if draft.status not in APPROVABLE_STATES:
        raise DraftStateError(
            f"Draft {draft_id} is {draft.status}; only pending/send_failed drafts can be approved"
        )

    # Validate channel policy BEFORE transitioning past pending.
    try:
        from aivan.execution.channel_policy import validate_draft_send_policy

        validate_draft_send_policy(draft)
    except ValueError as exc:
        repo.mark_send_failed(draft_id, reason=f"channel_policy_blocked: {exc}")
        return ApprovalResult(draft_id, SEND_FAILED, sent=False, error=str(exc))

    repo.mark_approved_pending_send(draft_id, approved_by=approved_by)

    try:
        response = get_openclaw_client().send_message(
            OpenClawSendRequest(
                channel=draft.channel or "",
                conversation_id=draft.conversation_id or "",
                target_peer_id=draft.target_peer_id or "",
                message_text=draft.message_text or "",
                message_type=draft.message_type or "text",
                attachments=draft.attachments_json or [],
            )
        )
    except Exception as exc:  # transport error -> recoverable send_failed
        repo.mark_send_failed(draft_id, reason=f"transport_error: {exc}")
        return ApprovalResult(draft_id, SEND_FAILED, sent=False, error=str(exc))

    if response.success:
        repo.mark_sent(draft_id)
        return ApprovalResult(draft_id, SENT, sent=True, message_id=response.message_id or "")

    repo.mark_send_failed(draft_id, reason=f"send_failed: {response.error}")
    return ApprovalResult(draft_id, SEND_FAILED, sent=False, error=response.error)


def reject(draft_id: str, db: Session) -> ApprovalResult:
    repo = DraftRepository(db)
    draft = repo.get(draft_id)
    if draft is None:
        raise DraftStateError(f"Draft {draft_id} not found")
    if draft.status != PENDING_APPROVAL:
        raise DraftStateError(f"Draft {draft_id} is {draft.status}; only pending drafts can be rejected")
    repo.reject(draft_id)
    return ApprovalResult(draft_id, REJECTED, sent=False)
