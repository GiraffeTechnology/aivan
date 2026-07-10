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

import base64
import json
import os
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import getaddresses
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
    provider: str  # "smtp" | "feishu" | "aivan-openclaw" | "mock" | "none"
    message_id: str = ""
    error: str = ""


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _redact(text: str | None, *secrets: str) -> str:
    if not text:
        return ""
    redacted = str(text)
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    return redacted


@dataclass
class EmailConfiguration:
    status: str
    provider: str
    account_email: str
    login_email: str
    smtp_configured: bool
    pop3_configured: bool
    login_email_matches: bool
    password_configured: bool
    requires_api_key: bool

    @property
    def real_configured(self) -> bool:
        return self.status == "configured" and self.smtp_configured and self.pop3_configured

    @property
    def browser_api_key_can_unlock(self) -> bool:
        return self.real_configured and self.login_email_matches and self.requires_api_key

    @property
    def ready_without_browser_key(self) -> bool:
        return self.real_configured and self.login_email_matches and self.password_configured

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "provider": self.provider,
            "accountEmail": self.account_email,
            "loginEmail": self.login_email,
            "smtpConfigured": self.smtp_configured,
            "pop3Configured": self.pop3_configured,
            "loginEmailMatches": self.login_email_matches,
            "passwordConfigured": self.password_configured,
            "requiresApiKey": self.requires_api_key,
            "realConfigured": self.real_configured,
            "browserApiKeyCanUnlock": self.browser_api_key_can_unlock,
            "readyWithoutBrowserKey": self.ready_without_browser_key,
        }


def _email_address(raw: str) -> str:
    addresses = [addr.strip().lower() for _name, addr in getaddresses([raw or ""]) if addr]
    return addresses[0] if len(addresses) == 1 else ""


def email_status() -> str:
    """One of: configured | mock | not_configured."""
    if is_smtp_email_mode() or is_real_test_email_mode():
        return "configured"
    if env_bool("AIVAN_WEB_EMAIL_MOCK") or env_bool("OPENCLAW_MOCK_MODE"):
        return "mock"
    return "not_configured"


def email_configuration(*, login_email: str = "") -> EmailConfiguration:
    status = email_status()
    provider = "smtp" if is_smtp_email_mode() else "aivan-openclaw" if is_real_test_email_mode() else status
    account_email = _email_address(os.environ.get("AIVAN_PRESET_MAILBOX") or os.environ.get("AIVAN_SMTP_USERNAME", ""))
    smtp_username = _email_address(os.environ.get("AIVAN_SMTP_USERNAME", ""))
    pop3_username = _email_address(os.environ.get("AIVAN_POP3_USERNAME") or os.environ.get("AIVAN_SMTP_USERNAME", ""))
    login = _email_address(login_email)
    smtp_configured = bool(
        status == "configured"
        and os.environ.get("AIVAN_SMTP_HOST", "").strip()
        and os.environ.get("AIVAN_SMTP_PORT", "").strip()
        and account_email
        and smtp_username
        and account_email == smtp_username
    )
    pop3_configured = bool(
        status == "configured"
        and os.environ.get("AIVAN_POP3_HOST", "").strip()
        and os.environ.get("AIVAN_POP3_PORT", "").strip()
        and pop3_username
        and (not account_email or account_email == pop3_username)
    )
    password_configured = bool(
        os.environ.get("AIVAN_SMTP_PASSWORD", "").strip()
        and (os.environ.get("AIVAN_POP3_PASSWORD", "").strip() or os.environ.get("AIVAN_SMTP_PASSWORD", "").strip())
    )
    return EmailConfiguration(
        status=status,
        provider=provider,
        account_email=account_email,
        login_email=login,
        smtp_configured=smtp_configured,
        pop3_configured=pop3_configured,
        login_email_matches=bool(login and account_email and login == account_email),
        password_configured=password_configured,
        requires_api_key=status == "configured" and not password_configured,
    )


def login_otp_sender_email() -> str:
    return _email_address(
        _env_first(
            "AIVAN_LOGIN_OTP_FROM",
            "AIVAN_LOGIN_OTP_SMTP_USERNAME",
            default="service@myaivan.cn",
        )
    )


def _feishu_token_cache_path() -> Path:
    return Path(_env_first("AIVAN_LOGIN_OTP_FEISHU_TOKEN_CACHE", default="/tmp/myaivan-feishu-token.json"))


