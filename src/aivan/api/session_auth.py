from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request


SESSION_COOKIE = "aivan_session"
CSRF_COOKIE = "aivan_csrf"
SESSION_TTL_SECONDS = 8 * 60 * 60
TEST_SESSION_TTL_SECONDS = 30 * 60
TEST_TICKET_TTL_SECONDS = 5 * 60
_CONSUMED_TEST_TICKETS: dict[str, int] = {}
_TEST_TICKET_LOCK = threading.Lock()


@dataclass(frozen=True)
class UISession:
    tenant_id: str
    actor_id: str
    role: str
    allowed_roles: tuple[str, ...]
    csrf_digest: str
    expires_at: int
    test_account: bool = False
    authorization_reference: str = ""


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _session_secret() -> bytes:
    value = (
        os.environ.get("AIVAN_UI_SESSION_SECRET", "").strip()
        or os.environ.get("AIVAN_AUTH_SECRET", "").strip()
    )
    production = os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"
    if production and len(value) < 32:
        raise HTTPException(
            status_code=503,
            detail={"error": "UI_SESSION_SECRET_MISCONFIGURED"},
        )
    return (value or "local-development-session-secret-not-for-production").encode("utf-8")


def _configured_identity() -> tuple[str, tuple[str, ...], str]:
    production = os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"
    actor_id = os.environ.get("AIVAN_UI_ACTOR_ID", "").strip()
    roles = tuple(
        dict.fromkeys(
            item.strip().lower()
            for item in os.environ.get("AIVAN_UI_ALLOWED_ROLES", "").split(",")
            if item.strip()
        )
    )
    default_role = os.environ.get("AIVAN_UI_DEFAULT_ROLE", "").strip().lower()
    if not production:
        actor_id = actor_id or "local-workbench-operator"
        roles = roles or ("admin",)
    if not actor_id or not roles:
        raise HTTPException(
            status_code=503,
            detail={"error": "UI_IDENTITY_MISCONFIGURED"},
        )
    default_role = default_role or roles[0]
    if default_role not in roles:
        raise HTTPException(
            status_code=503,
            detail={"error": "UI_DEFAULT_ROLE_MISCONFIGURED"},
        )
    return actor_id, roles, default_role


def configured_ui_identity(requested_role: str = "") -> tuple[str, tuple[str, ...], str]:
    actor_id, roles, default_role = _configured_identity()
    requested = requested_role.strip().lower()
    if requested:
        role = next(
            (
                configured_role
                for configured_role in roles
                if hmac.compare_digest(requested, configured_role)
            ),
            "",
        )
    else:
        role = default_role
    if not role:
        raise HTTPException(status_code=403, detail={"error": "ROLE_SWITCH_FORBIDDEN"})
    return actor_id, roles, role


