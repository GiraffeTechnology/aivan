"""HTTP client for giraffe-db GPM packet persistence endpoints.

Connects to the giraffe-db service at GIRAFFE_DB_BASE_URL. All methods raise
GiraffeDBClientError on non-2xx responses (except get_packet which returns None
on 404). Transport errors (timeouts, connection failures) are also wrapped as
GiraffeDBClientError so callers can treat all failure modes uniformly.

Packet-scoped endpoints send X-Service-Tenant-ID + X-Service-Auth headers so
giraffe-db can enforce tenant ownership and verify the service caller identity.
Both headers carry facts already verified by AIVAN's HMAC auth layer.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)


class GiraffeDBClientError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GiraffeDBClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = httpx.Client()
        self._service_auth = os.getenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "")

    def _service_headers(self, tenant_id: str | None) -> dict[str, str]:
        """Build X-Service-Tenant-ID + X-Service-Auth headers for protected requests."""
        headers: dict[str, str] = {}
        if tenant_id:
            headers["X-Service-Tenant-ID"] = tenant_id
        if self._service_auth:
            headers["X-Service-Auth"] = self._service_auth
        return headers

    def check_schema_version(self) -> dict:
        """GET /api/data/schema-version — used as connectivity probe."""
        url = f"{self.base_url}/api/data/schema-version"
        try:
            resp = self._session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise GiraffeDBClientError(
                f"check_schema_version failed: {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
        except Exception as exc:
            raise GiraffeDBClientError(f"check_schema_version failed: {exc}") from exc

    def get_tenant(self, tenant_id: str) -> dict | None:
        """GET /api/data/tenants/{tenant_id} — None if 404."""
        url = f"{self.base_url}/api/data/tenants/{tenant_id}"
        try:
            resp = self._session.get(url, timeout=self.timeout)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise GiraffeDBClientError(
                f"get_tenant failed: {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
        except Exception as exc:
            # Covers httpx.RequestError (ConnectError, TimeoutException, etc.)
            # and any other transport failure; lets auth fall back to HMAC-only.
            raise GiraffeDBClientError(f"get_tenant failed: {exc}") from exc

    # ── Packet CRUD ────────────────────────────────────────────────────────

    def create_packet(self, packet: dict, tenant_id: str | None = None) -> dict:
        """POST /api/data/gpm/packets

        tenant_id is sent as X-Service-Tenant-ID; falls back to packet["tenant_id"]
        so callers that don't pass it explicitly still get the header set.
        """
        url = f"{self.base_url}/api/data/gpm/packets"
        tid = tenant_id or packet.get("tenant_id")
        headers = self._service_headers(tid)
        try:
            resp = self._session.post(url, json=packet, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise GiraffeDBClientError(
                f"create_packet failed: {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc

    def get_packet(self, packet_id: str, tenant_id: str | None = None) -> dict | None:
        """GET /api/data/gpm/packets/{packet_id} — None if 404.

        Passes X-Service-Tenant-ID + X-Service-Auth headers so giraffe-db can
        enforce ownership and verify the caller before returning data.
        """
        url = f"{self.base_url}/api/data/gpm/packets/{packet_id}"
        headers = self._service_headers(tenant_id)
        try:
            resp = self._session.get(url, headers=headers, timeout=self.timeout)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise GiraffeDBClientError(
                f"get_packet failed: {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc

    def update_packet_status(
        self,
        packet_id: str,
        approval_status: str,
        operator_id: str,
        notes: str | None = None,
        tenant_id: str | None = None,
    ) -> dict:
        """PATCH /api/data/gpm/packets/{packet_id}"""
        url = f"{self.base_url}/api/data/gpm/packets/{packet_id}"
        body = {"approval_status": approval_status, "operator_id": operator_id, "notes": notes}
        headers = self._service_headers(tenant_id)
        try:
            resp = self._session.patch(url, json=body, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise GiraffeDBClientError(
                f"update_packet_status failed: {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc

    def list_packets(
        self,
        tenant_id: str = "default",
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """GET /api/data/gpm/packets"""
        url = f"{self.base_url}/api/data/gpm/packets"
        params: dict = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        headers = self._service_headers(tenant_id)
        try:
            resp = self._session.get(url, params=params, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json().get("packets", [])
        except httpx.HTTPStatusError as exc:
            raise GiraffeDBClientError(
                f"list_packets failed: {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc

    def create_audit_record(
        self,
        packet_id: str,
        operator_id: str,
        action: str,
        notes: str | None = None,
        tenant_id: str | None = None,
    ) -> dict:
        """POST /api/data/gpm/packets/{packet_id}/audit"""
        url = f"{self.base_url}/api/data/gpm/packets/{packet_id}/audit"
        body = {"operator_id": operator_id, "action": action, "notes": notes}
        headers = self._service_headers(tenant_id)
        try:
            resp = self._session.post(url, json=body, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise GiraffeDBClientError(
                f"create_audit_record failed: {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
