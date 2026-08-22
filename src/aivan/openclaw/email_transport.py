from __future__ import annotations

import os
import poplib
import smtplib
from dataclasses import dataclass
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import getaddresses

from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.openclaw.contracts import OpenClawSendResponse
from aivan.utils.time_utils import utcnow_iso
from aivan.utils.env import env_bool


SECRET_KEYS = {
    "AIVAN_SMTP_PASSWORD",
    "AIVAN_IMAP_PASSWORD",
    "AIVAN_POP3_PASSWORD",
    "SMTP_PASSWORD",
    "IMAP_PASSWORD",
    "POP3_PASSWORD",
}


@dataclass(frozen=True)
class RealTestEmailMessage:
    message_index: int
    from_address: str
    to_address: str
    subject: str
    date: str
    body_excerpt: str


def is_real_test_email_mode() -> bool:
    return os.environ.get("AIVAN_EMAIL_SEND_MODE", "").strip().lower() == "real_test"


def real_test_email_gateway() -> str:
    return os.environ.get("AIVAN_EMAIL_GATEWAY", "").strip().lower()


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


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _message_body_excerpt(raw_message: bytes, *, max_chars: int = 2000) -> tuple[str, str, str, str, str]:
    msg = message_from_bytes(raw_message)
    subject = _decode_header(msg.get("Subject"))
    from_address = _decode_header(msg.get("From"))
    to_address = _decode_header(msg.get("To"))
    date = msg.get("Date") or ""
    parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            disposition = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disposition:
                continue
            if part.get_content_type() not in {"text/plain", "text/html"}:
                continue
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            parts.append(payload.decode(charset, errors="replace"))
    else:
        payload = msg.get_payload(decode=True) or b""
        charset = msg.get_content_charset() or "utf-8"
        parts.append(payload.decode(charset, errors="replace"))
    return from_address, to_address, subject, date, "\n".join(parts).strip()[:max_chars]


def fetch_real_test_pop3_messages(*, limit: int = 20) -> list[RealTestEmailMessage]:
    """Fetch recent messages for controlled real-test email receive checks.

    This is intentionally a test helper for the OpenClaw real-test gateway path.
    It does not ingest messages into AIVAN workflow state.
    """
    if real_test_email_gateway() != "openclaw_real_test":
        raise ValueError("AIVAN_EMAIL_GATEWAY must be openclaw_real_test for real_test email receive")
    username = os.environ.get("AIVAN_POP3_USERNAME") or os.environ.get("AIVAN_SMTP_USERNAME", "")
    password = os.environ.get("AIVAN_POP3_PASSWORD") or os.environ.get("AIVAN_SMTP_PASSWORD", "")
    host = os.environ.get("AIVAN_POP3_HOST", "pop.163.com")
    port = int(os.environ.get("AIVAN_POP3_PORT", "995"))
    use_ssl = env_bool("AIVAN_POP3_USE_SSL", True)
    if not username:
        raise ValueError("AIVAN_POP3_USERNAME is not configured")
    if not password:
        raise ValueError("AIVAN_POP3_PASSWORD is not configured")

    pop_cls = poplib.POP3_SSL if use_ssl else poplib.POP3
    try:
        client = pop_cls(host, port, timeout=30)
        try:
            client.user(username)
            client.pass_(password)
            count, _size = client.stat()
            start = max(1, count - max(limit, 0) + 1)
            messages: list[RealTestEmailMessage] = []
            for index in range(start, count + 1):
                _resp, lines, _octets = client.retr(index)
                from_address, to_address, subject, date, body = _message_body_excerpt(b"\r\n".join(lines))
                messages.append(
                    RealTestEmailMessage(
                        message_index=index,
                        from_address=from_address,
                        to_address=to_address,
                        subject=subject,
                        date=date,
                        body_excerpt=body,
                    )
                )
            return messages
        finally:
            try:
                client.quit()
            except Exception:
                pass
    except Exception as exc:
        raise RuntimeError(redact_secret(str(exc))) from exc


def send_real_test_email(draft: InquiryDraftRecord) -> OpenClawSendResponse:
    recipient = (draft.target_peer_id or "").strip()
    sender = os.environ.get("AIVAN_PRESET_MAILBOX") or os.environ.get("AIVAN_SMTP_USERNAME", "")
    username = os.environ.get("AIVAN_SMTP_USERNAME", "")
    password = os.environ.get("AIVAN_SMTP_PASSWORD", "")
    host = os.environ.get("AIVAN_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("AIVAN_SMTP_PORT", "587"))
    use_ssl = env_bool("AIVAN_SMTP_USE_SSL", port == 465)
    use_tls = env_bool("AIVAN_SMTP_USE_TLS", True)

    try:
        if real_test_email_gateway() != "openclaw_real_test":
            raise ValueError("AIVAN_EMAIL_GATEWAY must be openclaw_real_test for real_test email sending")
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
