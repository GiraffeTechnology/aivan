from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from email.utils import getaddresses

from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.openclaw.contracts import OpenClawSendResponse
from aivan.utils.time_utils import utcnow_iso


SECRET_KEYS = {
    "AIVAN_SMTP_PASSWORD",
    "AIVAN_IMAP_PASSWORD",
    "SMTP_PASSWORD",
    "IMAP_PASSWORD",
}


def is_real_test_email_mode() -> bool:
    return os.environ.get("AIVAN_EMAIL_SEND_MODE", "").strip().lower() == "real_test"


def allowed_recipients() -> set[str]:
    raw = os.environ.get("AIVAN_EMAIL_ALLOWED_RECIPIENTS", "")
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def redact_secret(text: str | None) -> str:
    if not text:
        return ""
    redacted = str(text)
    for key in SECRET_KEYS:
        value = os.environ.get(key)
        if value:
            redacted = redacted.replace(value, "<redacted>")
    return redacted


def _smtp_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _single_email_address(raw: str) -> str:
    addresses = [(name, addr) for name, addr in getaddresses([raw or ""]) if addr]
    if len(addresses) != 1:
        raise ValueError("real_test email must have exactly one recipient")
    return addresses[0][1].strip().lower()


def validate_real_test_recipient(recipient: str) -> str:
    normalized = _single_email_address(recipient)
    allowed = allowed_recipients()
    if not normalized:
        raise ValueError("real_test email recipient is empty")
    if not allowed:
        raise ValueError("AIVAN_EMAIL_ALLOWED_RECIPIENTS is not configured")
    if normalized not in allowed:
        raise ValueError("real_test email recipient is not allowlisted")
    return normalized


def _subject_from_draft(draft: InquiryDraftRecord) -> str:
    for part in (draft.notes or "").splitlines():
        if part.lower().startswith("subject:"):
            return part.split(":", 1)[1].strip()
    for line in (draft.message_text or "").splitlines():
        if line.lower().startswith("subject:"):
            return line.split(":", 1)[1].strip()
    return "RFQ: Controlled AIVAN Test Email"


def _body_from_draft(draft: InquiryDraftRecord) -> str:
    lines = []
    for line in (draft.message_text or "").splitlines():
        if line.lower().startswith("subject:"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def send_real_test_email(draft: InquiryDraftRecord) -> OpenClawSendResponse:
    recipient = (draft.target_peer_id or "").strip()
    sender = os.environ.get("AIVAN_PRESET_MAILBOX") or os.environ.get("AIVAN_SMTP_USERNAME", "")
    username = os.environ.get("AIVAN_SMTP_USERNAME", "")
    password = os.environ.get("AIVAN_SMTP_PASSWORD", "")
    host = os.environ.get("AIVAN_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("AIVAN_SMTP_PORT", "587"))
    use_ssl = _smtp_bool("AIVAN_SMTP_USE_SSL", port == 465)
    use_tls = _smtp_bool("AIVAN_SMTP_USE_TLS", True)

    try:
        recipient_address = validate_real_test_recipient(recipient)
        sender_address = _single_email_address(sender)
        username_address = _single_email_address(username)
        if not sender_address:
            raise ValueError("real_test sender is not configured")
        if sender_address != username_address:
            raise ValueError("real_test sender must match SMTP username")
        if not password:
            raise ValueError("AIVAN_SMTP_PASSWORD is not configured")

        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = _subject_from_draft(draft)
        msg.set_content(_body_from_draft(draft))

        smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with smtp_cls(host, port, timeout=30) as smtp:
            if use_tls and not use_ssl:
                smtp.starttls()
            smtp.login(username, password)
            refused = smtp.send_message(msg, from_addr=sender_address, to_addrs=[recipient_address])
        if refused:
            return OpenClawSendResponse(
                success=False,
                error=redact_secret(f"SMTP refused recipients: {sorted(refused)}"),
            )
        return OpenClawSendResponse(
            success=True,
            message_id=f"smtp_real_test_{utcnow_iso()}",
            sent_at=utcnow_iso(),
        )
    except Exception as exc:
        return OpenClawSendResponse(success=False, error=redact_secret(str(exc)))
