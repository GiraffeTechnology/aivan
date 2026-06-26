"""Unit tests for GPM multi-tenant HMAC auth."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from aivan.gpm.auth import _verify_hmac, generate_token, make_require_auth
from aivan.gpm.giraffe_db_client import GiraffeDBClientError


def _make_request(headers: dict | None = None) -> MagicMock:
    req = MagicMock()
    req.headers = headers or {}
    req.app.state.giraffe_db_client = None
    return req


def _run(coro):
    return asyncio.run(coro)


# ── Token generation and HMAC verification ──────────────────────────────────

def test_generate_and_verify_token():
    token = generate_token("tenant-1", "super-secret")
    assert _verify_hmac(token, "super-secret") == "tenant-1"


def test_verify_wrong_signature():
    token = generate_token("tenant-1", "super-secret")
    tenant_id, sig = token.split(":", 1)
    bad_token = f"{tenant_id}:{'0' * len(sig)}"
    assert _verify_hmac(bad_token, "super-secret") is None


def test_verify_malformed_no_colon():
    assert _verify_hmac("notokenformat", "secret") is None


def test_verify_empty_token():
    assert _verify_hmac("", "secret") is None


def test_verify_empty_tenant_id():
    assert _verify_hmac(":somesig", "secret") is None


def test_tenant_a_token_not_valid_for_tenant_b():
    token_a = generate_token("tenant-a", "shared-secret")
    assert _verify_hmac(token_a, "shared-secret") == "tenant-a"
    _, sig = token_a.split(":", 1)
    assert _verify_hmac(f"tenant-b:{sig}", "shared-secret") is None


# ── Dev mode (no secret) ────────────────────────────────────────────────────

def test_dev_mode_reads_x_tenant_id_header(monkeypatch):
    monkeypatch.delenv("AIVAN_AUTH_SECRET", raising=False)
    auth = make_require_auth()
    req = _make_request({"X-Tenant-ID": "dev-tenant"})
    assert _run(auth(req)) == "dev-tenant"


def test_dev_mode_defaults_to_default_when_no_header(monkeypatch):
    monkeypatch.delenv("AIVAN_AUTH_SECRET", raising=False)
    auth = make_require_auth()
    assert _run(auth(_make_request({}))) == "default"


# ── Auth with secret set ────────────────────────────────────────────────────

def test_valid_token_active_tenant(monkeypatch):
    monkeypatch.setenv("AIVAN_AUTH_SECRET", "test-secret")
    db = MagicMock()
    db.get_tenant.return_value = {"tenant_id": "t1", "status": "active", "name": "T1"}
    auth = make_require_auth(db_client=db)
    token = generate_token("t1", "test-secret")
    assert _run(auth(_make_request({"Authorization": f"Bearer {token}"}))) == "t1"


def test_valid_token_tenant_not_found(monkeypatch):
    monkeypatch.setenv("AIVAN_AUTH_SECRET", "test-secret")
    db = MagicMock()
    db.get_tenant.return_value = None
    auth = make_require_auth(db_client=db)
    token = generate_token("ghost", "test-secret")
    with pytest.raises(HTTPException) as exc_info:
        _run(auth(_make_request({"Authorization": f"Bearer {token}"})))
    assert exc_info.value.status_code == 401


def test_valid_token_tenant_inactive(monkeypatch):
    monkeypatch.setenv("AIVAN_AUTH_SECRET", "test-secret")
    db = MagicMock()
    db.get_tenant.return_value = {"tenant_id": "t2", "status": "suspended", "name": "T2"}
    auth = make_require_auth(db_client=db)
    token = generate_token("t2", "test-secret")
    with pytest.raises(HTTPException) as exc_info:
        _run(auth(_make_request({"Authorization": f"Bearer {token}"})))
    assert exc_info.value.status_code == 403


def test_valid_token_giraffe_db_unavailable_degrades(monkeypatch):
    monkeypatch.setenv("AIVAN_AUTH_SECRET", "test-secret")
    db = MagicMock()
    db.get_tenant.side_effect = GiraffeDBClientError("connection refused")
    auth = make_require_auth(db_client=db)
    token = generate_token("t3", "test-secret")
    # Falls back to HMAC-only and returns tenant_id
    assert _run(auth(_make_request({"Authorization": f"Bearer {token}"}))) == "t3"


def test_missing_auth_header_raises_401(monkeypatch):
    monkeypatch.setenv("AIVAN_AUTH_SECRET", "test-secret")
    auth = make_require_auth()
    with pytest.raises(HTTPException) as exc_info:
        _run(auth(_make_request({})))
    assert exc_info.value.status_code == 401


def test_invalid_signature_raises_401(monkeypatch):
    monkeypatch.setenv("AIVAN_AUTH_SECRET", "test-secret")
    auth = make_require_auth()
    with pytest.raises(HTTPException) as exc_info:
        _run(auth(_make_request({"Authorization": "Bearer tenant-x:baadsignature000"})))
    assert exc_info.value.status_code == 401
