"""Authenticated HTTP consumer for the enabled GPM packet persistence API."""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import quote

import httpx

GPM_PACKET_API_VERSION = "gpm.packet-persistence.v1"
REQUIRED_PACKET_CAPABILITIES = (
    "create_packet",
    "read_packet",
    "idempotent_create",
)
_SAFE_OUTBOUND_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class GiraffeDBClientError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        *,
        error_code: str = "GPM_DB_REQUEST_FAILED",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class GiraffeDBClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = httpx.Client(follow_redirects=False)
        self._service_auth = os.getenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "").strip()
        self._tenant_service_auth = self._load_tenant_service_auth()

    @staticmethod
    def _load_tenant_service_auth() -> dict[str, str] | None:
        raw = os.getenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", "").strip()
        if not raw:
            return None
        try:
            configured = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GiraffeDBClientError(
                "tenant service auth configuration is invalid",
                error_code="GPM_DB_SERVICE_AUTH_MISCONFIGURED",
            ) from exc
        if (
            not isinstance(configured, dict)
            or not configured
            or any(
                not isinstance(tenant_id, str)
                or not tenant_id
                or not isinstance(secret, str)
                or not secret
                for tenant_id, secret in configured.items()
            )
        ):
            raise GiraffeDBClientError(
                "tenant service auth configuration is invalid",
                error_code="GPM_DB_SERVICE_AUTH_MISCONFIGURED",
            )
        return configured

    def _service_headers(
        self,
        tenant_id: str | None,
        *,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        if tenant_id:
            headers["X-Service-Tenant-ID"] = tenant_id
        service_auth = self._service_auth
        if self._tenant_service_auth is not None:
            service_auth = self._tenant_service_auth.get(tenant_id or "", "")
            if not service_auth:
                raise GiraffeDBClientError(
                    "tenant service auth is not configured",
                    error_code="GPM_DB_SERVICE_AUTH_MISSING",
                )
        if service_auth:
            headers["X-Service-Auth"] = service_auth
        if correlation_id:
            headers["X-AIVAN-Correlation-ID"] = correlation_id
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    @staticmethod
    def _provider_error_code(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return f"GPM_DB_HTTP_{response.status_code}"
        if isinstance(body, dict):
            detail = body.get("detail", body)
            if isinstance(detail, dict) and isinstance(detail.get("error"), str):
                return detail["error"]
        return f"GPM_DB_HTTP_{response.status_code}"

    def _request(
        self,
        method: str,
        url: str,
        *,
        operation: str,
        expected_statuses: set[int],
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            request_method = getattr(self._session, method.lower())
            response = request_method(
                url,
                timeout=self.timeout,
                **kwargs,
            )
        except httpx.RequestError as exc:
            raise GiraffeDBClientError(
                f"{operation} transport failed",
                error_code="GPM_DB_TRANSPORT_ERROR",
            ) from exc
        if response.status_code not in expected_statuses:
            raise GiraffeDBClientError(
                f"{operation} failed: {response.status_code}",
                status_code=response.status_code,
                error_code=self._provider_error_code(response),
            )
        return response

    @staticmethod
    def _json(response: httpx.Response, *, operation: str) -> dict[str, Any]:
        try:
            value = response.json()
        except ValueError as exc:
            raise GiraffeDBClientError(
                f"{operation} returned invalid JSON",
                status_code=response.status_code,
                error_code="GPM_DB_INVALID_RESPONSE",
            ) from exc
        if not isinstance(value, dict):
            raise GiraffeDBClientError(
                f"{operation} returned a non-object response",
                status_code=response.status_code,
                error_code="GPM_DB_INVALID_RESPONSE",
            )
        return value

    @staticmethod
    def _require_tenant(
        value: dict[str, Any],
        *,
        tenant_id: str,
        operation: str,
    ) -> dict[str, Any]:
        if value.get("tenant_id") != tenant_id:
            raise GiraffeDBClientError(
                f"{operation} returned the wrong tenant",
                error_code="GPM_DB_TENANT_MISMATCH",
            )
        return value

    @staticmethod
    def _outbound_id(value: str) -> str:
        if not _SAFE_OUTBOUND_ID.fullmatch(value):
            raise GiraffeDBClientError(
                "invalid outbound packet id",
                error_code="GPM_INVALID_PACKET_ID",
            )
        return quote(value, safe="")

    def check_schema_version(
        self,
        tenant_id: str,
        *,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Probe the database schema identity with authenticated tenant context."""

        response = self._request(
            "GET",
            f"{self.base_url}/api/data/schema-version",
            operation="check_schema_version",
            expected_statuses={200},
            headers=self._service_headers(
                tenant_id,
                correlation_id=correlation_id,
            ),
        )
        value = self._json(response, operation="check_schema_version")
        if not isinstance(value.get("schema_version"), str):
            raise GiraffeDBClientError(
                "schema probe omitted schema_version",
                error_code="GPM_DB_SCHEMA_IDENTITY_MISSING",
            )
        return value

    def check_packet_capabilities(
        self,
        tenant_id: str,
        *,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Verify the narrow packet API; a schema label is not capability proof."""

        response = self._request(
            "GET",
            f"{self.base_url}/api/data/gpm/capabilities",
            operation="check_packet_capabilities",
            expected_statuses={200},
            headers=self._service_headers(
                tenant_id,
                correlation_id=correlation_id,
            ),
        )
        value = self._json(response, operation="check_packet_capabilities")
        capabilities = value.get("capabilities")
        if (
            value.get("api_version") != GPM_PACKET_API_VERSION
            or not isinstance(capabilities, dict)
            or any(capabilities.get(name) is not True for name in REQUIRED_PACKET_CAPABILITIES)
        ):
            raise GiraffeDBClientError(
                "gpm packet persistence capabilities do not match",
                error_code="GPM_PACKET_CAPABILITY_MISMATCH",
            )
        return value

    def get_tenant(
        self,
        tenant_id: str,
        *,
        correlation_id: str | None = None,
    ) -> dict[str, Any] | None:
        response = self._request(
            "GET",
            f"{self.base_url}/api/data/tenants/{quote(tenant_id, safe='')}",
            operation="get_tenant",
            expected_statuses={200, 404},
            headers=self._service_headers(
                tenant_id,
                correlation_id=correlation_id,
            ),
        )
        if response.status_code == 404:
            return None
        value = self._json(response, operation="get_tenant")
        returned_tenant = value.get("tenant_id") or value.get("id")
        if returned_tenant not in {None, tenant_id}:
            raise GiraffeDBClientError(
                "get_tenant returned the wrong tenant",
                error_code="GPM_DB_TENANT_MISMATCH",
            )
        return value

    def create_packet(
        self,
        packet: dict[str, Any],
        tenant_id: str | None = None,
        *,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        effective_tenant = tenant_id or packet.get("tenant_id")
        if (
            not isinstance(effective_tenant, str)
            or packet.get("tenant_id") != effective_tenant
        ):
            raise GiraffeDBClientError(
                "packet tenant does not match request tenant",
                error_code="GPM_DB_REQUEST_TENANT_MISMATCH",
            )
        response = self._request(
            "POST",
            f"{self.base_url}/api/data/gpm/packets",
            operation="create_packet",
            expected_statuses={200, 201},
            json=packet,
            headers=self._service_headers(
                effective_tenant,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
            ),
        )
        value = self._json(response, operation="create_packet")
        return self._require_tenant(
            value,
            tenant_id=effective_tenant,
            operation="create_packet",
        )

    def get_packet(
        self,
        packet_id: str,
        tenant_id: str | None = None,
        *,
        correlation_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not tenant_id:
            raise GiraffeDBClientError(
                "packet read requires tenant context",
                error_code="GPM_DB_TENANT_REQUIRED",
            )
        response = self._request(
            "GET",
            f"{self.base_url}/api/data/gpm/packets/{self._outbound_id(packet_id)}",
            operation="get_packet",
            expected_statuses={200, 404},
            headers=self._service_headers(
                tenant_id,
                correlation_id=correlation_id,
            ),
        )
        if response.status_code == 404:
            return None
        value = self._json(response, operation="get_packet")
        return self._require_tenant(value, tenant_id=tenant_id, operation="get_packet")

    def update_packet_status(
        self,
        packet_id: str,
        approval_status: str,
        operator_id: str,
        notes: str | None = None,
        tenant_id: str | None = None,
        *,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise GiraffeDBClientError(
                "packet update requires tenant context",
                error_code="GPM_DB_TENANT_REQUIRED",
            )
        response = self._request(
            "PATCH",
            f"{self.base_url}/api/data/gpm/packets/{self._outbound_id(packet_id)}",
            operation="update_packet_status",
            expected_statuses={200},
            json={
                "approval_status": approval_status,
                "operator_id": operator_id,
                "notes": notes,
            },
            headers=self._service_headers(
                tenant_id,
                correlation_id=correlation_id,
            ),
        )
        value = self._json(response, operation="update_packet_status")
        return self._require_tenant(
            value,
            tenant_id=tenant_id,
            operation="update_packet_status",
        )

    def list_packets(
        self,
        tenant_id: str,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        *,
        correlation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        response = self._request(
            "GET",
            f"{self.base_url}/api/data/gpm/packets",
            operation="list_packets",
            expected_statuses={200},
            params=params,
            headers=self._service_headers(
                tenant_id,
                correlation_id=correlation_id,
            ),
        )
        value = self._json(response, operation="list_packets")
        packets = value.get("packets")
        if not isinstance(packets, list) or not all(
            isinstance(item, dict) for item in packets
        ):
            raise GiraffeDBClientError(
                "list_packets returned an invalid envelope",
                error_code="GPM_DB_INVALID_RESPONSE",
            )
        return [
            self._require_tenant(item, tenant_id=tenant_id, operation="list_packets")
            for item in packets
        ]

    def create_audit_record(
        self,
        packet_id: str,
        operator_id: str,
        action: str,
        notes: str | None = None,
        tenant_id: str | None = None,
        *,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not tenant_id:
            raise GiraffeDBClientError(
                "audit write requires tenant context",
                error_code="GPM_DB_TENANT_REQUIRED",
            )
        response = self._request(
            "POST",
            f"{self.base_url}/api/data/gpm/packets/{self._outbound_id(packet_id)}/audit",
            operation="create_audit_record",
            expected_statuses={201},
            json={"operator_id": operator_id, "action": action, "notes": notes},
            headers=self._service_headers(
                tenant_id,
                correlation_id=correlation_id,
            ),
        )
        value = self._json(response, operation="create_audit_record")
        return self._require_tenant(
            value,
            tenant_id=tenant_id,
            operation="create_audit_record",
        )
