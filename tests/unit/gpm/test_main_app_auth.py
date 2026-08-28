"""Auth wiring through the main AIVAN app lifespan (not just standalone GPM server)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aivan.gpm.auth import generate_token


@pytest.fixture()
def main_app_client(monkeypatch):
    """TestClient for main AIVAN app with HMAC auth secret set, no giraffe-db."""
    monkeypatch.setenv("AIVAN_AUTH_SECRET", "main-app-secret")
    monkeypatch.delenv("GIRAFFE_DB_BASE_URL", raising=False)

    from aivan.api.main import app
    with TestClient(app) as client:
        yield client


class TestMainAppGPMAuthWiring:
    def test_gpm_requires_auth_when_secret_set(self, main_app_client: TestClient) -> None:
        resp = main_app_client.get("/api/gpm/packets")
        assert resp.status_code == 401

    def test_gpm_valid_hmac_token_succeeds(self, main_app_client: TestClient) -> None:
        token = generate_token("tenant-main", "main-app-secret")
        resp = main_app_client.get(
            "/api/gpm/packets",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    def test_gpm_invalid_signature_returns_401(self, main_app_client: TestClient) -> None:
        resp = main_app_client.get(
            "/api/gpm/packets",
            headers={"Authorization": "Bearer tenant-main:badsig000"},
        )
        assert resp.status_code == 401

    def test_app_state_has_giraffe_db_client_after_startup(
        self, main_app_client: TestClient
    ) -> None:
        """app.state.giraffe_db_client must be set by lifespan (None when no URL)."""
        assert hasattr(main_app_client.app.state, "giraffe_db_client")
        # No GIRAFFE_DB_BASE_URL -> db_client is None
        assert main_app_client.app.state.giraffe_db_client is None


def test_production_gpm_route_rejects_forged_tenant_without_credentials(
    monkeypatch, production_runtime_policy
):
    """Regression for the audited unauthenticated cross-tenant write."""

    class FakeGiraffeDBClient:
        def __init__(self, base_url: str):
            self.base_url = base_url

        def check_schema_version(self):
            return None

        def get_tenant(self, tenant_id: str):
            return {"tenant_id": tenant_id, "status": "active"}

        def create_packet(self, packet: dict, tenant_id: str | None = None):
            return dict(packet)

        def list_packets(self, tenant_id: str, status: str | None = None):
            return []

    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_API_KEY", "deployment-key")
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-prod")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://giraffe-db.invalid")
    monkeypatch.setenv("GPM_LLM_RUNTIME_MODE", "live")
    monkeypatch.delenv("AIVAN_AUTH_SECRET", raising=False)
    monkeypatch.setattr(
        "aivan.gpm.giraffe_db_client.GiraffeDBClient", FakeGiraffeDBClient
    )

    from aivan.api import main

    # This regression targets tenant authentication, using the suite's
    # isolated database. Production schema startup has dedicated tests.
    monkeypatch.setattr(main, "init_db", lambda: None)

    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/gpm/quote-guidance",
            headers={"X-Tenant-ID": "attacker-tenant"},
            json={"sku": "SKU-1", "supplier_quote": 10.0},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "TENANT_MISMATCH"
