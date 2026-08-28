"""Provider-neutral, versioned persistence contract for GPM G2-A.

This module defines the consumer-side boundary only.  It does not claim that a
real giraffe-db deployment implements the contract; unsupported or incomplete
responses fail closed until the corresponding giraffe-db Stage is accepted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from aivan.gpm.auth import GPMPrincipal


GPM_PERSISTENCE_CONTRACT_VERSION = "gpm.persistence.v1"
_SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")


class PersistenceContractError(RuntimeError):
    """Stable, redacted adapter error carrying only code and correlation ID."""

    def __init__(
        self,
        code: str,
        *,
        correlation_id: str,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.correlation_id = correlation_id
        self.status_code = status_code
        super().__init__(f"{code} correlation_id={correlation_id}")


def require_safe_correlation_id(value: str | None) -> str:
    normalized = (value or "gpm-adapter").strip() or "gpm-adapter"
    if not _SAFE_CORRELATION_ID.fullmatch(normalized):
        raise PersistenceContractError(
            "GPM_INVALID_CORRELATION_ID",
            correlation_id="gpm-invalid-correlation",
        )
    return normalized


@dataclass(frozen=True)
class DecisionCommand:
    packet_id: str
    tenant_id: str
    decision: str
    operator_id: str
    operator_role: str
    authorization_basis: str
    idempotency_key: str
    correlation_id: str
    notes: str | None = None
    expected_status: str = "pending"
    contract_version: str = GPM_PERSISTENCE_CONTRACT_VERSION

    @classmethod
    def from_principal(
        cls,
        *,
        packet_id: str,
        decision: str,
        principal: GPMPrincipal,
        notes: str | None = None,
    ) -> DecisionCommand:
        return cls(
            packet_id=packet_id,
            tenant_id=principal.tenant_id,
            decision=decision,
            operator_id=principal.actor_id,
            operator_role=principal.role,
            authorization_basis=principal.authorization_basis,
            idempotency_key=principal.idempotency_key,
            correlation_id=principal.correlation_id,
            notes=notes,
        )


def require_response_tenant(
    value: dict[str, Any], *, expected_tenant: str, correlation_id: str
) -> dict[str, Any]:
    if value.get("tenant_id") != expected_tenant:
        raise PersistenceContractError(
            "GPM_RESPONSE_TENANT_MISMATCH",
            correlation_id=correlation_id,
        )
    return value


def require_atomic_decision_proof(
    value: dict[str, Any], *, command: DecisionCommand
) -> dict[str, Any]:
    require_response_tenant(
        value,
        expected_tenant=command.tenant_id,
        correlation_id=command.correlation_id,
    )
    expected = {
        "packet_id": command.packet_id,
        "approval_status": command.decision,
        "operator_id": command.operator_id,
        "operator_role": command.operator_role,
        "authorization_basis": command.authorization_basis,
        "idempotency_key": command.idempotency_key,
        "transaction_status": "committed",
        "audit_recorded": True,
        "lineage_recorded": True,
        "contract_version": GPM_PERSISTENCE_CONTRACT_VERSION,
        "dispatched": False,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise PersistenceContractError(
            "GPM_ATOMIC_DECISION_UNPROVEN",
            correlation_id=command.correlation_id,
        )
    return value


@runtime_checkable
class PacketPersistenceAdapter(Protocol):
    """Neutral boundary required by GPMPacketStore.

    The HTTP giraffe-db client is one adapter.  Future accepted SDK providers
    may implement the same contract without changing GPM business code.
    """

    contract_version: str

    def check_schema_version(self) -> dict[str, Any]: ...

    def create_packet(
        self,
        packet: dict[str, Any],
        tenant_id: str | None = None,
        *,
        correlation_id: str = "gpm-create",
    ) -> dict[str, Any]: ...

    def get_packet(
        self,
        packet_id: str,
        tenant_id: str | None = None,
        *,
        correlation_id: str = "gpm-get",
    ) -> dict[str, Any] | None: ...

    def list_packets(
        self,
        tenant_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        *,
        correlation_id: str = "gpm-list",
    ) -> list[dict[str, Any]]: ...

    def apply_decision(self, command: DecisionCommand) -> dict[str, Any]: ...
