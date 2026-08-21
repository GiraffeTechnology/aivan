from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request


SESSION_COOKIE = "aivan_session"
CSRF_COOKIE = "aivan_csrf"
SESSION_TTL_SECONDS = 8 * 60 * 60


@dataclass(frozen=True)
class UISession:
    tenant_id: str
    actor_id: str
    role: str
    allowed_roles: tuple[str, ...]
    csrf_digest: str
    expires_at: int


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
    role = requested_role.strip().lower() or default_role
    if role not in roles:
        raise HTTPException(status_code=403, detail={"error": "ROLE_SWITCH_FORBIDDEN"})
    return actor_id, roles, role


def issue_ui_session(
    *, tenant_id: str, actor_id: str, role: str, allowed_roles: tuple[str, ...]
) -> tuple[str, str, int]:
    csrf_token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    payload = {
        "v": 1,
        "tenant_id": tenant_id,
        "actor_id": actor_id,
        "role": role,
        "allowed_roles": list(allowed_roles),
        "csrf_digest": hashlib.sha256(csrf_token.encode("utf-8")).hexdigest(),
        "expires_at": expires_at,
    }
    encoded = _b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = _b64encode(hmac.new(_session_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}", csrf_token, expires_at


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
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
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
