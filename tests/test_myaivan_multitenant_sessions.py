"""Production UI sessions honor authenticated multi-tenant key bindings."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aivan.api.session_routes import router


@pytest.fixture
def tenant_app(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.delenv("AIVAN_TENANT_ID", raising=False)
    monkeypatch.delenv("AIVAN_API_KEY", raising=False)
    monkeypatch.delenv("AIVAN_AUTH_SECRET", raising=False)
    monkeypatch.setenv("AIVAN_TENANT_API_KEYS", json.dumps({
        "tenant-a": "test-key-a", "tenant-b": "test-key-b",
    }))
    monkeypatch.setenv("AIVAN_UI_SESSION_SECRET", "test-session-secret-" * 3)
    monkeypatch.setenv("AIVAN_UI_ACTOR_ID", "operator")
    monkeypatch.setenv("AIVAN_UI_ALLOWED_ROLES", "buyer,approver")
    monkeypatch.setenv("AIVAN_UI_DEFAULT_ROLE", "buyer")
    application = FastAPI()
    application.include_router(router)
    return application


def login(client, tenant, key):
    return client.post("/api/session/login", headers={
        "X-AIVAN-Tenant-ID": tenant, "X-AIVAN-API-Key": key,
    }, json={})


def test_two_production_tenants_get_separate_sessions_and_can_switch_roles(tenant_app):
    with TestClient(tenant_app, base_url="https://testserver") as a, TestClient(
        tenant_app, base_url="https://testserver"
    ) as b:
        for client, tenant, key in ((a, "tenant-a", "test-key-a"), (b, "tenant-b", "test-key-b")):
            response = login(client, tenant, key)
            assert response.status_code == 200, response.text
            assert response.json()["tenant_id"] == tenant
            assert "Secure" in response.headers.get("set-cookie", "")
            assert client.get("/api/session").json()["tenant_id"] == tenant
            assert client.post("/api/session/role", json={"role": "approver"}).status_code == 403
            switched = client.post("/api/session/role", headers={
                "X-AIVAN-CSRF": response.json()["csrf_token"],
            }, json={"role": "approver"})
            assert switched.status_code == 200, switched.text
            assert switched.json()["tenant_id"] == tenant
            assert switched.json()["role"] == "approver"
        assert a.get("/api/session").json()["tenant_id"] == "tenant-a"
        assert b.get("/api/session").json()["tenant_id"] == "tenant-b"


def test_tenant_key_cannot_select_another_tenant(tenant_app):
    with TestClient(tenant_app, base_url="https://testserver") as client:
        response = login(client, "tenant-b", "test-key-a")
        assert response.status_code == 403
        assert "set-cookie" not in response.headers
        assert login(client, "unknown-tenant", "test-key-a").status_code == 403


def test_session_cookie_cannot_be_rebound_by_header_or_body(tenant_app):
    with TestClient(tenant_app, base_url="https://testserver") as client:
        response = login(client, "tenant-a", "test-key-a")
        csrf = response.json()["csrf_token"]
        assert client.get("/api/session", headers={"X-AIVAN-Tenant-ID": "tenant-b"}).status_code == 403
        spoofed = client.post("/api/session/role", headers={
            "X-AIVAN-CSRF": csrf, "X-AIVAN-Tenant-ID": "tenant-b",
        }, json={"role": "approver", "tenant_id": "tenant-b"})
        assert spoofed.status_code == 403
        changed = client.post("/api/session/role", headers={"X-AIVAN-CSRF": csrf},
                              json={"role": "approver", "tenant_id": "tenant-b"})
        assert changed.status_code == 200
        assert changed.json()["tenant_id"] == "tenant-a"


def test_single_tenant_deployment_binding_remains_authoritative(tenant_app, monkeypatch):
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-a")
    with TestClient(tenant_app, base_url="https://testserver") as client:
        assert login(client, "tenant-a", "test-key-a").status_code == 200
        assert login(client, "tenant-b", "test-key-b").status_code == 403


def test_removing_tenant_revokes_existing_ui_session(tenant_app, monkeypatch):
    with TestClient(tenant_app, base_url="https://testserver") as client:
        response = login(client, "tenant-a", "test-key-a")
        assert response.status_code == 200
        monkeypatch.setenv("AIVAN_TENANT_API_KEYS", json.dumps({"tenant-b": "test-key-b"}))
        assert client.get("/api/session").status_code == 403
        assert client.post("/api/session/role", headers={
            "X-AIVAN-CSRF": response.json()["csrf_token"],
        }, json={"role": "approver"}).status_code == 403