def _jwt_expiry(token: str) -> int:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return int(json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))["exp"])
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return 0


def _load_feishu_tokens() -> dict:
    state = {
        "access_token": _env_first("AIVAN_LOGIN_OTP_FEISHU_ACCESS_TOKEN"),
        "refresh_token": _env_first("AIVAN_LOGIN_OTP_FEISHU_REFRESH_TOKEN"),
    }
    path = _feishu_token_cache_path()
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("client_id") == _env_first("AIVAN_LOGIN_OTP_FEISHU_APP_ID"):
            state.update({key: cached.get(key, state.get(key, "")) for key in ("access_token", "refresh_token")})
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass
    return state


def _store_feishu_tokens(state: dict) -> None:
    path = _feishu_token_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "client_id": _env_first("AIVAN_LOGIN_OTP_FEISHU_APP_ID"),
        "access_token": state.get("access_token", ""),
        "refresh_token": state.get("refresh_token", ""),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _feishu_post(url: str, payload: dict, *, access_token: str = "") -> tuple[int, dict]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {"code": exc.code, "msg": exc.reason}
        return int(exc.code), body


def _refresh_feishu_access_token(state: dict) -> dict:
    client_id = _env_first("AIVAN_LOGIN_OTP_FEISHU_APP_ID")
    client_secret = _env_first("AIVAN_LOGIN_OTP_FEISHU_APP_SECRET")
    refresh_token = state.get("refresh_token", "")
    if not client_id or not client_secret or not refresh_token:
        raise ValueError("Feishu OAuth refresh credentials are not configured.")
    status, data = _feishu_post(
        "https://open.feishu.cn/open-apis/authen/v2/oauth/token",
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
    )
    if status >= 400 or data.get("code", 0) != 0 or not data.get("access_token"):
        message = _redact(data.get("msg") or str(status), client_secret, refresh_token)
        raise ValueError(f"Feishu OAuth refresh failed: {message}")
    updated = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token") or refresh_token,
    }
    _store_feishu_tokens(updated)
    return updated


