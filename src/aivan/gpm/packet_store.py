"""Tenant-scoped GPM packet persistence with provider readback proof."""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import HTTPException

from aivan.gpm.giraffe_db_client import GiraffeDBClient, GiraffeDBClientError

logger = logging.getLogger(__name__)


def _is_production() -> bool:
    return os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"


def _raise_production_unavailable(exc: Exception | None = None) -> None:
    if _is_production():
        raise HTTPException(
            status_code=503,
            detail={
                "error": "GPM_PERSISTENCE_UNAVAILABLE",
                "message": "production GPM durable persistence is unavailable",
            },
        ) from exc


def _raise_outcome_unknown(packet_id: str, exc: Exception | None = None) -> None:
    raise HTTPException(
        status_code=503,
        detail={
            "error": "GPM_PERSISTENCE_OUTCOME_UNKNOWN",
            "packet_id": packet_id,
        },
    ) from exc


def _packet_matches(expected: dict, actual: dict | None) -> bool:
    if actual is None:
        return False
    return all(actual.get(key) == value for key, value in expected.items())


class GPMPacketStore:
    def __init__(self, db_client: Optional[GiraffeDBClient] = None) -> None:
        self._mem: dict[str, dict] = {}
        self._db = db_client
        self._verified_tenants: set[str] = set()

        if self._db is None:
            logger.warning(
                "GPMPacketStore: no db_client — in-memory only. "
                "Set GIRAFFE_DB_BASE_URL to enable persistence."
            )

    def ensure_tenant_ready(
        self,
        tenant_id: str,
        *,
        correlation_id: str | None = None,
        force_probe: bool = False,
    ) -> bool:
        if tenant_id in self._verified_tenants and not force_probe:
            return True
        if self._db is None:
            self._verified_tenants.discard(tenant_id)
            _raise_production_unavailable()
            return False
        try:
            self._db.check_schema_version(
                tenant_id=tenant_id,
                correlation_id=correlation_id,
            )
            self._db.check_packet_capabilities(
                tenant_id,
                correlation_id=correlation_id,
            )
        except GiraffeDBClientError as exc:
            self._verified_tenants.discard(tenant_id)
            _raise_production_unavailable(exc)
            logger.warning(
                "GPMPacketStore: provider probe failed error_code=%s",
                exc.error_code,
            )
            return False
        self._verified_tenants.add(tenant_id)
        return True

    def _remember(self, packet_id: str, packet: dict) -> None:
        if not _is_production():
            self._mem[packet_id] = packet

    def _readback(
        self,
        packet: dict,
        *,
        correlation_id: str | None,
    ) -> dict | None:
        assert self._db is not None
        return self._db.get_packet(
            packet["packet_id"],
            tenant_id=packet["tenant_id"],
            correlation_id=correlation_id,
        )

    def save(
        self,
        packet: dict,
        *,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict:
        packet_id = packet["packet_id"]
        tenant_id = packet.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id:
            raise HTTPException(
                status_code=422,
                detail={"error": "GPM_PACKET_TENANT_REQUIRED"},
            )

        if self.ensure_tenant_ready(
            tenant_id,
            correlation_id=correlation_id,
        ):
            assert self._db is not None
            create_error: GiraffeDBClientError | None = None
            created: dict | None = None
            try:
                created = self._db.create_packet(
                    packet,
                    tenant_id=tenant_id,
                    idempotency_key=idempotency_key,
                    correlation_id=correlation_id,
                )
            except GiraffeDBClientError as exc:
                create_error = exc

            try:
                readback = self._readback(
                    packet,
                    correlation_id=correlation_id,
                )
            except GiraffeDBClientError as exc:
                if _is_production():
                    _raise_outcome_unknown(packet_id, exc)
                logger.warning(
                    "GPMPacketStore.save: provider readback failed error_code=%s",
                    exc.error_code,
                )
                readback = None

            if _packet_matches(packet, readback):
                assert readback is not None
                self._remember(packet_id, readback)
                return readback

            if create_error is not None and create_error.status_code == 409:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "GPM_IDEMPOTENCY_CONFLICT",
                        "packet_id": packet_id,
                    },
                ) from create_error

            if _is_production() and (created is not None or create_error is not None):
                if create_error is None or create_error.status_code is None:
                    _raise_outcome_unknown(packet_id, create_error)
                _raise_production_unavailable(create_error)

            if create_error is not None:
                logger.warning(
                    "GPMPacketStore.save: provider write failed error_code=%s; "
                    "using development memory fallback",
                    create_error.error_code,
                )

        _raise_production_unavailable()
        self._mem[packet_id] = packet
        return packet

    def get(
        self,
        packet_id: str,
        tenant_id: str | None = None,
        *,
        correlation_id: str | None = None,
    ) -> Optional[dict]:
        cached = None if _is_production() else self._mem.get(packet_id)
        if cached is not None:
            if tenant_id is not None and cached.get("tenant_id") != tenant_id:
                return None
            return cached
        effective_tenant = tenant_id
        if effective_tenant is None and not _is_production():
            effective_tenant = os.environ.get("AIVAN_TENANT_ID", "").strip() or "default"
        if effective_tenant and self.ensure_tenant_ready(
            effective_tenant,
            correlation_id=correlation_id,
        ):
            assert self._db is not None
            try:
                row = self._db.get_packet(
                    packet_id,
                    tenant_id=effective_tenant,
                    correlation_id=correlation_id,
                )
                if row:
                    self._remember(packet_id, row)
                return row
            except GiraffeDBClientError as exc:
                if exc.status_code == 403:
                    raise HTTPException(
                        status_code=403,
                        detail={"error": "GPM_PACKET_ACCESS_DENIED"},
                    ) from exc
                _raise_production_unavailable(exc)
                logger.warning(
                    "GPMPacketStore.get: provider read failed error_code=%s",
                    exc.error_code,
                )
        _raise_production_unavailable()
        return None

    def update_status(
        self,
        packet_id: str,
        approval_status: str,
        operator_id: str,
        notes: Optional[str] = None,
        tenant_id: str | None = None,
        *,
        correlation_id: str | None = None,
    ) -> Optional[dict]:
        effective_tenant = tenant_id
        if effective_tenant is None and not _is_production():
            effective_tenant = os.environ.get("AIVAN_TENANT_ID", "").strip() or "default"
        if effective_tenant and self.ensure_tenant_ready(
            effective_tenant,
            correlation_id=correlation_id,
        ):
            assert self._db is not None
            try:
                updated = self._db.update_packet_status(
                    packet_id,
                    approval_status,
                    operator_id,
                    notes,
                    tenant_id=effective_tenant,
                    correlation_id=correlation_id,
                )
                self._remember(packet_id, updated)
                return updated
            except GiraffeDBClientError as exc:
                _raise_production_unavailable(exc)
                logger.warning(
                    "GPMPacketStore.update_status: provider failed error_code=%s",
                    exc.error_code,
                )

        _raise_production_unavailable()
        if packet_id in self._mem:
            packet = self._mem[packet_id]
            if tenant_id is not None and packet.get("tenant_id") != tenant_id:
                return None
            packet.update(
                {
                    "approval_status": approval_status,
                    "operator_id": operator_id,
                    **({"notes": notes} if notes else {}),
                }
            )
            return packet
        return None

    def write_audit(
        self,
        packet_id: str,
        operator_id: str,
        action: str,
        notes: Optional[str] = None,
        tenant_id: str = "default",
        *,
        correlation_id: str | None = None,
    ) -> bool:
        if self.ensure_tenant_ready(
            tenant_id,
            correlation_id=correlation_id,
        ):
            assert self._db is not None
            try:
                self._db.create_audit_record(
                    packet_id,
                    operator_id,
                    action,
                    notes,
                    tenant_id,
                    correlation_id=correlation_id,
                )
                return True
            except GiraffeDBClientError as exc:
                _raise_production_unavailable(exc)
                logger.warning(
                    "GPMPacketStore.write_audit: provider failed error_code=%s",
                    exc.error_code,
                )
        _raise_production_unavailable()
        return False

    def list_by_tenant(
        self,
        tenant_id: str = "default",
        status: Optional[str] = None,
        *,
        correlation_id: str | None = None,
    ) -> list[dict]:
        if self.ensure_tenant_ready(
            tenant_id,
            correlation_id=correlation_id,
        ):
            assert self._db is not None
            try:
                return self._db.list_packets(
                    tenant_id=tenant_id,
                    status=status,
                    correlation_id=correlation_id,
                )
            except GiraffeDBClientError as exc:
                _raise_production_unavailable(exc)
                logger.warning(
                    "GPMPacketStore.list_by_tenant: provider failed error_code=%s",
                    exc.error_code,
                )
        _raise_production_unavailable()
        return [
            packet
            for packet in self._mem.values()
            if packet.get("tenant_id") == tenant_id
            and (status is None or packet.get("approval_status") == status)
        ]

    @property
    def is_durable(self) -> bool:
        return bool(self._verified_tenants)
