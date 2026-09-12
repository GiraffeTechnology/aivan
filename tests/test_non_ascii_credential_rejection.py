"""A non-ASCII credential must be rejected, not crash the server.

ASGI decodes request headers as latin-1. A client that sends a single raw
header byte in the 0x80-0xFF range therefore hands the auth path a ``str``
containing a code point above U+007F, and ``hmac.compare_digest`` raises
``TypeError`` on exactly that input. Before the fix an unauthenticated caller
could turn every authenticated route into a 500 with one byte.

These tests build the ASGI scope by hand. That is deliberate: ``TestClient``
(and the httpx stack under it) encodes headers as ASCII before the request is
ever sent, so a ``TestClient``-based test raises ``UnicodeEncodeError`` in the
client and passes whether or not the server is fixed. ``test_testclient_cannot_reach_this``
pins that trap so the technique is not quietly reverted.
"""

from __future__ import annotations

import hmac
import os

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from aivan.api.request_context import resolve_request_context
from aivan.api.secure_compare import secure_compare_str

# One raw latin-1 byte. Legal on the wire, illegal for compare_digest.
RAW_NON_ASCII = b"\xff"
DECODED_NON_ASCII = RAW_NON_ASCII.decode("latin-1")

_AUTH_ENV = (
    "AIVAN_ENV",
    "AIVAN_API_KEY",
    "AIVAN_AUTH_SECRET",
    "AIVAN_TENANT_ID",
    "AIVAN_TENANT_API_KEYS",
    "AIVAN_TEST_MODE",
)


@pytest.fixture(autouse=True)
def _clean_auth_env(monkeypatch):
    for name in _AUTH_ENV:
        monkeypatch.delenv(name, raising=False)


def _request(headers: list[tuple[bytes, bytes]], method: str = "POST") -> Request:
    """A Starlette Request carrying raw header bytes, with no client in between."""
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.1"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": "/api/rfq",
            "raw_path": b"/api/rfq",
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": ("127.0.0.1", 54321),
            "server": ("testserver", 80),
        }
    )


def test_raw_byte_really_decodes_to_non_ascii():
    """Guard the premise: the scope byte must survive as a non-ASCII str."""
    request = _request([(b"x-aivan-api-key", RAW_NON_ASCII)])
    supplied = request.headers.get("X-AIVAN-API-Key")
    assert supplied == DECODED_NON_ASCII
    assert any(ord(ch) > 0x7F for ch in supplied)


def test_compare_digest_would_raise_on_this_input():
    """Pin why the guard exists: the stdlib call this replaced raises here."""
    with pytest.raises(TypeError):
        hmac.compare_digest(DECODED_NON_ASCII, "expected-secret")


def test_secure_compare_str_rejects_non_ascii_without_raising():
    assert secure_compare_str(DECODED_NON_ASCII, "expected-secret") is False


def test_secure_compare_str_still_matches_equal_secrets():
    assert secure_compare_str("expected-secret", "expected-secret") is True
    assert secure_compare_str("expected-secret", "expected-secrex") is False


def test_secure_compare_str_handles_lone_surrogates():
    """Strict encoding would raise UnicodeEncodeError; surrogateescape must not."""
    assert secure_compare_str("\udcff", "expected-secret") is False


def test_non_ascii_api_key_is_403_not_500(monkeypatch):
    monkeypatch.setenv("AIVAN_API_KEY", "expected-secret")
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-1")

    request = _request([(b"x-aivan-api-key", RAW_NON_ASCII)])
    with pytest.raises(HTTPException) as excinfo:
        resolve_request_context(request, allow_ui_session=False)
    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == {"error": "INVALID_API_KEY"}


def test_non_ascii_bearer_token_is_403_not_500(monkeypatch):
    monkeypatch.setenv("AIVAN_AUTH_SECRET", "expected-secret")
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-1")

    request = _request([(b"authorization", b"Bearer " + RAW_NON_ASCII)])
    with pytest.raises(HTTPException) as excinfo:
        resolve_request_context(request, allow_ui_session=False)
    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == {"error": "INVALID_API_KEY"}


def test_non_ascii_tenant_scoped_key_is_403_not_500(monkeypatch):
    monkeypatch.setenv("AIVAN_TENANT_API_KEYS", '{"tenant-1": "expected-secret"}')
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-1")

    request = _request(
        [
            (b"x-aivan-api-key", RAW_NON_ASCII),
            (b"x-aivan-tenant-id", b"tenant-1"),
        ]
    )
    with pytest.raises(HTTPException) as excinfo:
        resolve_request_context(request, allow_ui_session=False)
    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == {"error": "INVALID_API_KEY"}


def test_correct_key_still_authenticates(monkeypatch):
    monkeypatch.setenv("AIVAN_API_KEY", "expected-secret")
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-1")

    request = _request([(b"x-aivan-api-key", b"expected-secret")])
    context = resolve_request_context(request, allow_ui_session=False)
    assert context.tenant_id == "tenant-1"


def test_non_ascii_role_in_body_is_403_not_500(monkeypatch):
    """The same failure class reached through a JSON body rather than a header."""
    from aivan.api.session_auth import configured_ui_identity

    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_UI_ACTOR_ID", "operator-1")
    monkeypatch.setenv("AIVAN_UI_ALLOWED_ROLES", "admin")

    with pytest.raises(HTTPException) as excinfo:
        configured_ui_identity("管理员")
    assert excinfo.value.status_code == 403


def test_testclient_cannot_reach_this():
    """Documents why these tests do not use TestClient.

    httpx encodes header values before sending, so a TestClient-based version
    of the tests above fails in the client and never exercises the server.
    A test written that way passes against unfixed code.
    """
    import httpx

    with pytest.raises(UnicodeEncodeError):
        httpx.Headers({"X-AIVAN-API-Key": DECODED_NON_ASCII}).raw


def test_env_fixture_isolated():
    assert os.environ.get("AIVAN_API_KEY") in (None, "")
