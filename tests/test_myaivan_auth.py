"""Authentication / production fail-closed tests for the myaivan Web UI.

Rules under test:
* local/dev with no secret → open demo access.
* production with no secret → every protected page/endpoint fails closed (503).
* secret configured → pages redirect to /myaivan/login; API requires a valid
  session cookie or X-AIVAN-API-Key / Bearer key (401 missing, 403 wrong).
* /api/myaivan/i18n/{lang} stays public (UI strings only, no user/case data).
"""

from __future__ import annotations

import time

import pytest

from aivan.web import auth as web_auth

KEY = "test-myaivan-access-key"


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.delenv("AIVAN_API_KEY", raising=False)
    monkeypatch.delenv("AIVAN_AUTH_SECRET", raising=False)


@pytest.fixture
def production_with_key(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_API_KEY", KEY)
    monkeypatch.delenv("AIVAN_AUTH_SECRET", raising=False)


# ── local/dev demo access ─────────────────────────────────────────────────────

def test_local_dev_demo_access_open(api_client, monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.delenv("AIVAN_API_KEY", raising=False)
    monkeypatch.delenv("AIVAN_AUTH_SECRET", raising=False)
    assert api_client.get("/myaivan").status_code == 200
    assert api_client.get("/myaivan/work").status_code == 200
    assert api_client.post("/api/myaivan/cases", json={}).status_code == 200
    # Login page is pointless in open mode → back to the welcome page.
    resp = api_client.get("/myaivan/login", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/myaivan"


# ── production without secret: fail closed ────────────────────────────────────

def test_production_without_secret_blocks_pages(api_client, production):
    for path in ("/myaivan", "/myaivan/work", "/myaivan/login"):
        resp = api_client.get(path)
        assert resp.status_code == 503, path
        assert "AIVAN_API_KEY" in resp.text


def test_production_without_secret_blocks_api(api_client, production):
    assert api_client.post("/api/myaivan/cases", json={}).status_code == 503
    assert api_client.get("/api/myaivan/cases/whatever").status_code == 503
    assert api_client.get("/api/myaivan/email/status").status_code == 503
    assert api_client.post("/api/myaivan/login", json={"key": "anything"}).status_code == 503


# ── production with key: pages require login, API requires key/session ───────

def test_production_pages_redirect_to_login(api_client, production_with_key):
    for path in ("/myaivan", "/myaivan/work"):
        resp = api_client.get(path, follow_redirects=False)
        assert resp.status_code == 303, path
        assert resp.headers["location"] == "/myaivan/login"
    assert api_client.get("/myaivan/login").status_code == 200


def test_production_api_unauthenticated_401(api_client, production_with_key):
    resp = api_client.post("/api/myaivan/cases", json={})
    assert resp.status_code == 401
    resp = api_client.get("/api/myaivan/cases/some-case")
    assert resp.status_code == 401


def test_production_api_wrong_key_403(api_client, production_with_key):
    resp = api_client.post(
        "/api/myaivan/cases", json={}, headers={"X-AIVAN-API-Key": "wrong"}
    )
    assert resp.status_code == 403


def test_production_api_key_header_and_bearer_work(api_client, production_with_key):
    resp = api_client.post("/api/myaivan/cases", json={}, headers={"X-AIVAN-API-Key": KEY})
    assert resp.status_code == 200
    resp = api_client.post(
        "/api/myaivan/cases", json={}, headers={"Authorization": f"Bearer {KEY}"}
    )
    assert resp.status_code == 200


# ── login session flow ────────────────────────────────────────────────────────

def test_login_session_grants_page_and_api_access(api_client, production_with_key):
    bad = api_client.post("/api/myaivan/login", json={"key": "wrong"})
    assert bad.status_code == 401

    ok = api_client.post("/api/myaivan/login", json={"key": KEY})
    assert ok.status_code == 200
    assert web_auth.SESSION_COOKIE in ok.cookies

    # Cookie is kept by the TestClient → pages and API now work.
    assert api_client.get("/myaivan", follow_redirects=False).status_code == 200
    assert api_client.get("/myaivan/work", follow_redirects=False).status_code == 200
    assert api_client.post("/api/myaivan/cases", json={}).status_code == 200


def test_logout_revokes_session(api_client, production_with_key):
    api_client.post("/api/myaivan/login", json={"key": KEY})
    assert api_client.get("/myaivan", follow_redirects=False).status_code == 200
    api_client.post("/api/myaivan/logout")
    resp = api_client.get("/myaivan", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/myaivan/login"


def test_tampered_or_expired_session_rejected(api_client, production_with_key):
    # Tampered signature
    api_client.cookies.set(web_auth.SESSION_COOKIE, f"{int(time.time()) + 3600}.deadbeef")
    assert api_client.get("/myaivan", follow_redirects=False).status_code == 303
    assert api_client.post("/api/myaivan/cases", json={}).status_code == 401

    # Expired but correctly signed token
    expired = web_auth.issue_session_token(now=time.time() - 2 * web_auth.session_ttl_seconds())
    assert not web_auth.verify_session_token(expired)
    api_client.cookies.set(web_auth.SESSION_COOKIE, expired)
    assert api_client.post("/api/myaivan/cases", json={}).status_code == 401


def test_rotating_secret_invalidates_sessions(api_client, production_with_key, monkeypatch):
    api_client.post("/api/myaivan/login", json={"key": KEY})
    assert api_client.post("/api/myaivan/cases", json={}).status_code == 200
    monkeypatch.setenv("AIVAN_API_KEY", "rotated-key")
    assert api_client.post("/api/myaivan/cases", json={}).status_code == 401


# ── i18n stays public (UI strings only) ───────────────────────────────────────

def test_i18n_public_in_production(api_client, production_with_key):
    resp = api_client.get("/api/myaivan/i18n/en")
    assert resp.status_code == 200
    data = resp.json()
    # Strictly UI strings — no case/user data in the payload.
    assert set(data) == {"lang", "source", "strings", "languages"}
    assert all(isinstance(v, str) for v in data["strings"].values())


def test_i18n_blocked_only_when_production_misconfigured_is_not_required(api_client, production):
    # Even in fail-closed production the catalog carries no user data; it stays
    # public so the login page itself can localize.
    assert api_client.get("/api/myaivan/i18n/en").status_code == 200
