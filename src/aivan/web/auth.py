"""Authentication / production fail-closed guard for the myaivan Web UI.

Semantics (mirrors the core API's ``_require_api_key`` fail-closed rules):

* local/dev with no secret configured  → open demo access.
* production (AIVAN_ENV=production) with neither AIVAN_API_KEY nor
  AIVAN_AUTH_SECRET configured → every protected page/endpoint fails closed
  (503). myaivan must never serve case/business data unauthenticated in
  production.
* a secret configured (any env) → access requires either
    - a valid login session cookie (issued by POST /api/myaivan/login after
      presenting the key), or
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
import secrets as _secrets
import time

from fastapi import HTTPException, Request

SESSION_COOKIE = "myaivan_session"
DEFAULT_SESSION_TTL_SECONDS = 12 * 3600


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


def issue_session_token(now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + session_ttl_seconds())
    return f"{expires}.{_sign(f'myaivan-session:{expires}')}"


def verify_session_token(token: str, now: float | None = None) -> bool:
    if not token or not _signing_secret():
        return False
    expires_raw, _, signature = token.partition(".")
    try:
        expires = int(expires_raw)
    except ValueError:
        return False
    if (now if now is not None else time.time()) >= expires:
        return False
    expected = _sign(f"myaivan-session:{expires}")
    return hmac.compare_digest(signature, expected)


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
