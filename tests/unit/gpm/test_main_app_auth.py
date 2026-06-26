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