def issue_ui_session(
    *,
    tenant_id: str,
    actor_id: str,
    role: str,
    allowed_roles: tuple[str, ...],
    test_account: bool = False,
    ttl_seconds: int = SESSION_TTL_SECONDS,
    authorization_reference: str = "",
) -> tuple[str, str, int]:
    csrf_token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + ttl_seconds
    payload = {
        "v": 1,
        "tenant_id": tenant_id,
        "actor_id": actor_id,
        "role": role,
        "allowed_roles": list(allowed_roles),
        "csrf_digest": hashlib.sha256(csrf_token.encode("utf-8")).hexdigest(),
        "expires_at": expires_at,
        "test_account": test_account,
        "authorization_reference": authorization_reference,
    }
    encoded = _b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = _b64encode(
        hmac.new(_session_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{encoded}.{signature}", csrf_token, expires_at


def _test_ticket_secret() -> bytes:
    value = os.environ.get("AIVAN_UI_TEST_TICKET_SECRET", "").strip()
    if len(value) < 32:
        raise ValueError("AIVAN_UI_TEST_TICKET_SECRET must contain at least 32 characters")
    return value.encode("utf-8")


def validate_test_ticket_configuration() -> None:
    _test_ticket_secret()


def test_session_ttl_seconds() -> int:
    try:
        configured = int(
            os.environ.get(
                "AIVAN_UI_TEST_SESSION_TTL_SECONDS", str(TEST_SESSION_TTL_SECONDS)
            )
        )
    except ValueError:
        configured = TEST_SESSION_TTL_SECONDS
    return max(60, min(configured, 60 * 60))


def issue_test_login_ticket(
    *, now: int | None = None, ttl_seconds: int = TEST_TICKET_TTL_SECONDS
) -> str:
    """Create a short-lived test-login ticket for offline/server-side tooling."""

    issued_at = int(time.time()) if now is None else int(now)
    ttl = max(30, min(int(ttl_seconds), 10 * 60))
    payload = {
        "v": 1,
        "purpose": "myaivan_ui_test_login",
        "jti": secrets.token_urlsafe(18),
        "issued_at": issued_at,
        "expires_at": issued_at + ttl,
    }
    encoded = _b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = _b64encode(
        hmac.new(_test_ticket_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{encoded}.{signature}"


def consume_test_login_ticket(ticket: str, *, now: int | None = None) -> str:
    """Validate and atomically consume one test-login ticket.

    Returns a non-secret digest prefix suitable for audit correlation.
    """

    current = int(time.time()) if now is None else int(now)
    try:
        encoded, signature = ticket.split(".", 1)
        expected = _b64encode(
            hmac.new(
                _test_ticket_secret(), encoded.encode("ascii"), hashlib.sha256
            ).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        payload = json.loads(_b64decode(encoded))
        if not isinstance(payload, dict):
            raise ValueError("payload")
        if payload.get("v") != 1 or payload.get("purpose") != "myaivan_ui_test_login":
            raise ValueError("purpose")
        issued_at = int(payload["issued_at"])
        expires_at = int(payload["expires_at"])
        if not str(payload["jti"]) or issued_at > current + 30:
            raise ValueError("issued_at")
        if expires_at <= current or expires_at - issued_at > 10 * 60:
            raise ValueError("expires_at")
    except (
        binascii.Error,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("invalid test login ticket") from exc

    digest = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
    with _TEST_TICKET_LOCK:
        expired = [key for key, expiry in _CONSUMED_TEST_TICKETS.items() if expiry <= current]
        for key in expired:
            _CONSUMED_TEST_TICKETS.pop(key, None)
        if digest in _CONSUMED_TEST_TICKETS:
            raise ValueError("test login ticket already consumed")
        _CONSUMED_TEST_TICKETS[digest] = expires_at
    return digest[:16]


def read_ui_session(request: Request) -> UISession | None:
    token = request.cookies.get(SESSION_COOKIE, "").strip()
    if not token:
        return None
    try:
        encoded, signature = token.split(".", 1)
        expected = _b64encode(
            hmac.new(_session_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        payload = json.loads(_b64decode(encoded))
        session = UISession(
            tenant_id=str(payload["tenant_id"]),
            actor_id=str(payload["actor_id"]),
            role=str(payload["role"]),
            allowed_roles=tuple(str(item) for item in payload["allowed_roles"]),
            csrf_digest=str(payload["csrf_digest"]),
            expires_at=int(payload["expires_at"]),
            test_account=bool(payload.get("test_account", False)),
            authorization_reference=str(payload.get("authorization_reference", "")),
        )
    except (
        binascii.Error,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise HTTPException(status_code=401, detail={"error": "INVALID_UI_SESSION"}) from exc
    if session.expires_at <= int(time.time()):
        raise HTTPException(status_code=401, detail={"error": "UI_SESSION_EXPIRED"})
    if session.role not in session.allowed_roles:
        raise HTTPException(status_code=401, detail={"error": "INVALID_UI_SESSION_ROLE"})
    return session


def require_session_csrf(request: Request, session: UISession) -> None:
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    supplied = request.headers.get("X-AIVAN-CSRF", "").strip()
    digest = hashlib.sha256(supplied.encode("utf-8")).hexdigest()
    if not supplied or not hmac.compare_digest(digest, session.csrf_digest):
        raise HTTPException(status_code=403, detail={"error": "CSRF_REQUIRED"})
