"""Verify GiraffeDBClient sends correct X-Service-Tenant-ID + X-Service-Auth headers."""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from aivan.gpm.giraffe_db_client import GiraffeDBClient
from aivan.gpm.persistence_contract import PersistenceContractError


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

    def test_create_packet_never_infers_tenant_from_body(
        self, client_with_secret: GiraffeDBClient
    ) -> None:
        packet = {"packet_id": "p1", "tenant_id": "beta", "sku": "SKU1", "supplier_quote": 1.0, "currency": "USD"}
        with pytest.raises(PersistenceContractError) as exc_info:
            client_with_secret.create_packet(packet)
        assert exc_info.value.code == "GPM_TENANT_REQUIRED"

    def test_get_packet_sends_both_headers(self, client_with_secret: GiraffeDBClient) -> None:
        resp_body = {"packet_id": "p1", "tenant_id": "acme"}
        with patch.object(client_with_secret._session, "get", return_value=_mock_response(resp_body)) as mock:
            client_with_secret.get_packet("p1", tenant_id="acme")
        headers = mock.call_args[1]["headers"]
        assert headers["X-Service-Tenant-ID"] == "acme"
        assert headers["X-Service-Auth"] == "test-svc-secret"

    def test_legacy_nonatomic_status_update_is_disabled(self, client_with_secret: GiraffeDBClient) -> None:
        with pytest.raises(PersistenceContractError) as exc_info:
            client_with_secret.update_packet_status("p1", "approved", "op1", tenant_id="acme")
        assert exc_info.value.code == "GPM_LEGACY_NONATOMIC_MUTATION_DISABLED"

    def test_list_packets_sends_both_headers(self, client_with_secret: GiraffeDBClient) -> None:
        with patch.object(
            client_with_secret._session, "get", return_value=_mock_response({"packets": []})
        ) as mock:
            client_with_secret.list_packets(tenant_id="acme")
        headers = mock.call_args[1]["headers"]
        assert headers["X-Service-Tenant-ID"] == "acme"
        assert headers["X-Service-Auth"] == "test-svc-secret"

    def test_legacy_separate_audit_write_is_disabled(self, client_with_secret: GiraffeDBClient) -> None:
        with pytest.raises(PersistenceContractError) as exc_info:
            client_with_secret.create_audit_record("p1", "op1", "approved", tenant_id="acme")
        assert exc_info.value.code == "GPM_LEGACY_NONATOMIC_AUDIT_DISABLED"

    def test_missing_service_auth_fails_closed(self, client_no_secret: GiraffeDBClient) -> None:
        with pytest.raises(PersistenceContractError) as exc_info:
            client_no_secret.get_packet("p1", tenant_id="acme")
        assert exc_info.value.code == "GPM_SERVICE_AUTH_MISCONFIGURED"

    def test_missing_tenant_fails_closed(self, client_with_secret: GiraffeDBClient) -> None:
        with pytest.raises(PersistenceContractError) as exc_info:
            client_with_secret.get_packet("p1", tenant_id=None)
        assert exc_info.value.code == "GPM_TENANT_REQUIRED"
