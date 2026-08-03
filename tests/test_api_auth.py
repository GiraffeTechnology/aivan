"""Tests for /api/openclaw/* route API-key authentication."""
from __future__ import annotations
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client():
    """TestClient backed by a StaticPool in-memory SQLite DB."""
    from aivan.api.main import app, get_db
    from aivan.db.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


_AUTH_ENV = (
    "AIVAN_ENV",
    "AIVAN_API_KEY",
    "AIVAN_AUTH_SECRET",
    "AIVAN_TENANT_ID",
    "AIVAN_TENANT_API_KEYS",
    "AIVAN_TEST_MODE",
    "AIVAN_TEST_TENANT_ID",
)


@pytest.fixture(autouse=True)
def clear_api_key():
    """Keep the shared request-context environment deterministic."""
    saved = {name: os.environ.get(name) for name in _AUTH_ENV}
    for name in _AUTH_ENV:
        os.environ.pop(name, None)
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


# ── No auth configured — all routes open ────────────────────────────────────

def test_events_no_key_configured_allowed(client):
    """When AIVAN_API_KEY is not set the endpoint is openly accessible."""
    resp = client.post(
        "/api/openclaw/events",
        json={
            "channel": "test",
            "conversation_id": "auth-test-conv-001",
            "sender_id": "buyer-001",
            "sender_display_name": "Test Buyer",
            "message_text": "I need 500 white cotton t-shirts",
            "role_context": "buyer",
            "mode": "auto",
        },
    )
    assert resp.status_code != 401
    assert resp.status_code != 403


# ── Auth configured — missing key ────────────────────────────────────────────

def test_events_missing_key_returns_401(client):
    os.environ["AIVAN_API_KEY"] = "secret-key-abc"
    resp = client.post("/api/openclaw/events", json={"channel": "test"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "AUTH_REQUIRED"


def test_drafts_approve_missing_key_returns_401(client):
    os.environ["AIVAN_API_KEY"] = "secret-key-abc"
    resp = client.post("/api/openclaw/drafts/some-id/approve", json={})
    assert resp.status_code == 401


def test_drafts_reject_missing_key_returns_401(client):
    os.environ["AIVAN_API_KEY"] = "secret-key-abc"
    resp = client.post("/api/openclaw/drafts/some-id/reject")
    assert resp.status_code == 401


def test_accounts_missing_key_returns_401(client):
    os.environ["AIVAN_API_KEY"] = "secret-key-abc"
    resp = client.get("/api/openclaw/accounts")
    assert resp.status_code == 401


# ── Auth configured — wrong key ───────────────────────────────────────────────

def test_events_wrong_key_returns_403(client):
    os.environ["AIVAN_API_KEY"] = "secret-key-abc"
    resp = client.post(
        "/api/openclaw/events",
        json={"channel": "test"},
        headers={"X-AIVAN-API-Key": "wrong-key"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "INVALID_API_KEY"


def test_drafts_approve_wrong_key_returns_403(client):
    os.environ["AIVAN_API_KEY"] = "secret-key-abc"
    resp = client.post(
        "/api/openclaw/drafts/some-id/approve",
        json={},
        headers={"X-AIVAN-API-Key": "wrong-key"},
    )
    assert resp.status_code == 403


# ── Auth configured — correct key ─────────────────────────────────────────────

def test_events_correct_key_passes_auth(client):
    os.environ["AIVAN_API_KEY"] = "secret-key-abc"
    resp = client.post(
        "/api/openclaw/events",
        json={
            "channel": "test",
            "conversation_id": "auth-test-conv-002",
            "sender_id": "buyer-002",
            "sender_display_name": "Test Buyer 2",
            "message_text": "I need 500 white cotton t-shirts",
            "role_context": "buyer",
            "mode": "auto",
        },
        headers={"X-AIVAN-API-Key": "secret-key-abc"},
    )
    assert resp.status_code not in (401, 403)


def test_accounts_correct_key_returns_200(client):
    os.environ["AIVAN_API_KEY"] = "secret-key-abc"
    resp = client.get(
        "/api/openclaw/accounts",
        headers={"X-AIVAN-API-Key": "secret-key-abc"},
    )
    assert resp.status_code == 200


# ── Health and dashboard routes are always open ────────────────────────────────

def test_health_always_open(client):
    os.environ["AIVAN_API_KEY"] = "secret-key-abc"
    resp = client.get("/health")
    assert resp.status_code == 200


def test_api_health_always_open(client):
    os.environ["AIVAN_API_KEY"] = "secret-key-abc"
    resp = client.get("/api/health")
    assert resp.status_code == 200


# ── Plugin alias routes (/api/drafts/*) also require auth ─────────────────────

def test_drafts_alias_missing_key_returns_401(client):
    os.environ["AIVAN_API_KEY"] = "secret-key-abc"
    resp = client.get("/api/drafts")
    assert resp.status_code == 401


def test_drafts_approve_alias_missing_key_returns_401(client):
    os.environ["AIVAN_API_KEY"] = "secret-key-abc"
    resp = client.post("/api/drafts/nonexistent/approve", json={})
    assert resp.status_code == 401


def test_drafts_reject_alias_missing_key_returns_401(client):
    os.environ["AIVAN_API_KEY"] = "secret-key-abc"
    resp = client.post("/api/drafts/nonexistent/reject")
    assert resp.status_code == 401
