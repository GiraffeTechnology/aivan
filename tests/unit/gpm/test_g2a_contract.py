"""GPM G2-A tenant, identity, and atomic decision contract tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aivan.gpm import router as gpm_router
from aivan.gpm.auth import GPMPrincipal, authorize_gpm_decision, generate_token
from aivan.gpm.giraffe_db_client import GiraffeDBClient
from aivan.gpm.packet_store import GPMPacketStore
from aivan.gpm.persistence_contract import (
    GPM_PERSISTENCE_CONTRACT_VERSION,
    DecisionCommand,
    PersistenceContractError,
)
from aivan.gpm.router import ApprovalRequest


def _response(body: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json=body,
        request=httpx.Request("GET", "https://db.invalid/resource"),
    )


def _client(monkeypatch, *, secret: str = "service-secret") -> GiraffeDBClient:
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", secret)
    return GiraffeDBClient("https://db.invalid")


def _principal(
    *,
    tenant_id: str = "tenant-a",
    actor_id: str = "operator-1",
    role: str = "approver",
    idempotency_key: str = "decision-001",
    correlation_id: str = "trace-001",
) -> GPMPrincipal:
    return GPMPrincipal(
        tenant_id=tenant_id,
        actor_id=actor_id,
        role=role,
        authorization_basis="tenant_api_key",
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


def test_tenant_bound_operation_requires_service_secret_and_explicit_tenant(monkeypatch):
    client = _client(monkeypatch, secret="")
    packet = {"packet_id": "gpm_pkt_1", "tenant_id": "body-tenant"}

    with pytest.raises(PersistenceContractError) as missing_secret:
        client.create_packet(packet, tenant_id="tenant-a", correlation_id="trace-1")
    assert missing_secret.value.code == "GPM_SERVICE_AUTH_MISCONFIGURED"
    assert missing_secret.value.correlation_id == "trace-1"

    client = _client(monkeypatch)
    with pytest.raises(PersistenceContractError) as inferred_body:
        client.create_packet(packet, tenant_id=None, correlation_id="trace-2")
    assert inferred_body.value.code == "GPM_TENANT_REQUIRED"
    assert inferred_body.value.correlation_id == "trace-2"


@pytest.mark.parametrize("method", ["create", "get", "list"])
def test_adapter_rejects_cross_tenant_responses(monkeypatch, method):
    client = _client(monkeypatch)
    client._session = MagicMock()
    foreign = {"packet_id": "gpm_pkt_1", "tenant_id": "tenant-b"}

    if method == "create":
        client._session.post.return_value = _response(foreign, 201)
        call = lambda: client.create_packet(
            {**foreign, "tenant_id": "tenant-a"},
            tenant_id="tenant-a",
            correlation_id="trace-cross",
        )
    elif method == "get":
        client._session.get.return_value = _response(foreign)
        call = lambda: client.get_packet(
            "gpm_pkt_1", tenant_id="tenant-a", correlation_id="trace-cross"
        )
    else:
        client._session.get.return_value = _response({"packets": [foreign]})
        call = lambda: client.list_packets(
            tenant_id="tenant-a", correlation_id="trace-cross"
        )

    with pytest.raises(PersistenceContractError) as exc_info:
        call()
    assert exc_info.value.code == "GPM_RESPONSE_TENANT_MISMATCH"
    assert exc_info.value.correlation_id == "trace-cross"
    assert "tenant-b" not in str(exc_info.value)


def test_transport_errors_are_redacted_and_correlation_bound(monkeypatch):
    client = _client(monkeypatch)
    client._session = MagicMock()
    client._session.get.side_effect = httpx.ConnectError(
        "secret-token leaked by transport https://db.invalid/private"
    )

    with pytest.raises(PersistenceContractError) as exc_info:
        client.get_packet(
            "gpm_pkt_1", tenant_id="tenant-a", correlation_id="trace-redacted"
        )

    assert exc_info.value.code == "GPM_ADAPTER_UNAVAILABLE"
    assert exc_info.value.correlation_id == "trace-redacted"
    assert "secret-token" not in str(exc_info.value)
    assert "db.invalid" not in str(exc_info.value)


def test_adapter_rejects_unsafe_correlation_id_before_transport(monkeypatch):
    client = _client(monkeypatch)
    client._session = MagicMock()

    with pytest.raises(PersistenceContractError) as exc_info:
        client.get_packet(
            "gpm_pkt_1",
            tenant_id="tenant-a",
            correlation_id="trace-ok\nforged-log=true",
        )

    assert exc_info.value.code == "GPM_INVALID_CORRELATION_ID"
    client._session.get.assert_not_called()


def test_tenant_and_packet_ids_are_encoded_as_single_path_segments(monkeypatch):
    client = _client(monkeypatch)
    client._session = MagicMock()
    client._session.get.return_value = _response(
        {"tenant_id": "tenant/a", "status": "active"}
    )

    client.get_tenant("tenant/a", correlation_id="trace-path")
    tenant_url = client._session.get.call_args.args[0]
    assert tenant_url.endswith("/tenants/tenant%2Fa")

    command = DecisionCommand.from_principal(
        packet_id="gpm_pkt/a",
        decision="approved",
        principal=_principal(tenant_id="tenant/a"),
    )
    client._session.patch.return_value = _response(
        {
            "packet_id": "gpm_pkt/a",
            "tenant_id": "tenant/a",
            "approval_status": "approved",
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
    )
    client.apply_decision(command)
    packet_url = client._session.patch.call_args.args[0]
    assert packet_url.endswith("/packets/gpm_pkt%2Fa")


def test_approval_body_cannot_supply_operator_identity():
    ApprovalRequest(notes="reviewed")
    with pytest.raises(ValidationError):
        ApprovalRequest(operator_id="body-attacker", notes="reviewed")


def test_only_authenticated_authorized_operator_can_decide():
    identity = authorize_gpm_decision(_principal())
    assert identity.actor_id == "operator-1"

    with pytest.raises(PermissionError):
        authorize_gpm_decision(_principal(role="auditor"))

    with pytest.raises(PermissionError):
        authorize_gpm_decision(_principal(actor_id=""))


class _AtomicAdapter:
    contract_version = GPM_PERSISTENCE_CONTRACT_VERSION

    def __init__(self) -> None:
        self.calls: list[DecisionCommand] = []
        self.packet = {
            "packet_id": "gpm_pkt_1",
            "tenant_id": "tenant-a",
            "approval_status": "pending",
            "dispatched": False,
        }

    def check_schema_version(self):
        return {
            "contract_version": GPM_PERSISTENCE_CONTRACT_VERSION,
            "provider": "test-adapter",
        }

    def get_packet(self, packet_id, *, tenant_id, correlation_id):
        assert tenant_id == "tenant-a"
        return dict(self.packet)

    def apply_decision(self, command: DecisionCommand):
        self.calls.append(command)
        self.packet = {
            **self.packet,
            "approval_status": command.decision,
            "operator_id": command.operator_id,
            "operator_role": command.operator_role,
            "authorization_basis": command.authorization_basis,
            "idempotency_key": command.idempotency_key,
            "transaction_status": "committed",
            "audit_recorded": True,
            "lineage_recorded": True,
            "contract_version": GPM_PERSISTENCE_CONTRACT_VERSION,
        }
        return dict(self.packet)


class _TenantProbeAdapter(_AtomicAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.create_tenants: list[str | None] = []

    def create_packet(self, packet, tenant_id=None, *, correlation_id):
        self.create_tenants.append(tenant_id)
        if tenant_id is not None:
            raise AssertionError("durable store inferred tenant from packet body")
        raise PersistenceContractError(
            "GPM_TENANT_REQUIRED", correlation_id=correlation_id
        )


class _ExplodingDecisionAdapter(_AtomicAdapter):
    def apply_decision(self, command: DecisionCommand):
        raise RuntimeError("remote response leaked secret-token")


def test_store_decision_is_idempotent_and_concurrency_serialized(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "production")
    adapter = _AtomicAdapter()
    store = GPMPacketStore(db_client=adapter)
    principal = _principal()

    def decide():
        return store.decide(
            "gpm_pkt_1", "approved", principal=principal, notes="ok"
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: decide(), range(4)))

    assert len(adapter.calls) == 1
    assert {item["approval_status"] for item in results} == {"approved"}
    assert {item["idempotency_key"] for item in results} == {"decision-001"}
    assert all(item["audit_recorded"] is True for item in results)
    assert all(item["lineage_recorded"] is True for item in results)
    assert all(item["dispatched"] is False for item in results)


def test_idempotency_key_cannot_be_reused_by_another_operator(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "production")
    adapter = _AtomicAdapter()
    store = GPMPacketStore(db_client=adapter)
    first = _principal(actor_id="operator-1")
    replay_as_other_actor = _principal(actor_id="operator-2")

    store.decide("gpm_pkt_1", "approved", principal=first)
    with pytest.raises(PersistenceContractError) as exc_info:
        store.decide(
            "gpm_pkt_1", "approved", principal=replay_as_other_actor
        )

    assert exc_info.value.code == "GPM_IDEMPOTENCY_CONFLICT"
    assert len(adapter.calls) == 1


def test_provider_exception_is_redacted_at_store_boundary(monkeypatch, caplog):
    monkeypatch.setenv("AIVAN_ENV", "production")
    store = GPMPacketStore(db_client=_ExplodingDecisionAdapter())

    with pytest.raises(PersistenceContractError) as exc_info:
        store.decide("gpm_pkt_1", "approved", principal=_principal())

    assert exc_info.value.code == "GPM_ADAPTER_UNAVAILABLE"
    assert exc_info.value.correlation_id == "trace-001"
    assert "secret-token" not in str(exc_info.value)
    assert "secret-token" not in caplog.text


def test_unversioned_adapter_never_becomes_production_durable(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "production")
    adapter = MagicMock()
    adapter.contract_version = "legacy-unversioned"
    adapter.check_schema_version.return_value = {"schema_version": "0.1.0"}
    store = GPMPacketStore(db_client=adapter)

    assert store.is_durable is False
    with pytest.raises(HTTPException) as exc_info:
        store.save(
            {"packet_id": "gpm_pkt_legacy", "tenant_id": "tenant-a"},
            tenant_id="tenant-a",
            correlation_id="trace-version",
        )
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["error"] == "GPM_PERSISTENCE_UNAVAILABLE"


def test_durable_store_never_infers_tenant_identity_from_packet_body(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "production")
    adapter = _TenantProbeAdapter()
    store = GPMPacketStore(db_client=adapter)

    with pytest.raises(HTTPException) as exc_info:
        store.save(
            {"packet_id": "gpm_pkt_body", "tenant_id": "body-tenant"},
            correlation_id="trace-body-tenant",
        )

    assert exc_info.value.status_code == 503
    assert adapter.create_tenants == [None]


def test_adapter_requires_atomic_transaction_proof(monkeypatch):
    client = _client(monkeypatch)
    client._session = MagicMock()
    client._session.patch.return_value = _response(
        {
            "packet_id": "gpm_pkt_1",
            "tenant_id": "tenant-a",
            "approval_status": "approved",
            "operator_id": "operator-1",
            "dispatched": False,
        }
    )
    command = DecisionCommand.from_principal(
        packet_id="gpm_pkt_1",
        decision="approved",
        principal=_principal(),
        notes="ok",
    )

    with pytest.raises(PersistenceContractError) as exc_info:
        client.apply_decision(command)
    assert exc_info.value.code == "GPM_ATOMIC_DECISION_UNPROVEN"
    assert exc_info.value.correlation_id == "trace-001"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("packet_id", "gpm_pkt_other"),
        ("operator_role", "admin"),
        ("authorization_basis", "body_claim"),
    ],
)
def test_atomic_proof_binds_packet_and_authenticated_authorization(
    monkeypatch, field, value
):
    client = _client(monkeypatch)
    client._session = MagicMock()
    command = DecisionCommand.from_principal(
        packet_id="gpm_pkt_1",
        decision="approved",
        principal=_principal(),
    )
    receipt = {
        "packet_id": command.packet_id,
        "tenant_id": command.tenant_id,
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
    receipt[field] = value
    client._session.patch.return_value = _response(receipt)

    with pytest.raises(PersistenceContractError) as exc_info:
        client.apply_decision(command)

    assert exc_info.value.code == "GPM_ATOMIC_DECISION_UNPROVEN"


@pytest.fixture()
def decision_api(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("AIVAN_AUTH_SECRET", "route-secret")
    store = GPMPacketStore(db_client=None)
    packet = {
        "packet_id": "gpm_pkt_route",
        "tenant_id": "tenant-a",
        "approval_status": "pending",
        "dispatched": False,
    }
    store.save(packet)
    gpm_router._reset_store(store)
    app = FastAPI()
    app.state.giraffe_db_client = None
    app.include_router(gpm_router.router, prefix="/api/gpm")
    with TestClient(app) as client:
        yield client


def _decision_headers(*, tenant_id="tenant-a", actor_id="operator-1", role="approver"):
    token = generate_token(tenant_id, "route-secret")
    return {
        "Authorization": f"Bearer {token}",
        "X-AIVAN-Actor-ID": actor_id,
        "X-AIVAN-Role-Context": role,
        "Idempotency-Key": "route-decision-1",
        "X-AIVAN-Trace-ID": "trace-route-1",
    }


def test_decision_route_uses_authenticated_operator_and_is_idempotent(decision_api):
    first = decision_api.post(
        "/api/gpm/quote-guidance/gpm_pkt_route/approve",
        headers=_decision_headers(),
        json={"notes": "approved"},
    )
    repeated = decision_api.post(
        "/api/gpm/quote-guidance/gpm_pkt_route/approve",
        headers=_decision_headers(),
        json={"notes": "ignored on idempotent replay"},
    )

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert first.json() == repeated.json()
    assert first.json()["operator_id"] == "operator-1"
    assert first.json()["operator_role"] == "approver"
    assert first.json()["audit_recorded"] is True
    assert first.json()["lineage_recorded"] is True
    assert first.json()["dispatched"] is False


def test_decision_route_rejects_body_operator_missing_actor_and_cross_tenant(decision_api):
    body_identity = decision_api.post(
        "/api/gpm/quote-guidance/gpm_pkt_route/approve",
        headers=_decision_headers(),
        json={"operator_id": "body-attacker"},
    )
    missing_actor = decision_api.post(
        "/api/gpm/quote-guidance/gpm_pkt_route/approve",
        headers=_decision_headers(actor_id=""),
        json={},
    )
    cross_tenant = decision_api.post(
        "/api/gpm/quote-guidance/gpm_pkt_route/approve",
        headers=_decision_headers(tenant_id="tenant-b"),
        json={},
    )

    assert body_identity.status_code == 422
    assert missing_actor.status_code == 403
    assert missing_actor.json()["detail"] == {
        "error": "GPM_OPERATOR_ID_REQUIRED",
        "correlation_id": "trace-route-1",
    }
    assert cross_tenant.status_code == 404
    assert cross_tenant.json()["detail"] == {
        "error": "GPM_PACKET_NOT_FOUND",
        "correlation_id": "trace-route-1",
    }
