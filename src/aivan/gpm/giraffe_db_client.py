"""Versioned, fail-closed HTTP adapter for GPM persistence.

This is a consumer-side contract only. Real giraffe-db support for the atomic
decision operation remains an external Stage dependency and is not claimed.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote

import httpx

from aivan.gpm.persistence_contract import (
    GPM_PERSISTENCE_CONTRACT_VERSION,
    DecisionCommand,
    PersistenceContractError,
    require_atomic_decision_proof,
    require_response_tenant,
    require_safe_correlation_id,
)
from aivan.observability.safe_logging import log_exception_safely

logger = logging.getLogger(__name__)


class GiraffeDBClientError(PersistenceContractError):
    """Compatibility name for callers catching the legacy adapter error."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        *,
        correlation_id: str = "gpm-adapter",
    ) -> None:
        super().__init__(message, correlation_id=correlation_id, status_code=status_code)


class GiraffeDBClient:
    contract_version = GPM_PERSISTENCE_CONTRACT_VERSION

    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        *,
        service_auth: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = httpx.Client()
        self._service_auth = (
            service_auth
            if service_auth is not None
            else os.getenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "")
        ).strip()

    @staticmethod
    def _correlation(value: str | None) -> str:
        return require_safe_correlation_id(value)

    @staticmethod
    def _path_segment(value: str) -> str:
        return quote(value, safe="")

    def _base_headers(self, *, correlation_id: str) -> dict[str, str]:
        if not self._service_auth:
            raise PersistenceContractError(
                "GPM_SERVICE_AUTH_MISCONFIGURED", correlation_id=correlation_id
            )
        return {
            "X-Service-Auth": self._service_auth,
            "X-GPM-Contract-Version": self.contract_version,
            "X-AIVAN-Correlation-ID": correlation_id,
        }

    def _service_headers(
        self, tenant_id: str | None, *, correlation_id: str = "gpm-adapter"
    ) -> dict[str, str]:
        correlation_id = self._correlation(correlation_id)
        normalized_tenant = (tenant_id or "").strip()
        if not normalized_tenant:
            raise PersistenceContractError(
                "GPM_TENANT_REQUIRED", correlation_id=correlation_id
            )
        return {
            **self._base_headers(correlation_id=correlation_id),
            "X-Service-Tenant-ID": normalized_tenant,
        }

    def _transport_error(
        self, operation: str, exc: Exception, *, correlation_id: str
    ) -> GiraffeDBClientError:
        log_exception_safely(
            logger,
            "GPM persistence adapter request failed",
            exc=exc,
            context={"operation": operation, "correlation_id": correlation_id},
        )
        status_code = (
            exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        )
        return GiraffeDBClientError(
            "GPM_ADAPTER_UNAVAILABLE",
            status_code=status_code,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _json(response: httpx.Response, *, correlation_id: str) -> dict[str, Any]:
        try:
            value = response.json()
        except Exception as exc:
            raise PersistenceContractError(
                "GPM_ADAPTER_INVALID_RESPONSE", correlation_id=correlation_id
            ) from exc
        if not isinstance(value, dict):
            raise PersistenceContractError(
                "GPM_ADAPTER_INVALID_RESPONSE", correlation_id=correlation_id
            )
        return value

    def check_schema_version(self) -> dict[str, Any]:
        correlation_id = "gpm-schema-probe"
        headers = self._base_headers(correlation_id=correlation_id)
        try:
            response = self._session.get(
                f"{self.base_url}/api/data/schema-version",
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            value = self._json(response, correlation_id=correlation_id)
        except PersistenceContractError:
            raise
        except Exception as exc:
            raise self._transport_error(
                "check_schema_version", exc, correlation_id=correlation_id
            ) from exc
        reported = value.get("gpm_contract_version") or value.get("contract_version")
        if reported != self.contract_version:
            raise PersistenceContractError(
                "GPM_CONTRACT_VERSION_MISMATCH", correlation_id=correlation_id
            )
        return value

    def get_tenant(
        self, tenant_id: str, *, correlation_id: str = "gpm-tenant-check"
    ) -> dict[str, Any] | None:
        correlation_id = self._correlation(correlation_id)
        headers = self._service_headers(tenant_id, correlation_id=correlation_id)
        tenant_path = self._path_segment(tenant_id)
        try:
            response = self._session.get(
                f"{self.base_url}/api/data/tenants/{tenant_path}",
                headers=headers,
                timeout=self.timeout,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            value = self._json(response, correlation_id=correlation_id)
            return require_response_tenant(
                value, expected_tenant=tenant_id, correlation_id=correlation_id
            )
        except PersistenceContractError:
            raise
        except Exception as exc:
            raise self._transport_error(
                "get_tenant", exc, correlation_id=correlation_id
            ) from exc

    def create_packet(
        self,
        packet: dict[str, Any],
        tenant_id: str | None = None,
        *,
        correlation_id: str = "gpm-create",
    ) -> dict[str, Any]:
        correlation_id = self._correlation(correlation_id)
        headers = self._service_headers(tenant_id, correlation_id=correlation_id)
        if packet.get("tenant_id") != tenant_id:
            raise PersistenceContractError(
                "GPM_REQUEST_TENANT_MISMATCH", correlation_id=correlation_id
            )
        try:
            response = self._session.post(
                f"{self.base_url}/api/data/gpm/packets",
                json=packet,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            value = self._json(response, correlation_id=correlation_id)
            return require_response_tenant(
                value, expected_tenant=tenant_id or "", correlation_id=correlation_id
            )
        except PersistenceContractError:
            raise
        except Exception as exc:
            raise self._transport_error(
                "create_packet", exc, correlation_id=correlation_id
            ) from exc

    def get_packet(
        self,
        packet_id: str,
        tenant_id: str | None = None,
        *,
        correlation_id: str = "gpm-get",
    ) -> dict[str, Any] | None:
        correlation_id = self._correlation(correlation_id)
        headers = self._service_headers(tenant_id, correlation_id=correlation_id)
        packet_path = self._path_segment(packet_id)
        try:
            response = self._session.get(
                f"{self.base_url}/api/data/gpm/packets/{packet_path}",
                headers=headers,
                timeout=self.timeout,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            value = self._json(response, correlation_id=correlation_id)
            return require_response_tenant(
                value, expected_tenant=tenant_id or "", correlation_id=correlation_id
            )
        except PersistenceContractError:
            raise
        except Exception as exc:
            raise self._transport_error("get_packet", exc, correlation_id=correlation_id) from exc

    def list_packets(
        self,
        tenant_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        *,
        correlation_id: str = "gpm-list",
    ) -> list[dict[str, Any]]:
        correlation_id = self._correlation(correlation_id)
        headers = self._service_headers(tenant_id, correlation_id=correlation_id)
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        try:
            response = self._session.get(
                f"{self.base_url}/api/data/gpm/packets",
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            envelope = self._json(response, correlation_id=correlation_id)
            packets = envelope.get("packets")
            if not isinstance(packets, list) or not all(
                isinstance(item, dict) for item in packets
            ):
                raise PersistenceContractError(
                    "GPM_ADAPTER_INVALID_RESPONSE", correlation_id=correlation_id
                )
            return [
                require_response_tenant(
                    item,
                    expected_tenant=tenant_id or "",
                    correlation_id=correlation_id,
                )
                for item in packets
            ]
        except PersistenceContractError:
            raise
        except Exception as exc:
            raise self._transport_error(
                "list_packets", exc, correlation_id=correlation_id
            ) from exc

    def apply_decision(self, command: DecisionCommand) -> dict[str, Any]:
        headers = self._service_headers(
            command.tenant_id, correlation_id=command.correlation_id
        )
        packet_path = self._path_segment(command.packet_id)
        body = {
            "approval_status": command.decision,
            "expected_status": command.expected_status,
            "operator_id": command.operator_id,
            "operator_role": command.operator_role,
            "authorization_basis": command.authorization_basis,
            "notes": command.notes,
            "idempotency_key": command.idempotency_key,
            "correlation_id": command.correlation_id,
            "contract_version": command.contract_version,
            "audit_required": True,
            "lineage_required": True,
            "dispatched": False,
        }
        try:
            response = self._session.patch(
                f"{self.base_url}/api/data/gpm/packets/{packet_path}",
                json=body,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            value = self._json(response, correlation_id=command.correlation_id)
            return require_atomic_decision_proof(value, command=command)
        except PersistenceContractError:
            raise
        except Exception as exc:
            raise self._transport_error(
                "apply_decision", exc, correlation_id=command.correlation_id
            ) from exc

    def update_packet_status(self, *args, **kwargs) -> dict[str, Any]:
        raise PersistenceContractError(
            "GPM_LEGACY_NONATOMIC_MUTATION_DISABLED",
            correlation_id="gpm-legacy-update",
        )

    def create_audit_record(self, *args, **kwargs) -> dict[str, Any]:
        raise PersistenceContractError(
            "GPM_LEGACY_NONATOMIC_AUDIT_DISABLED",
            correlation_id="gpm-legacy-audit",
        )
