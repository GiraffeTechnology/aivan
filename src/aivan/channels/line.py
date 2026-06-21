from __future__ import annotations
import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass

import httpx

_PUSH_URL = "https://api.line.me/v2/bot/message/push"
_MAX_RETRIES = 3


@dataclass
class LineSendResult:
    success: bool
    message_id: str = ""
    sent_at: str = ""
    error: str = ""
    error_code: str = ""


def send_line_push(user_id: str, message_text: str) -> LineSendResult:
    """Push a text message to a LINE userId via the official Push API.

    - AIVAN_LINE_ENABLED must be 'true'.
    - AIVAN_LINE_MODE=mock (default) returns a stub without hitting api.line.me.
    - 429 responses trigger exponential back-off retry (2 s, 4 s, 8 s).
    - Non-200 / non-429 errors are returned as structured failures; never swallowed.
    """
    from aivan.utils.time_utils import utcnow_iso

    if os.environ.get("AIVAN_LINE_ENABLED", "false").lower() != "true":
        return LineSendResult(success=False, error="LINE not enabled (AIVAN_LINE_ENABLED != true)")

    if os.environ.get("AIVAN_LINE_MODE", "mock").lower() == "mock":
        return LineSendResult(
            success=True,
            message_id=f"mock_line_{user_id}_{utcnow_iso()}",
            sent_at=utcnow_iso(),
        )

    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    if not token:
        return LineSendResult(success=False, error="LINE_CHANNEL_ACCESS_TOKEN not configured")

    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": message_text}],
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    wait = 2
    last_error = "unknown"
    for _ in range(_MAX_RETRIES):
        try:
            resp = httpx.post(_PUSH_URL, json=payload, headers=headers, timeout=30)
            if resp.status_code == 429:
                time.sleep(wait)
                wait *= 2
                last_error = "rate_limited"
                continue
            if resp.status_code == 200:
                return LineSendResult(
                    success=True,
                    message_id=resp.headers.get("X-Line-Request-Id", ""),
                    sent_at=utcnow_iso(),
                )
            body: dict = resp.json() if resp.content else {}
            err_msg = body.get("message", f"HTTP {resp.status_code}")
            return LineSendResult(success=False, error=err_msg, error_code=str(resp.status_code))
        except Exception as exc:
            last_error = str(exc)

    return LineSendResult(success=False, error=last_error, error_code="retry_exhausted")


def verify_line_signature(body: bytes, x_line_signature: str) -> bool:
    """Verify the HMAC-SHA256 signature sent by the LINE webhook."""
    secret = os.environ.get("LINE_CHANNEL_SECRET", "")
    if not secret:
        return False
    digest = hmac.HMAC(secret.encode(), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, x_line_signature)
