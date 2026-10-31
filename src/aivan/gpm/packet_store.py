"""Tenant-bound GPM packet persistence with a fail-closed production boundary.

Reads and creates use the versioned provider-neutral adapter. Approval and
rejection use ``decide()`` so status, audit, lineage, and idempotency are one
adapter transaction. Legacy split mutation helpers remain only for old local
callers; the production HTTP adapter rejects them. Memory compatibility is
non-production only and never establishes durable integration evidence.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from typing import Optional

from fastapi import HTTPException

from aivan.gpm.auth import GPMPrincipal, authorize_gpm_decision
from aivan.gpm.giraffe_db_client import GPM_PACKET_API_VERSION, REQUIRED_PACKET_CAPABILITIES
from aivan.gpm.persistence_contract import (
    GPM_PERSISTENCE_CONTRACT_VERSION,
    DecisionCommand,
    PacketPersistenceAdapter,
    PersistenceContractError,
    require_atomic_decision_proof,
)

logger = logging.getLogger(__name__)


def _is_production() -> bool:
    return os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"


def _raise_production_unavailable(exc: Exception | None = None) -> None:
    if _is_production():
        correlation_id = (
            exc.correlation_id
            if isinstance(exc, PersistenceContractError)
            else "gpm-persistence"
        )
        raise HTTPException(
            status_code=503,
            detail={
                "error": "GPM_PERSISTENCE_UNAVAILABLE",
                "message": "production GPM durable persistence is unavailable",
                "correlation_id": correlation_id,
            },
        ) from exc


def _redact_adapter_error(
    exc: Exception, *, correlation_id: str
) -> PersistenceContractError:
    if isinstance(exc, PersistenceContractError):
        return exc
    logger.error(
        "GPM persistence adapter failed exception_type=%s correlation_id=%s",
        type(exc).__name__,
        correlation_id,
    )
    return PersistenceContractError(
        "GPM_ADAPTER_UNAVAILABLE",
        correlation_id=correlation_id,
    )


class GPMPacketStore:
    def __init__(self, db_client: Optional[PacketPersistenceAdapter] = None) -> None:
        self._mem: dict[str, dict] = {}
        self._db = db_client
        self._durable = False
        self._legacy_durable = False
        self._verified_tenants: set[str] = set()
        self._decision_lock = threading.RLock()
        self._decision_receipts: dict[tuple[str, str], dict] = {}

        if (self._db is not None
                and getattr(self._db, "contract_version", None) == GPM_PERSISTENCE_CONTRACT_VERSION
                and getattr(self._db, "packet_api_version", None) != GPM_PACKET_API_VERSION):
            try:
                version_info = self._db.check_schema_version()
                reported_version = (
                    version_info.get("gpm_contract_version")
                    or version_info.get("contract_version")
                )
                if (
                    getattr(self._db, "contract_version", None)
                    != GPM_PERSISTENCE_CONTRACT_VERSION
                    or reported_version != GPM_PERSISTENCE_CONTRACT_VERSION
                ):
                    raise PersistenceContractError(
                        "GPM_CONTRACT_VERSION_MISMATCH",
                        correlation_id="gpm-schema-probe",
                    )
                self._durable = True
                self._legacy_durable = True
                logger.info("GPMPacketStore: giraffe-db available — durable mode")
            except Exception as exc:
                logger.warning(
                    "GPMPacketStore: giraffe-db unavailable exception_type=%s — "
                    "local in-memory fallback; packets will not survive restart",
                    type(exc).__name__,
                )
        elif self._db is None:
            logger.warning(
                "GPMPacketStore: no db_client — in-memory only. "
                "Set GIRAFFE_DB_BASE_URL to enable persistence."
            )

    def ensure_tenant_ready(
        self, tenant_id: str, *, correlation_id: str | None = None, force_probe: bool = False,
    ) -> bool:
        from aivan.gpm.persistence_contract import require_safe_correlation_id

        correlation_id = require_safe_correlation_id(correlation_id or "gpm-tenant-probe")
        if not isinstance(tenant_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,254}", tenant_id):
            raise PersistenceContractError("GPM_TENANT_REQUIRED", correlation_id=correlation_id)
        if self._db is None:
            self._verified_tenants.clear()
            self._durable = False
            _raise_production_unavailable()
            return False
        if self._legacy_durable:
            if not force_probe:
                return True
            try:
                version = self._db.check_schema_version()
                if (version.get("gpm_contract_version") or version.get("contract_version")) != GPM_PERSISTENCE_CONTRACT_VERSION:
                    raise PersistenceContractError("GPM_CONTRACT_VERSION_MISMATCH", correlation_id=correlation_id)
                return True
            except Exception as exc:
                self._durable = False
                self._legacy_durable = False
                _raise_production_unavailable(_redact_adapter_error(exc, correlation_id=correlation_id))
                return False
        if tenant_id in self._verified_tenants and not force_probe:
            return True
        try:
            schema_probe = getattr(self._db, "check_schema_version")
            capability_probe = getattr(self._db, "check_packet_capabilities")
            schema = schema_probe(tenant_id=tenant_id, correlation_id=correlation_id)
            capabilities = capability_probe(tenant_id, correlation_id=correlation_id)
            flags = capabilities.get("capabilities") if isinstance(capabilities, dict) else None
            if (not isinstance(schema, dict) or not isinstance(schema.get("schema_version"), str)
                    or not schema["schema_version"]
                    or not isinstance(capabilities, dict)
                    or capabilities.get("api_version") != GPM_PACKET_API_VERSION
                    or not isinstance(flags, dict)
                    or any(flags.get(name) is not True for name in REQUIRED_PACKET_CAPABILITIES)):
                raise PersistenceContractError("GPM_PACKET_CAPABILITY_MISMATCH", correlation_id=correlation_id)
        except Exception as exc:
            self._verified_tenants.discard(tenant_id)
            self._durable = bool(self._verified_tenants)
            _raise_production_unavailable(_redact_adapter_error(exc, correlation_id=correlation_id))
            return False
        self._verified_tenants.add(tenant_id)
        self._durable = True
        return True

    # ── public API ─────────────────────────────────────────────────────────

    def _remember(self, packet_id: str, packet: dict) -> None:
        """Cache only outside production to avoid a redundant unbounded copy."""

        if not _is_production():
            self._mem[packet_id] = packet

    def save(
        self, packet: dict, *, tenant_id: str | None = None,
        correlation_id: str = "gpm-create", idempotency_key: str | None = None,
    ) -> dict:
        pid = packet["packet_id"]
        packet_tenant = packet.get("tenant_id")
        if not isinstance(packet_tenant, str) or not packet_tenant or (
                tenant_id is not None and tenant_id != packet_tenant):
            raise HTTPException(status_code=422, detail={"error": "GPM_PACKET_TENANT_REQUIRED"})
        if _is_production() and not tenant_id:
            # Never substitute packet identity for the authenticated caller.
            # Preserve the versioned legacy adapter's explicit None rejection;
            # the HTTP adapter itself rejects it before network I/O.
            if self._legacy_durable and self._db is not None:
                try:
                    self._db.create_packet(packet, tenant_id=None, correlation_id=correlation_id)
                except Exception as exc:
                    _raise_production_unavailable(_redact_adapter_error(exc, correlation_id=correlation_id))
                raise HTTPException(status_code=503, detail={
                    "error": "GPM_PERSISTENCE_OUTCOME_UNKNOWN", "packet_id": pid,
                })
            _raise_production_unavailable()
        tenant_id = packet_tenant
        if self.ensure_tenant_ready(tenant_id, correlation_id=correlation_id):
            assert self._db is not None
            arguments = {"tenant_id": tenant_id, "correlation_id": correlation_id}
            if idempotency_key:
                arguments["idempotency_key"] = idempotency_key
            error = None
            try:
                self._db.create_packet(packet, **arguments)
            except Exception as exc:
                error = _redact_adapter_error(exc, correlation_id=correlation_id)
            try:
                saved = self._db.get_packet(pid, tenant_id=tenant_id, correlation_id=correlation_id)
            except Exception as exc:
                error = _redact_adapter_error(exc, correlation_id=correlation_id)
                saved = None
            if isinstance(saved, dict) and all(saved.get(k) == v for k, v in packet.items()):
                self._remember(pid, saved)
                return saved
            if error is not None and error.status_code == 409:
                raise HTTPException(status_code=409, detail={"error": "GPM_IDEMPOTENCY_CONFLICT", "packet_id": pid}) from error
            if _is_production():
                raise HTTPException(status_code=503, detail={
                    "error": "GPM_PERSISTENCE_OUTCOME_UNKNOWN", "packet_id": pid,
                }) from error
        _raise_production_unavailable()
        self._mem[pid] = packet
        return packet

    def get(
        self,
        packet_id: str,
        tenant_id: str | None = None,
        *,
        correlation_id: str = "gpm-get",
    ) -> Optional[dict]:
        cached = None if _is_production() else self._mem.get(packet_id)
        if cached is not None:
            # Enforce tenant isolation in memory — never return another tenant's packet.
            if tenant_id is not None and cached.get("tenant_id") != tenant_id:
                return None
            return cached
        if tenant_id is not None:
            self.ensure_tenant_ready(tenant_id, correlation_id=correlation_id)
        if self._durable:
            assert self._db is not None
            try:
                row = self._db.get_packet(
                    packet_id,
                    tenant_id=tenant_id,
                    correlation_id=correlation_id,
                )
                if row:
                    self._remember(packet_id, row)
                return row
            except Exception as exc:
                adapter_error = _redact_adapter_error(
                    exc, correlation_id=correlation_id
                )
                _raise_production_unavailable(adapter_error)
                logger.warning("GPMPacketStore.get: giraffe-db read failed")
        _raise_production_unavailable()
        return None

    def update_status(
        self,
        packet_id: str,
        approval_status: str,
        operator_id: str,
        notes: Optional[str] = None,
        tenant_id: str | None = None,
    ) -> Optional[dict]:
        if self._durable:
            assert self._db is not None
            try:
                legacy_update = getattr(self._db, "update_packet_status", None)
                if not callable(legacy_update):
                    raise PersistenceContractError(
                        "GPM_LEGACY_NONATOMIC_MUTATION_DISABLED",
                        correlation_id="gpm-legacy-update",
                    )
                updated = legacy_update(
                    packet_id, approval_status, operator_id, notes, tenant_id=tenant_id
                )
                self._remember(packet_id, updated)
                return updated
            except Exception as exc:
                adapter_error = _redact_adapter_error(
                    exc, correlation_id="gpm-legacy-update"
                )
                _raise_production_unavailable(adapter_error)
                logger.warning("GPMPacketStore.update_status: giraffe-db failed — memory only")

        _raise_production_unavailable()
        if packet_id in self._mem:
            packet = self._mem[packet_id]
            if tenant_id is not None and packet.get("tenant_id") != tenant_id:
                return None
            self._mem[packet_id].update({
                "approval_status": approval_status,
                "operator_id": operator_id,
                **(({"notes": notes}) if notes else {}),
            })
            return self._mem[packet_id]
        return None

    def write_audit(
        self,
        packet_id: str,
        operator_id: str,
        action: str,
        notes: Optional[str] = None,
        tenant_id: str = "default",
    ) -> bool:
        """Write audit record to giraffe-db only. Returns False on failure without raising."""
        if self._durable:
            assert self._db is not None
            try:
                legacy_audit = getattr(self._db, "create_audit_record", None)
                if not callable(legacy_audit):
                    raise PersistenceContractError(
                        "GPM_LEGACY_NONATOMIC_AUDIT_DISABLED",
                        correlation_id="gpm-legacy-audit",
                    )
                legacy_audit(packet_id, operator_id, action, notes, tenant_id)
                return True
            except Exception as exc:
                adapter_error = _redact_adapter_error(
                    exc, correlation_id="gpm-legacy-audit"
                )
                _raise_production_unavailable(adapter_error)
                logger.warning("GPMPacketStore.write_audit: failed")
        _raise_production_unavailable()
        return False

    def list_by_tenant(
        self,
        tenant_id: str = "default",
        status: Optional[str] = None,
        *,
        correlation_id: str = "gpm-list",
    ) -> list[dict]:
        if self._durable:
            assert self._db is not None
            try:
                return self._db.list_packets(
                    tenant_id=tenant_id,
                    status=status,
                    correlation_id=correlation_id,
                )
            except Exception as exc:
                adapter_error = _redact_adapter_error(
                    exc, correlation_id=correlation_id
                )
                _raise_production_unavailable(adapter_error)
                logger.warning("GPMPacketStore.list_by_tenant: giraffe-db failed — memory fallback")
        _raise_production_unavailable()
        return [
            p for p in self._mem.values()
            if p.get("tenant_id") == tenant_id
            and (status is None or p.get("approval_status") == status)
        ]

    @property
    def is_durable(self) -> bool:
        return self._durable

    def decide(
        self,
        packet_id: str,
        decision: str,
        *,
        principal: GPMPrincipal,
        notes: str | None = None,
    ) -> dict:
        """Atomically apply one authenticated, idempotent decision.

        The production adapter must return explicit transaction, audit, lineage,
        tenant, and idempotency proof. Local compatibility uses one lock and one
        in-memory receipt; it is never a production persistence fallback.
        """

        authorize_gpm_decision(principal)
        if decision not in {"approved", "rejected"}:
            raise PersistenceContractError(
                "GPM_INVALID_DECISION",
                correlation_id=principal.correlation_id,
            )
        receipt_key = (principal.tenant_id, principal.idempotency_key)
        command = DecisionCommand.from_principal(
            packet_id=packet_id,
            decision=decision,
            principal=principal,
            notes=notes,
        )
        with self._decision_lock:
            existing = self._decision_receipts.get(receipt_key)
            if existing is not None:
                if (
                    existing.get("packet_id") != packet_id
                    or existing.get("approval_status") != decision
                    or existing.get("operator_id") != principal.actor_id
                    or existing.get("operator_role") != principal.role
                    or existing.get("authorization_basis")
                    != principal.authorization_basis
                ):
                    raise PersistenceContractError(
                        "GPM_IDEMPOTENCY_CONFLICT",
                        correlation_id=principal.correlation_id,
                    )
                return dict(existing)

            if self._durable:
                assert self._db is not None
                try:
                    updated = self._db.apply_decision(command)
                    require_atomic_decision_proof(updated, command=command)
                    self._remember(packet_id, dict(updated))
                except Exception as exc:
                    raise _redact_adapter_error(
                        exc, correlation_id=principal.correlation_id
                    ) from exc
            else:
                _raise_production_unavailable()
                packet = self._mem.get(packet_id)
                if packet is None or packet.get("tenant_id") != principal.tenant_id:
                    raise PersistenceContractError(
                        "GPM_PACKET_NOT_FOUND",
                        correlation_id=principal.correlation_id,
                    )
                if packet.get("approval_status") != "pending":
                    raise PersistenceContractError(
                        "GPM_ALREADY_DECIDED",
                        correlation_id=principal.correlation_id,
                    )
                updated = {
                    **packet,
                    "approval_status": decision,
                    "operator_id": principal.actor_id,
                    "operator_role": principal.role,
                    "authorization_basis": principal.authorization_basis,
                    "idempotency_key": principal.idempotency_key,
                    "correlation_id": principal.correlation_id,
                    "transaction_status": "committed",
                    "audit_recorded": True,
                    "lineage_recorded": True,
                    "contract_version": command.contract_version,
                    "dispatched": False,
                    **({"notes": notes} if notes else {}),
                }
                self._mem[packet_id] = updated
            self._decision_receipts[receipt_key] = dict(updated)
            return dict(updated)

