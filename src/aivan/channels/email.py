from __future__ import annotations
import os
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


@dataclass
class EmailSendResult:
    success: bool
    message_id: str = ""
    sent_at: str = ""
    error: str = ""


def send_email(to_address: str, subject: str, body: str) -> EmailSendResult:
    """Send email via SMTP.  AIVAN_EMAIL_MODE=mock (default) skips real send."""
    from aivan.utils.time_utils import utcnow_iso

    if os.environ.get("AIVAN_EMAIL_MODE", "mock").lower() == "mock":
        return EmailSendResult(
            success=True,
            message_id=f"mock_email_{utcnow_iso()}",
            sent_at=utcnow_iso(),
        )

    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    from_addr = os.environ.get("SMTP_FROM", user)

    if not host:
        return EmailSendResult(success=False, error="SMTP_HOST not configured")

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = from_addr
        msg["To"] = to_address
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(host, port) as smtp:
            smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.sendmail(from_addr, to_address, msg.as_string())

        sent_at = utcnow_iso()
        return EmailSendResult(success=True, message_id=f"smtp_{sent_at}", sent_at=sent_at)
    except Exception as exc:
        return EmailSendResult(success=False, error=str(exc))