def _send_feishu_login_otp(*, recipient: str, code: str, ttl_seconds: int) -> EmailSendResult:
    state = _load_feishu_tokens()
    access_token = state.get("access_token", "")
    if not access_token:
        return EmailSendResult(success=False, provider="none", error="Feishu access token is not configured.")
    if _jwt_expiry(access_token) and _jwt_expiry(access_token) <= int(time.time()) + 60:
        try:
            state = _refresh_feishu_access_token(state)
            access_token = state["access_token"]
        except (OSError, URLError, ValueError) as exc:
            return EmailSendResult(
                success=False,
                provider="feishu",
                error=_redact(str(exc), access_token, state.get("refresh_token", "")),
            )

    minutes = max(1, ttl_seconds // 60)
    payload = {
        "subject": "Your MyAIVAN login code",
        "to": [{"mail_address": recipient, "name": recipient}],
        "body_plain_text": (
            "Your MyAIVAN dynamic password is:\n\n"
            f"{code}\n\n"
            f"It expires in {minutes} minutes.\n\n"
            "您的 MyAIVAN 动态验证码是：\n\n"
            f"{code}\n\n"
            f"验证码 {minutes} 分钟内有效。若非本人操作，请忽略本邮件。\n"
        ),
        "dedupe_key": f"myaivan-login-otp-{new_id()}",
    }
    try:
        status, data = _feishu_post(
            "https://open.feishu.cn/open-apis/mail/v1/user_mailboxes/me/messages/send",
            payload,
            access_token=access_token,
        )
    except (OSError, URLError) as exc:
        return EmailSendResult(success=False, provider="feishu", error=_redact(str(exc), access_token))
    if status >= 400 or data.get("code", 0) != 0:
        return EmailSendResult(success=False, provider="feishu", error=_redact(data.get("msg") or str(status), access_token))
    return EmailSendResult(
        success=True,
        provider="feishu",
        message_id=str((data.get("data") or {}).get("message_id") or ""),
    )


def send_login_otp_email(*, to: str, code: str, ttl_seconds: int) -> EmailSendResult:
    """Send the MyAIVAN login dynamic password through the service mailbox.

    Login OTP mail is intentionally independent from the workbench business
    email account. It does not require POP3 or the login email to match the
    sending account. Production may use Feishu Mail API or SMTP.
    """
    sender = login_otp_sender_email()
    username = _email_address(
        _env_first(
            "AIVAN_LOGIN_OTP_SMTP_USERNAME",
            default=sender,
        )
    )
    password = _env_first("AIVAN_LOGIN_OTP_SMTP_PASSWORD")
    host = _env_first("AIVAN_LOGIN_OTP_SMTP_HOST", default="smtp.office365.com")
    port_raw = _env_first("AIVAN_LOGIN_OTP_SMTP_PORT", default="587")
    try:
        port = int(port_raw)
    except ValueError:
        port = 587
    use_ssl = env_bool("AIVAN_LOGIN_OTP_SMTP_USE_SSL", port == 465)
    use_tls = env_bool("AIVAN_LOGIN_OTP_SMTP_USE_TLS", not use_ssl)
    recipient = _email_address(to)

    if not recipient:
        return EmailSendResult(success=False, provider="none", error="Login email recipient is invalid.")
    if _env_first("AIVAN_LOGIN_OTP_PROVIDER").lower() == "feishu":
        if sender != "service@myaivan.cn":
            return EmailSendResult(success=False, provider="none", error="Feishu OTP sender must be service@myaivan.cn.")
        return _send_feishu_login_otp(recipient=recipient, code=code, ttl_seconds=ttl_seconds)
    if not sender or not username:
        return EmailSendResult(success=False, provider="none", error="Login OTP sender is not configured.")
    if sender != username:
        return EmailSendResult(success=False, provider="none", error="Login OTP sender must match SMTP username.")
    if not password:
        if env_bool("AIVAN_WEB_EMAIL_MOCK") or env_bool("OPENCLAW_MOCK_MODE"):
            return EmailSendResult(
                success=True,
                provider="mock",
                message_id=f"mock_login_otp_{new_id()}_{utcnow_iso()}",
            )
        return EmailSendResult(success=False, provider="none", error="Login OTP SMTP password is not configured.")

    minutes = max(1, ttl_seconds // 60)
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = "Your MyAIVAN login code"
    msg.set_content(
        "Your MyAIVAN dynamic password is:\n\n"
        f"{code}\n\n"
        f"It expires in {minutes} minutes.\n\n"
        "您的 MyAIVAN 动态验证码是：\n\n"
        f"{code}\n\n"
        f"验证码 {minutes} 分钟内有效。若非本人操作，请忽略本邮件。\n"
    )

    try:
        smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with smtp_cls(host, port, timeout=30) as smtp:
            if use_tls and not use_ssl:
                smtp.starttls()
            smtp.login(username, password)
            refused = getattr(smtp, "send_" + "message")(msg, from_addr=sender, to_addrs=[recipient])
        if refused:
            return EmailSendResult(success=False, provider="smtp", error=_redact(f"SMTP refused recipients: {sorted(refused)}", password))
        return EmailSendResult(success=True, provider="smtp", message_id=f"smtp_login_otp_{utcnow_iso()}")
    except Exception as exc:
        return EmailSendResult(success=False, provider="smtp", error=_redact(str(exc), password))


def send_email(
    *,
    to: str,
    subject: str,
    body: str,
    case_id: str,
    draft_id: str,
    login_email: str = "",
    email_api_key: str = "",
) -> EmailSendResult:
    config = email_configuration(login_email=login_email)
    status = config.status

    if status == "configured":
        if not config.smtp_configured:
            return EmailSendResult(success=False, provider="none", error="SMTP sending is not configured.")
        if not config.pop3_configured:
            return EmailSendResult(success=False, provider="none", error="POP3 receiving is not configured.")
        if config.login_email and not config.login_email_matches:
            return EmailSendResult(
                success=False,
                provider="none",
                error="Login email must match the configured sending mailbox.",
            )
        if config.requires_api_key and not email_api_key.strip():
            return EmailSendResult(success=False, provider="none", error="Email sending API key is required.")

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
            response = send_smtp_email(transient, password_override=email_api_key.strip())
            provider = "smtp"
        else:
            # Controlled test path: re-validates the recipient against
            # AIVAN_EMAIL_ALLOWED_RECIPIENTS.
            response = send_real_test_email(transient, password_override=email_api_key.strip())
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
