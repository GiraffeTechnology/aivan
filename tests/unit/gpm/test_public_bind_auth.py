"""Regression tests for standalone GPM public-bind authentication."""

from __future__ import annotations

import ipaddress
import sys

import pytest
from fastapi.testclient import TestClient

from aivan.gpm.auth import generate_token
from aivan.gpm.server import PUBLIC_BIND_AUTH_ERROR, create_app

PUBLIC_TEST_HOST = str(ipaddress.ip_address(0xC000020A))


def _clear_auth_profiles(monkeypatch) -> None:
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.delenv("AIVAN_AUTH_SECRET", raising=False)
    monkeypatch.delenv("AIVAN_API_KEY", raising=False)
    monkeypatch.delenv("AIVAN_TENANT_ID", raising=False)
    monkeypatch.delenv("AIVAN_TENANT_API_KEYS", raising=False)
    monkeypatch.delenv("AIVAN_GPM_BIND_HOST", raising=False)
    monkeypatch.delenv("GIRAFFE_DB_BASE_URL", raising=False)


def test_direct_uvicorn_asgi_public_bind_fails_closed_at_startup(monkeypatch):
    """The exported app must inspect direct uvicorn --host startup."""

    _clear_auth_profiles(monkeypatch)
    monkeypatch.setattr(
        sys,
        "argv",
        ["uvicorn", "aivan.gpm.server:app", "--host", "0.0.0.0"],
    )

    direct_asgi_app = create_app()
    with pytest.raises(RuntimeError, match=PUBLIC_BIND_AUTH_ERROR):
        with TestClient(direct_asgi_app):
            pass


@pytest.mark.parametrize(
    ("profile_name", "profile_value", "request_headers"),
    [
        (
            "AIVAN_API_KEY",
            "deployment-key",
            {
                "X-AIVAN-API-Key": "deployment-key",
                "X-AIVAN-Tenant-ID": "tenant-a",
            },
        ),
        (
            "AIVAN_TENANT_API_KEYS",
            '{"tenant-a":"tenant-key"}',
            {
                "X-AIVAN-API-Key": "tenant-key",
                "X-AIVAN-Tenant-ID": "tenant-a",
            },
        ),
    ],
)
def test_api_key_profiles_alone_do_not_authenticate_public_gpm_requests(
    monkeypatch, profile_name, profile_value, request_headers
):
    """Configuration presence is insufficient; the actual request stays denied."""

    _clear_auth_profiles(monkeypatch)
    monkeypatch.setenv(profile_name, profile_value)
    with pytest.raises(RuntimeError, match=PUBLIC_BIND_AUTH_ERROR):
        with TestClient(create_app(bind_host="0.0.0.0")):
            pass

    loopback_configured_app = create_app(bind_host="127.0.0.1")

    with TestClient(
        loopback_configured_app,
        base_url=f"http://{PUBLIC_TEST_HOST}",
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/api/gpm/packets", headers=request_headers)

    assert response.status_code == 503
    assert response.json() == {"error": PUBLIC_BIND_AUTH_ERROR}


def test_public_gpm_requires_and_verifies_hmac_on_every_request(monkeypatch):
    _clear_auth_profiles(monkeypatch)
    monkeypatch.setenv("AIVAN_AUTH_SECRET", "public-gpm-secret")
    monkeypatch.setenv("AIVAN_API_KEY", "must-not-bypass-hmac")
    public_app = create_app(bind_host="0.0.0.0")

    with TestClient(
        public_app,
        base_url=f"http://{PUBLIC_TEST_HOST}",
        raise_server_exceptions=False,
    ) as client:
        missing = client.get("/api/gpm/packets")
        api_key_only = client.get(
            "/api/gpm/packets",
            headers={
                "X-AIVAN-API-Key": "must-not-bypass-hmac",
                "X-AIVAN-Tenant-ID": "tenant-a",
            },
        )
        token = generate_token("tenant-a", "public-gpm-secret")
        accepted = client.get(
            "/api/gpm/packets",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert missing.status_code == 401
    assert api_key_only.status_code == 401
    assert accepted.status_code == 200


def test_loopback_dev_remains_compatible_without_auth_secret(monkeypatch):
    _clear_auth_profiles(monkeypatch)
    loopback_app = create_app(bind_host="127.0.0.1")

    with TestClient(loopback_app, base_url="http://127.0.0.1") as client:
        response = client.get("/api/gpm/packets")

    assert response.status_code == 200
