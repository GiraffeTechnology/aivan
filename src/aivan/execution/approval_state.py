"""Draft approval state machine with recoverable send failures.

States (PRD §11):
    pending_approval -> approved_pending_send -> sent
                                              \\-> send_failed (recoverable)
    pending_approval -> rejected
    (any) -> superseded

The delivery claim is committed before external I/O. Only definite rejection
permits retry; timeout, lost acknowledgement or process interruption remains
``delivery_unconfirmed`` and requires external reconciliation.
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
    ``sent``. Definite rejection becomes ``send_failed``; an unknown delivery
    outcome remains non-retryable ``delivery_unconfirmed``.
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

    from aivan.execution.draft_preview import (
        PreviewError, approved_render, bind_approval, invalidate_approval, verify_preview,
    )
    try:
        if draft.status == SEND_FAILED:
            rendered = approved_render(db, draft)
        else:
            preview, rendered = verify_preview(db, draft, None)
            draft.approved_by = approved_by
            bind_approval(db, draft, preview)
        if rendered.manual_delivery:
            return ApprovalResult(draft_id, draft.status, sent=False, error="DRAFT_REQUIRES_MANUAL_DELIVERY")
    except PreviewError as exc:
        invalidate_approval(db, draft, exc.code)
        return ApprovalResult(draft_id, PENDING_APPROVAL, sent=False, error=exc.code)

    # Validate channel policy BEFORE transitioning past pending.
    try:
        from aivan.execution.channel_policy import validate_draft_send_policy

        validate_draft_send_policy(draft)
    except ValueError as exc:
        repo.mark_send_failed(draft_id, reason=f"channel_policy_blocked: {exc}")
        return ApprovalResult(draft_id, SEND_FAILED, sent=False, error="outbound transport failed")

    from aivan.execution.delivery_state import claim_delivery
    if not claim_delivery(db, draft, draft.status):
        raise DraftStateError("Draft delivery has already been claimed")

    try:
        response = get_openclaw_client().send_message(
            OpenClawSendRequest(
                channel=draft.channel or "",
                channel_account_id=draft.channel_account_id or "",
                conversation_id=draft.conversation_id or "",
                target_peer_id=draft.target_peer_id or "",
                message_text=rendered.message_text,
                message_type=draft.message_type or "text",
                attachments=draft.attachments_json or [],
            )
        )
    except Exception:
        return ApprovalResult(draft_id, "delivery_unconfirmed", sent=False, error="Outbound delivery is unconfirmed")

    if response.success:
        repo.mark_sent(draft_id)
        return ApprovalResult(draft_id, SENT, sent=True, message_id=response.message_id or "")

    if response.outcome_uncertain:
        return ApprovalResult(draft_id, "delivery_unconfirmed", sent=False, error="Outbound delivery is unconfirmed")
    repo.mark_send_failed(draft_id, reason="transport_failed")
    return ApprovalResult(draft_id, SEND_FAILED, sent=False, error="outbound transport failed")


def reject(draft_id: str, db: Session) -> ApprovalResult:
    repo = DraftRepository(db)
    draft = repo.get(draft_id)
    if draft is None:
        raise DraftStateError(f"Draft {draft_id} not found")
    if draft.status != PENDING_APPROVAL:
        raise DraftStateError(f"Draft {draft_id} is {draft.status}; only pending drafts can be rejected")
    repo.reject(draft_id)
    return ApprovalResult(draft_id, REJECTED, sent=False)
