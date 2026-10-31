"""Issue #80: non-ASCII credential headers must fail closed, never raise 500."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

import pytest
from fastapi import HTTPException, Request

from aivan.api.request_context import resolve_request_context


def _raw_request(*headers: tuple[bytes, bytes], method: str = "GET", path: str = "/") -> Request:
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


def _production_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_API_KEY", "issue80-ascii-secret")
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-issue80")
    monkeypatch.delenv("AIVAN_AUTH_SECRET", raising=False)
    monkeypatch.delenv("AIVAN_TENANT_API_KEYS", raising=False)


@pytest.mark.parametrize(
    "credential_header",
    [
        (b"x-aivan-api-key", b"wrong-\xff-key"),
        (b"authorization", b"Bearer wrong-\xff-token"),
    ],
)
def test_resolve_request_context_rejects_raw_nonascii_credentials_as_structured_403(
    monkeypatch: pytest.MonkeyPatch,
    credential_header: tuple[bytes, bytes],
) -> None:
    _production_api_key(monkeypatch)
    request = _raw_request(
        credential_header,
        (b"x-aivan-tenant-id", b"tenant-issue80"),
        (b"x-aivan-trace-id", b"trace-issue80-context"),
    )

    with pytest.raises(HTTPException) as exc_info:
        resolve_request_context(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {"error": "INVALID_API_KEY"}
    assert "wrong" not in json.dumps(exc_info.value.detail)
    assert "\u00ff" not in json.dumps(exc_info.value.detail)


def test_non_bearer_raw_nonascii_authorization_keeps_existing_structured_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _production_api_key(monkeypatch)
    request = _raw_request(
        (b"authorization", b"Basic wrong-\xff-token"),
        (b"x-aivan-tenant-id", b"tenant-issue80"),
        (b"x-aivan-trace-id", b"trace-issue80-missing"),
    )

    with pytest.raises(HTTPException) as exc_info:
        resolve_request_context(request)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"] == "AUTH_REQUIRED"
    assert "wrong" not in json.dumps(exc_info.value.detail)
    assert "\u00ff" not in json.dumps(exc_info.value.detail)


def test_tenant_key_profile_rejects_raw_nonascii_credential_as_structured_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_TENANT_API_KEYS", '{"tenant-issue80":"tenant-ascii-secret"}')
    monkeypatch.delenv("AIVAN_API_KEY", raising=False)
    monkeypatch.delenv("AIVAN_AUTH_SECRET", raising=False)
    monkeypatch.delenv("AIVAN_TENANT_ID", raising=False)
    request = _raw_request(
        (b"x-aivan-api-key", b"wrong-\xff-key"),
        (b"x-aivan-tenant-id", b"tenant-issue80"),
        (b"x-aivan-trace-id", b"trace-issue80-tenant-map"),
    )

    with pytest.raises(HTTPException) as exc_info:
        resolve_request_context(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {"error": "INVALID_API_KEY"}


async def _raw_asgi_post(
    app: Callable[..., Awaitable[None]],
    *,
    path: str,
    headers: list[tuple[bytes, bytes]],
    body: bytes,
) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
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
    request_sent = False
    messages: list[dict] = []

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


@pytest.mark.parametrize(
    "credential_header",
    [
        (b"x-aivan-api-key", b"wrong-\xff-key"),
        (b"authorization", b"Bearer wrong-\xff-token"),
    ],
)
def test_raw_nonascii_credential_crosses_api_and_gpm_boundary_with_zero_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    credential_header: tuple[bytes, bytes],
) -> None:
    _production_api_key(monkeypatch)
    from aivan.api import main
    from aivan.gpm import router as gpm_router

    class _DBClientMustNotBeCalled:
        def get_tenant(self, *args, **kwargs):
            raise AssertionError("tenant lookup is a side effect after invalid authentication")

    def _handler_must_not_run(*args, **kwargs):
        raise AssertionError("GPM business handler must not run for invalid authentication")

    monkeypatch.setattr(main.app.state, "giraffe_db_client", _DBClientMustNotBeCalled(), raising=False)
    monkeypatch.setattr(gpm_router, "analyze_quote", _handler_must_not_run)
    monkeypatch.setattr(gpm_router, "mock_quote_analysis", _handler_must_not_run)

    status, response_headers, response_body = asyncio.run(
        _raw_asgi_post(
            main.app,
            path="/api/gpm/quote-guidance",
            headers=[
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", b"58"),
                credential_header,
                (b"x-aivan-tenant-id", b"tenant-issue80"),
                (b"x-aivan-trace-id", b"trace-issue80-gpm"),
            ],
            body=b'{"sku":"FIXTURE-80","supplier_quote":10.0,"currency":"USD"}',
        )
    )

    assert status == 403
    assert json.loads(response_body) == {"detail": {"error": "INVALID_API_KEY"}}
    assert b"wrong" not in response_body
    assert b"\xff" not in response_body
    assert (b"x-content-type-options", b"nosniff") in response_headers
