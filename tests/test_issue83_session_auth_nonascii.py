"""Issue #83: session-auth Unicode inputs must fail closed without side effects."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

import pytest
from fastapi import HTTPException, Request, Response

from aivan.api.request_context import RequestContext
from aivan.api.session_auth import (
    UISession,
    configured_ui_identity,
    read_ui_session,
    require_session_csrf,
)


def _request(
    *headers: tuple[bytes, bytes], method: str = "GET", path: str = "/"
) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": list(headers),
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "state": {},
        }
    )


def _production_session_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_API_KEY", "issue83-ascii-secret")
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-issue83")
    monkeypatch.setenv("AIVAN_UI_ACTOR_ID", "auditor-issue83")
    monkeypatch.setenv("AIVAN_UI_ALLOWED_ROLES", "auditor,buyer")
    monkeypatch.setenv("AIVAN_UI_DEFAULT_ROLE", "auditor")
    monkeypatch.setenv("AIVAN_UI_SESSION_SECRET", "issue83-session-secret-at-least-32-bytes")
    monkeypatch.delenv("AIVAN_AUTH_SECRET", raising=False)
    monkeypatch.delenv("AIVAN_TENANT_API_KEYS", raising=False)


async def _raw_asgi_post(
    app: Callable[..., Awaitable[None]],
    *,
    path: str,
    headers: list[tuple[bytes, bytes]],
    body: bytes,
) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    request_sent = False
    messages: list[dict] = []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "state": {},
    }

    async def receive() -> dict:
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    await app(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return start["status"], start.get("headers", []), response_body


def test_nonascii_requested_role_is_stable_forbidden() -> None:
    with pytest.raises(HTTPException) as exc_info:
        configured_ui_identity("买家")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {"error": "ROLE_SWITCH_FORBIDDEN"}


def test_raw_login_nonascii_role_has_no_session_or_downstream_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _production_session_profile(monkeypatch)
    from aivan.api import main, session_routes

    side_effects = {"session": 0, "downstream": 0}

    def _session_must_not_be_issued(*args, **kwargs):
        side_effects["session"] += 1
        raise AssertionError("invalid role must not issue a session")

    def _downstream_must_not_run(*args, **kwargs):
        side_effects["downstream"] += 1
        raise AssertionError("invalid role must not reach downstream work")

    monkeypatch.setattr(session_routes, "issue_ui_session", _session_must_not_be_issued)
    monkeypatch.setattr(main, "execute_rfq", _downstream_must_not_run, raising=False)
    body = json.dumps({"role": "买家"}, ensure_ascii=False).encode("utf-8")

    status, response_headers, response_body = asyncio.run(
        _raw_asgi_post(
            main.app,
            path="/api/session/login",
            headers=[
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"x-aivan-api-key", b"issue83-ascii-secret"),
                (b"x-aivan-tenant-id", b"tenant-issue83"),
                (b"x-aivan-trace-id", b"trace-issue83-login"),
            ],
            body=body,
        )
    )

    assert status == 403
    assert json.loads(response_body) == {"detail": {"error": "ROLE_SWITCH_FORBIDDEN"}}
    assert side_effects == {"session": 0, "downstream": 0}
    assert not any(name.lower() == b"set-cookie" for name, _ in response_headers)


def test_nonascii_role_switch_has_no_new_session_or_role_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _production_session_profile(monkeypatch)
    from aivan.api import session_routes

    session = UISession(
        tenant_id="tenant-issue83",
        actor_id="auditor-issue83",
        role="auditor",
        allowed_roles=("auditor", "buyer"),
        csrf_digest="0" * 64,
        expires_at=4_000_000_000,
    )
    context = RequestContext(
        tenant_id="tenant-issue83",
        trace_id="trace-issue83-role",
        idempotency_key="",
        actor_id="auditor-issue83",
        role_context="auditor",
        conversation_role="",
        execution_mode="",
        channel_account_id="",
        participant_actor_id="",
        participant_role_context="",
        participant_conversation_role="",
        authorization_basis="ui_session",
        production=True,
    )
    issued = 0

    def _session_must_not_be_issued(*args, **kwargs):
        nonlocal issued
        issued += 1
        raise AssertionError("invalid role must not issue a replacement session")

    monkeypatch.setattr(session_routes, "read_ui_session", lambda request: session)
    monkeypatch.setattr(session_routes, "issue_ui_session", _session_must_not_be_issued)

    with pytest.raises(HTTPException) as exc_info:
        session_routes.switch_role(
            _request(method="POST", path="/api/session/role"),
            Response(),
            {"role": "买家"},
            context,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {"error": "ROLE_SWITCH_FORBIDDEN"}
    assert issued == 0
    assert session.role == "auditor"


@pytest.mark.parametrize(
    "raw_cookie",
    [b"aivan_session=payload.\xff", b"aivan_session=\xff.signature"],
)
def test_nonascii_session_cookie_remains_structured_401(raw_cookie: bytes) -> None:
    with pytest.raises(HTTPException) as exc_info:
        read_ui_session(_request((b"cookie", raw_cookie)))

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == {"error": "INVALID_UI_SESSION"}


def test_nonascii_csrf_remains_structured_403() -> None:
    session = UISession(
        tenant_id="tenant-issue83",
        actor_id="auditor-issue83",
        role="auditor",
        allowed_roles=("auditor",),
        csrf_digest="0" * 64,
        expires_at=4_000_000_000,
    )
    with pytest.raises(HTTPException) as exc_info:
        require_session_csrf(
            _request((b"x-aivan-csrf", b"\xff"), method="POST"),
            session,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {"error": "CSRF_REQUIRED"}


def test_legacy_gpm_hmac_nonascii_signature_remains_fail_closed() -> None:
    from aivan.gpm.auth import _verify_hmac

    assert _verify_hmac("tenant-issue83:\N{LATIN SMALL LETTER Y WITH DIAERESIS}", "secret") is None
