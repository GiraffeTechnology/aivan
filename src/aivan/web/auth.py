"""Authentication / production fail-closed guard for the myaivan Web UI.

Semantics (mirrors the core API's ``_require_api_key`` fail-closed rules):

* local/dev with no secret configured  → open demo access.
* production (AIVAN_ENV=production) with neither AIVAN_API_KEY nor
  AIVAN_AUTH_SECRET configured → every protected page/endpoint fails closed
  (503). myaivan must never serve case/business data unauthenticated in
  production.
* a secret configured (any env) → access requires either
    - a valid login session cookie (issued by email dynamic password login), or
    - a matching X-AIVAN-API-Key header / Authorization: Bearer token
      (for API clients and automation).

Session cookies are stateless HMAC tokens signed with the configured secret:
``<expires_ts>.<hmac_sha256(secret, "myaivan-session:<expires_ts>")>``.
Rotating the secret invalidates all sessions immediately.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets as _secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

from fastapi import HTTPException, Request

SESSION_COOKIE = "myaivan_session"
DEFAULT_SESSION_TTL_SECONDS = 12 * 3600
DEFAULT_OTP_TTL_SECONDS = 5 * 60
DEFAULT_OTP_MAX_ATTEMPTS = 5
DEFAULT_HUMAN_CHALLENGE_TTL_SECONDS = 5 * 60
DEFAULT_HUMAN_CHALLENGE_DIFFICULTY = 3
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_OTP_STORE: dict[str, dict] = {}
_HUMAN_CHALLENGES: dict[str, dict] = {}


def _env() -> str:
    return os.environ.get("AIVAN_ENV", "local").strip().lower()


def _configured_keys() -> list[str]:
    keys = [
        os.environ.get("AIVAN_API_KEY", "").strip(),
        os.environ.get("AIVAN_AUTH_SECRET", "").strip(),
    ]
    return [k for k in keys if k]


def auth_mode() -> str:
    """open (local demo) | required (secret configured) | misconfigured
    (production without any secret — fail closed)."""
    configured = _configured_keys()
    if configured:
        return "required"
    if _env() == "production":
        return "misconfigured"
    return "open"


def verify_presented_key(provided: str) -> bool:
    provided = (provided or "").strip()
    if not provided:
        return False
    return any(_secrets.compare_digest(provided, key) for key in _configured_keys())


def _signing_secret() -> str:
    # Prefer the HMAC auth secret; fall back to the API key.
    return (
        os.environ.get("AIVAN_AUTH_SECRET", "").strip()
        or os.environ.get("AIVAN_API_KEY", "").strip()
    )


def _sign(payload: str) -> str:
    return hmac.new(_signing_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()


def session_ttl_seconds() -> int:
    try:
        return int(os.environ.get("AIVAN_WEB_SESSION_TTL_SECONDS", str(DEFAULT_SESSION_TTL_SECONDS)))
    except ValueError:
        return DEFAULT_SESSION_TTL_SECONDS


def otp_ttl_seconds() -> int:
    try:
        return int(os.environ.get("AIVAN_WEB_OTP_TTL_SECONDS", str(DEFAULT_OTP_TTL_SECONDS)))
    except ValueError:
        return DEFAULT_OTP_TTL_SECONDS


def otp_max_attempts() -> int:
    try:
        return int(os.environ.get("AIVAN_WEB_OTP_MAX_ATTEMPTS", str(DEFAULT_OTP_MAX_ATTEMPTS)))
    except ValueError:
        return DEFAULT_OTP_MAX_ATTEMPTS


def human_challenge_ttl_seconds() -> int:
    try:
        return int(os.environ.get("AIVAN_WEB_HUMAN_CHALLENGE_TTL_SECONDS", str(DEFAULT_HUMAN_CHALLENGE_TTL_SECONDS)))
    except ValueError:
        return DEFAULT_HUMAN_CHALLENGE_TTL_SECONDS


def human_challenge_difficulty() -> int:
    try:
        return max(1, int(os.environ.get("AIVAN_WEB_HUMAN_CHALLENGE_DIFFICULTY", str(DEFAULT_HUMAN_CHALLENGE_DIFFICULTY))))
    except ValueError:
        return DEFAULT_HUMAN_CHALLENGE_DIFFICULTY


def _encode_user_id(user_id: str) -> str:
    return urlsafe_b64encode((user_id or "").encode()).decode().rstrip("=")


def _decode_user_id(encoded: str) -> str:
    if not encoded:
        return ""
    padded = encoded + ("=" * (-len(encoded) % 4))
    try:
        return urlsafe_b64decode(padded.encode()).decode()
    except Exception:
        return ""


def issue_session_token(now: float | None = None, user_id: str = "") -> str:
    expires = int((now if now is not None else time.time()) + session_ttl_seconds())
    encoded_user = _encode_user_id(user_id)
    payload = f"myaivan-session:{expires}:{encoded_user}"
    return f"{expires}.{encoded_user}.{_sign(payload)}"


def _cleanup_human_challenges(now: float) -> None:
    expired = [cid for cid, record in _HUMAN_CHALLENGES.items() if now >= int(record["expires"])]
    for cid in expired:
        _HUMAN_CHALLENGES.pop(cid, None)


def issue_human_challenge(*, now: float | None = None) -> dict:
    """Create a self-hosted proof-of-work challenge for the login form.

    This avoids third-party CAPTCHA services: the browser proves it spent a
    small amount of local CPU by finding a nonce whose SHA-256 digest has a
    configured leading-zero prefix.
    """
    current = now if now is not None else time.time()
    _cleanup_human_challenges(current)
    challenge_id = _secrets.token_urlsafe(18)
    salt = _secrets.token_urlsafe(18)
    difficulty = human_challenge_difficulty()
    expires = int(current + human_challenge_ttl_seconds())
    _HUMAN_CHALLENGES[challenge_id] = {
        "salt": salt,
        "difficulty": difficulty,
        "expires": expires,
    }
    return {
        "challengeId": challenge_id,
        "salt": salt,
        "difficulty": difficulty,
        "algorithm": "sha256-leading-zero-hex",
        "expiresInSeconds": human_challenge_ttl_seconds(),
    }


def _human_digest(challenge_id: str, salt: str, nonce: str) -> str:
    payload = f"{challenge_id}:{salt}:{nonce}".encode()
    return hashlib.sha256(payload).hexdigest()


def verify_human_proof(proof: dict | None, *, now: float | None = None) -> bool:
    if not isinstance(proof, dict):
        return False
    challenge_id = str(proof.get("challengeId") or "")
    nonce = str(proof.get("nonce") or "")
    digest = str(proof.get("digest") or "").lower()
    if not challenge_id or not nonce or not digest:
        return False
    record = _HUMAN_CHALLENGES.get(challenge_id)
    if not record:
        return False
    if (now if now is not None else time.time()) >= int(record["expires"]):
        _HUMAN_CHALLENGES.pop(challenge_id, None)
        return False
    expected = _human_digest(challenge_id, str(record["salt"]), nonce)
    prefix = "0" * int(record["difficulty"])
    ok = hmac.compare_digest(expected, digest) and digest.startswith(prefix)
    if ok:
        _HUMAN_CHALLENGES.pop(challenge_id, None)
    return ok


def normalize_email(email: str) -> str:
    normalized = (email or "").strip().lower()
    if not _EMAIL_RE.match(normalized):
        raise ValueError("A valid email address is required")
    return normalized


def _allowed_login_emails() -> set[str]:
    raw = os.environ.get("AIVAN_WEB_LOGIN_ALLOWED_EMAILS", "").strip()
    if not raw:
        return set()
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def is_login_email_allowed(email: str) -> bool:
    allowed = _allowed_login_emails()
    return not allowed or email in allowed


def _hash_otp(email: str, code: str, expires: int) -> str:
    return _sign(f"myaivan-login-otp:{email}:{expires}:{code}")


def _otp_debug_enabled() -> bool:
    return (
        os.environ.get("AIVAN_WEB_OTP_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
        or os.environ.get("AIVAN_TEST_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
    )


def _static_otp_code() -> str:
    code = os.environ.get("AIVAN_WEB_STATIC_OTP_CODE", "").strip()
    return code if code.isdigit() and len(code) == 6 else ""


def issue_login_code(email: str, *, now: float | None = None) -> dict:
    """Generate and send a one-time login code to an email address.

    The cleartext code is sent only by email. Test/debug environments may opt
    into returning it through ``debugCode`` for automation.
    """
    from aivan.web.email_outbound import send_email

    normalized = normalize_email(email)
    if not is_login_email_allowed(normalized):
        raise PermissionError("This email is not allowed to sign in to MyAIVAN")

    code = _static_otp_code() or f"{_secrets.randbelow(1_000_000):06d}"
    expires = int((now if now is not None else time.time()) + otp_ttl_seconds())
    _OTP_STORE[normalized] = {
        "hash": _hash_otp(normalized, code, expires),
        "expires": expires,
        "attempts": 0,
    }
    if _static_otp_code():
        return {
            "sent": True,
            "provider": "static_test",
            "messageId": "",
            "expiresInSeconds": otp_ttl_seconds(),
            "error": "",
        }
    result = send_email(
        to=normalized,
        subject="Your MyAIVAN login code",
        body=(
            "Your MyAIVAN dynamic password is:\n\n"
            f"{code}\n\n"
            f"It expires in {otp_ttl_seconds() // 60} minutes. "
            "If you did not request this code, ignore this email."
        ),
        case_id="myaivan-login",
        draft_id=f"login_{_secrets.token_hex(8)}",
    )
    if not result.success:
        _OTP_STORE.pop(normalized, None)
    payload = {
        "sent": result.success,
        "provider": result.provider,
        "messageId": result.message_id,
        "expiresInSeconds": otp_ttl_seconds(),
        "error": result.error,
    }
    if result.success and _otp_debug_enabled():
        payload["debugCode"] = code
    return payload


def verify_login_code(email: str, code: str, *, now: float | None = None) -> bool:
    normalized = normalize_email(email)
    record = _OTP_STORE.get(normalized)
    if not record:
        return False
    if (now if now is not None else time.time()) >= int(record["expires"]):
        _OTP_STORE.pop(normalized, None)
        return False
    record["attempts"] = int(record.get("attempts", 0)) + 1
    if record["attempts"] > otp_max_attempts():
        _OTP_STORE.pop(normalized, None)
        return False
    expected = record["hash"]
    provided = _hash_otp(normalized, (code or "").strip(), int(record["expires"]))
    if hmac.compare_digest(expected, provided):
        _OTP_STORE.pop(normalized, None)
        return True
    return False


def verify_session_token(token: str, now: float | None = None) -> bool:
    return bool(session_user_id(token, now=now) is not None)


def session_user_id(token: str, now: float | None = None) -> str | None:
    if not token or not _signing_secret():
        return None
    parts = token.split(".")
    if len(parts) == 2:
        expires_raw, signature = parts
        encoded_user = ""
        payload = f"myaivan-session:{expires_raw}"
    elif len(parts) == 3:
        expires_raw, encoded_user, signature = parts
        payload = f"myaivan-session:{expires_raw}:{encoded_user}"
    else:
        return None
    try:
        expires = int(expires_raw)
    except ValueError:
        return None
    if (now if now is not None else time.time()) >= expires:
        return None
    expected = _sign(payload)
    if not hmac.compare_digest(signature, expected):
        return None
    return _decode_user_id(encoded_user)


def request_user_id(request: Request) -> str:
    user_id = session_user_id(request.cookies.get(SESSION_COOKIE, ""))
    if user_id is not None:
        return user_id
    if verify_presented_key(_presented_key(request)):
        return "api_key"
    return ""


def _presented_key(request: Request) -> str:
    provided = request.headers.get("X-AIVAN-API-Key", "").strip()
    if not provided:
        auth_header = request.headers.get("Authorization", "").strip()
        if auth_header.lower().startswith("bearer "):
            provided = auth_header[7:].strip()
    return provided


def check_access(request: Request) -> str:
    """Return the access decision for a protected myaivan route.

    ok | login_required | invalid_key | fail_closed
    """
    mode = auth_mode()
    if mode == "open":
        return "ok"
    if mode == "misconfigured":
        return "fail_closed"
    if verify_session_token(request.cookies.get(SESSION_COOKIE, "")):
        return "ok"
    provided = _presented_key(request)
    if not provided:
        return "login_required"
    return "ok" if verify_presented_key(provided) else "invalid_key"


def require_web_api(request: Request) -> None:
    """FastAPI dependency for /api/myaivan JSON endpoints (fail closed)."""
    decision = check_access(request)
    if decision == "ok":
        return
    if decision == "fail_closed":
        raise HTTPException(
            status_code=503,
            detail=(
                "Server auth misconfigured: production requires AIVAN_API_KEY or "
                "AIVAN_AUTH_SECRET"
            ),
        )
    if decision == "login_required":
        raise HTTPException(
            status_code=401,
            detail="Authentication required: log in at /myaivan/login or send X-AIVAN-API-Key",
        )
    raise HTTPException(status_code=403, detail="Invalid API key")
