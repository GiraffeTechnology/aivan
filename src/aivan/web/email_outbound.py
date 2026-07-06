"""Email outbound adapter for the myaivan Web UI (PRD §17).

The ✉️ action sends email through a configured SMTP mailbox in production,
or through aivan-openclaw's controlled real-test transport for approved
test runs. When neither is configured, a feature-flagged mock
provider (AIVAN_WEB_EMAIL_MOCK=true, or OPENCLAW_MOCK_MODE=true) simulates a
send for local/demo mode and is always labeled ``provider="mock"`` — the UI
and audit log must never present a mock result as a real delivery. With
neither configured, sending fails with a clear "not configured" status.
"""

from __future__ import annotations

from dataclasses import dataclass

from aivan.openclaw.email_transport import (
    is_real_test_email_mode,
    is_smtp_email_mode,
    send_real_test_email,
    send_smtp_email,
)
from aivan.utils.env import env_bool
from aivan.utils.ids import new_id
from aivan.utils.time_utils import utcnow_iso


@dataclass
class EmailSendResult:
    success: bool
    provider: str  # "smtp" | "aivan-openclaw" | "mock" | "none"
    message_id: str = ""
    error: str = ""


def email_status() -> str:
    """One of: configured | mock | not_configured."""
    if is_smtp_email_mode() or is_real_test_email_mode():
        return "configured"
    if env_bool("AIVAN_WEB_EMAIL_MOCK") or env_bool("OPENCLAW_MOCK_MODE"):
        return "mock"
    return "not_configured"


def send_email(*, to: str, subject: str, body: str, case_id: str, draft_id: str) -> EmailSendResult:
    status = email_status()

    if status == "configured":
        from aivan.db.models.inquiry import InquiryDraftRecord

        transient = InquiryDraftRecord(
            draft_id=draft_id,
            project_id=case_id,
            channel="email",
            target_peer_id=to,
            target_role="counterparty",
            message_text=body,
            notes=f"subject={subject}",
            status="approved",
        )
        if is_smtp_email_mode():
            response = send_smtp_email(transient)
            provider = "smtp"
        else:
            # Controlled test path: re-validates the recipient against
            # AIVAN_EMAIL_ALLOWED_RECIPIENTS.
            response = send_real_test_email(transient)
            provider = "aivan-openclaw"
        return EmailSendResult(
            success=response.success,
            provider=provider,
            message_id=response.message_id or "",
            error=response.error or "",
        )

    if status == "mock":
        return EmailSendResult(
            success=True,
            provider="mock",
            message_id=f"mock_email_{new_id()}_{utcnow_iso()}",
        )

    return EmailSendResult(
        success=False,
        provider="none",
        error="Email sending is not configured. Please copy the draft manually.",
    )
