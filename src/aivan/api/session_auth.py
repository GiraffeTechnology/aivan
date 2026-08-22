from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import stat
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request


SESSION_COOKIE = "aivan_session"
CSRF_COOKIE = "aivan_csrf"
SESSION_TTL_SECONDS = 8 * 60 * 60
TEST_SESSION_TTL_SECONDS = 30 * 60
TEST_TICKET_TTL_SECONDS = 5 * 60


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
    path = _test_ticket_ledger_path()
    _open_test_ticket_ledger(path)


def _test_ticket_ledger_path() -> str:
    path = os.environ.get("AIVAN_UI_TEST_TICKET_LEDGER_PATH", "").strip()
    if not path or not os.path.isabs(path):
        raise ValueError("AIVAN_UI_TEST_TICKET_LEDGER_PATH must be an absolute regular path")
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        raise ValueError("AIVAN_UI_TEST_TICKET_LEDGER_PATH parent must already exist")
    parent_metadata = os.stat(parent, follow_symlinks=False)
    if not stat.S_ISDIR(parent_metadata.st_mode):
        raise ValueError("AIVAN_UI_TEST_TICKET_LEDGER_PATH parent must not be a symlink")
    if os.name != "nt" and (
        parent_metadata.st_uid != os.geteuid() or parent_metadata.st_mode & 0o077
    ):
        raise ValueError(
            "AIVAN_UI_TEST_TICKET_LEDGER_PATH parent must be owned by the "
            "service user and inaccessible to group/other users"
        )
    if os.path.lexists(path):
        metadata = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("AIVAN_UI_TEST_TICKET_LEDGER_PATH must be a regular file")
    normalized_path = os.path.normcase(os.path.realpath(path))
    database_url = os.environ.get("AIVAN_DB_URL", "").strip()
    database_paths = {"data/aivan.db", "data/aiven.db"}
    if database_url.startswith("sqlite:///"):
        configured_database = database_url.removeprefix("sqlite:///")
        if configured_database != ":memory:":
            database_paths.add(configured_database)
    if normalized_path in {
        os.path.normcase(os.path.realpath(database_path)) for database_path in database_paths
    }:
        raise ValueError("test ticket ledger must not share the business database path")
    return path


def _open_test_ticket_ledger(path: str) -> None:
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ValueError("unable to safely open test ticket ledger") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("test ticket ledger must be a regular file")
        if os.name != "nt" and (metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077):
            raise ValueError("test ticket ledger must be owned by the service user and mode 0600")
    finally:
        os.close(descriptor)


def _consume_test_ticket_digest(digest: str, expires_at: int, current: int) -> None:
    """Atomically persist a consumed digest across workers and restarts."""

    path = _test_ticket_ledger_path()
    _open_test_ticket_ledger(path)
    connection = sqlite3.connect(path, timeout=5, isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS consumed_test_tickets ("
            "digest TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)"
        )
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM consumed_test_tickets WHERE expires_at <= ?", (current,))
        connection.execute(
            "INSERT INTO consumed_test_tickets (digest, expires_at) VALUES (?, ?)",
            (digest, expires_at),
        )
        connection.execute("COMMIT")
    except sqlite3.IntegrityError as exc:
        connection.execute("ROLLBACK")
        raise ValueError("test login ticket already consumed") from exc
    except sqlite3.Error:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def test_session_ttl_seconds() -> int:
    try:
        configured = int(
            os.environ.get("AIVAN_UI_TEST_SESSION_TTL_SECONDS", str(TEST_SESSION_TTL_SECONDS))
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
    encoded = _b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
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
            hmac.new(_test_ticket_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
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
    _consume_test_ticket_digest(digest, expires_at, current)
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
