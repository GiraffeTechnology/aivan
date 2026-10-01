"""Verify GiraffeDBClient sends correct X-Service-Tenant-ID + X-Service-Auth headers."""
from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from aivan.gpm.giraffe_db_client import GiraffeDBClient, GiraffeDBClientError


def _mock_response(json_body: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=json_body, request=httpx.Request("GET", "http://test"))


@pytest.fixture()
def client_with_secret(monkeypatch: pytest.MonkeyPatch) -> GiraffeDBClient:
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "test-svc-secret")
    return GiraffeDBClient("http://giraffe-db")


@pytest.fixture()
def client_no_secret(monkeypatch: pytest.MonkeyPatch) -> GiraffeDBClient:
    monkeypatch.delenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", raising=False)
    return GiraffeDBClient("http://giraffe-db")


class TestServiceHeaders:
    """Each method must send X-Service-Tenant-ID; X-Service-Auth sent only when secret is set."""

    def test_create_packet_sends_both_headers(self, client_with_secret: GiraffeDBClient) -> None:
        packet = {"packet_id": "p1", "tenant_id": "acme", "sku": "SKU1", "supplier_quote": 1.0, "currency": "USD"}
        with patch.object(client_with_secret._session, "post", return_value=_mock_response(packet, 201)) as mock:
            client_with_secret.create_packet(packet, tenant_id="acme")
        headers = mock.call_args[1]["headers"]
        assert headers["X-Service-Tenant-ID"] == "acme"
        assert headers["X-Service-Auth"] == "test-svc-secret"

    def test_create_packet_infers_tenant_from_body_when_not_explicit(
        self, client_with_secret: GiraffeDBClient
    ) -> None:
        packet = {"packet_id": "p1", "tenant_id": "beta", "sku": "SKU1", "supplier_quote": 1.0, "currency": "USD"}
        with patch.object(client_with_secret._session, "post", return_value=_mock_response(packet, 201)) as mock:
            client_with_secret.create_packet(packet)  # no explicit tenant_id
        headers = mock.call_args[1]["headers"]
        assert headers["X-Service-Tenant-ID"] == "beta"

    def test_get_packet_sends_both_headers(self, client_with_secret: GiraffeDBClient) -> None:
        resp_body = {"packet_id": "p1", "tenant_id": "acme"}
        with patch.object(client_with_secret._session, "get", return_value=_mock_response(resp_body)) as mock:
            client_with_secret.get_packet("p1", tenant_id="acme")
        headers = mock.call_args[1]["headers"]
        assert headers["X-Service-Tenant-ID"] == "acme"
        assert headers["X-Service-Auth"] == "test-svc-secret"

    def test_update_packet_status_sends_both_headers(self, client_with_secret: GiraffeDBClient) -> None:
        resp_body = {"packet_id": "p1", "tenant_id": "acme", "approval_status": "approved"}
        with patch.object(client_with_secret._session, "patch", return_value=_mock_response(resp_body)) as mock:
            client_with_secret.update_packet_status("p1", "approved", "op1", tenant_id="acme")
        headers = mock.call_args[1]["headers"]
        assert headers["X-Service-Tenant-ID"] == "acme"
        assert headers["X-Service-Auth"] == "test-svc-secret"

    def test_list_packets_sends_both_headers(self, client_with_secret: GiraffeDBClient) -> None:
        with patch.object(
            client_with_secret._session, "get", return_value=_mock_response({"packets": []})
        ) as mock:
            client_with_secret.list_packets(tenant_id="acme")
        headers = mock.call_args[1]["headers"]
        assert headers["X-Service-Tenant-ID"] == "acme"
        assert headers["X-Service-Auth"] == "test-svc-secret"

    def test_create_audit_record_sends_both_headers(self, client_with_secret: GiraffeDBClient) -> None:
        resp_body = {"audit_id": "a1", "packet_id": "p1", "tenant_id": "acme"}
        with patch.object(client_with_secret._session, "post", return_value=_mock_response(resp_body, 201)) as mock:
            client_with_secret.create_audit_record("p1", "op1", "approved", tenant_id="acme")
        headers = mock.call_args[1]["headers"]
        assert headers["X-Service-Tenant-ID"] == "acme"
        assert headers["X-Service-Auth"] == "test-svc-secret"

    def test_no_auth_header_when_secret_not_set(self, client_no_secret: GiraffeDBClient) -> None:
        resp_body = {"packet_id": "p1", "tenant_id": "acme"}
        with patch.object(client_no_secret._session, "get", return_value=_mock_response(resp_body)) as mock:
            client_no_secret.get_packet("p1", tenant_id="acme")
        headers = mock.call_args[1]["headers"]
        assert headers["X-Service-Tenant-ID"] == "acme"
        assert "X-Service-Auth" not in headers

    def test_packet_read_rejects_missing_tenant_context(
        self, client_with_secret: GiraffeDBClient
    ) -> None:
        with pytest.raises(GiraffeDBClientError) as exc_info:
            client_with_secret.get_packet("p1", tenant_id=None)

        assert exc_info.value.error_code == "GPM_DB_TENANT_REQUIRED"

    def test_tenant_scoped_credentials_select_matching_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", raising=False)
        monkeypatch.setenv(
            "GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON",
            json.dumps({"tenant-a": "secret-a", "tenant-b": "secret-b"}),
        )
        client = GiraffeDBClient("http://giraffe-db")
        packet = {"packet_id": "p1", "tenant_id": "tenant-b"}

        with patch.object(
            client._session,
            "post",
            return_value=_mock_response(packet, 201),
        ) as mock:
            client.create_packet(packet, tenant_id="tenant-b")

        headers = mock.call_args[1]["headers"]
        assert headers["X-Service-Tenant-ID"] == "tenant-b"
        assert headers["X-Service-Auth"] == "secret-b"

    def test_tenant_scoped_credentials_fail_closed_for_unknown_tenant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON",
            json.dumps({"tenant-a": "secret-a"}),
        )
        client = GiraffeDBClient("http://giraffe-db")

        with pytest.raises(GiraffeDBClientError) as exc_info:
            client.check_schema_version("tenant-b")

        assert exc_info.value.error_code == "GPM_DB_SERVICE_AUTH_MISSING"

    @pytest.mark.parametrize(
        "raw",
        ["not-json", "[]", '{"tenant-a": ""}', '{"": "secret"}'],
    )
    def test_tenant_scoped_credentials_reject_invalid_configuration(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        monkeypatch.setenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", raw)

        with pytest.raises(GiraffeDBClientError) as exc_info:
            GiraffeDBClient("http://giraffe-db")

        assert exc_info.value.error_code == "GPM_DB_SERVICE_AUTH_MISCONFIGURED"
