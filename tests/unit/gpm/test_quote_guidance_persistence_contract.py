"""A10 regressions for the enabled Stage 1 quote-guidance persistence path."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from aivan.gpm.giraffe_db_client import GiraffeDBClient, GiraffeDBClientError
from aivan.gpm.packet_store import GPMPacketStore
from aivan.gpm.persistence_contract import GPM_PERSISTENCE_CONTRACT_VERSION, PersistenceContractError
from aivan.gpm.router import (
    _reset_store,
    require_gpm_principal,
    router,
)
from tests.unit.gpm.principal_fixture import principal_for_tenant


@pytest.fixture(autouse=True)
def synthetic_service_auth(monkeypatch):
    """Give this isolated provider fixture explicit, non-production credentials."""
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "synthetic-provider-service-secret")


TENANT = "tenant-a"
PACKET = {
    "packet_id": "gpm_pkt_contract001",
    "tenant_id": TENANT,
    "sku": "SKU-001",
    "supplier_id": "supplier-001",
    "supplier_quote": 12.5,
    "currency": "USD",
    "quantity": 10,
    "quote_position": "within_mid_range",
    "recommendation": "negotiate",
    "confidence": "low",
    "human_approval_required": True,
    "approval_status": "pending",
    "dispatched": False,
}


def _response(status: int, body: dict, method: str = "GET") -> httpx.Response:
    return httpx.Response(
        status,
        json=body,
        request=httpx.Request(method, "http://giraffe-db.test/api/data/test"),
    )


def test_schema_probe_sends_authenticated_tenant_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "service-secret")
    client = GiraffeDBClient("http://giraffe-db.test")
    with patch.object(
        client._session,
        "get",
        return_value=_response(200, {"schema_version": "0.2.0"}),
    ) as request:
        result = client.check_schema_version(tenant_id=TENANT, correlation_id="trace-001")

    assert result == {"schema_version": "0.2.0"}
    assert request.call_args.kwargs["headers"] == {
        "X-Service-Tenant-ID": TENANT,
        "X-Service-Auth": "service-secret",
        "X-AIVAN-Correlation-ID": "trace-001",
        "X-GPM-Contract-Version": GPM_PERSISTENCE_CONTRACT_VERSION,
    }


def test_packet_capability_probe_is_separate_from_database_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "service-secret")
    client = GiraffeDBClient("http://giraffe-db.test")
    body = {
        "api_version": "gpm.packet-persistence.v1",
        "capabilities": {
            "create_packet": True,
            "read_packet": True,
            "idempotent_create": True,
            "quote_lineage": True,
        },
    }
    with patch.object(client._session, "get", return_value=_response(200, body)) as request:
        assert client.check_packet_capabilities(TENANT, correlation_id="trace-002") == body

    assert str(request.call_args.args[0]).endswith("/api/data/gpm/capabilities")
    assert request.call_args.kwargs["headers"]["X-Service-Tenant-ID"] == TENANT
    assert request.call_args.kwargs["headers"]["X-Service-Auth"] == "service-secret"


def test_packet_capability_probe_rejects_label_only_provider() -> None:
    client = GiraffeDBClient("http://giraffe-db.test")
    incomplete = {
        "api_version": "gpm.packet-persistence.v1",
        "capabilities": {"create_packet": True, "read_packet": True},
    }
    with patch.object(client._session, "get", return_value=_response(200, incomplete)):
        with pytest.raises(GiraffeDBClientError) as exc_info:
            client.check_packet_capabilities(TENANT)

    assert exc_info.value.error_code == "GPM_PACKET_CAPABILITY_MISMATCH"


def test_create_transport_error_is_wrapped() -> None:
    client = GiraffeDBClient("http://giraffe-db.test")
    with patch.object(
        client._session,
        "post",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        with pytest.raises(GiraffeDBClientError) as exc_info:
            client.create_packet(
                PACKET,
                tenant_id=TENANT,
                idempotency_key="idem-001",
                correlation_id="trace-003",
            )

    assert exc_info.value.error_code == "GPM_ADAPTER_UNAVAILABLE"
    assert exc_info.value.status_code is None


def test_create_rejects_provider_tenant_mismatch() -> None:
    client = GiraffeDBClient("http://giraffe-db.test")
    wrong_tenant = {**PACKET, "tenant_id": "tenant-b"}
    with patch.object(
        client._session,
        "post",
        return_value=_response(201, wrong_tenant, method="POST"),
    ):
        with pytest.raises(PersistenceContractError) as exc_info:
            client.create_packet(PACKET, tenant_id=TENANT)

    assert exc_info.value.code == "GPM_RESPONSE_TENANT_MISMATCH"


def test_production_save_requires_provider_readback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIVAN_ENV", "production")
    db = MagicMock()
    db.check_schema_version.return_value = {"schema_version": "0.2.0"}
    db.check_packet_capabilities.return_value = {
        "api_version": "gpm.packet-persistence.v1",
        "capabilities": {
            "create_packet": True,
            "read_packet": True,
            "idempotent_create": True,
            "quote_lineage": True,
        },
    }
    db.create_packet.return_value = dict(PACKET)
    db.get_packet.return_value = dict(PACKET)
    store = GPMPacketStore(db_client=db)

    result = store.save(
        PACKET,
        tenant_id=TENANT,
        idempotency_key="idem-002",
        correlation_id="trace-004",
    )

    assert result == PACKET
    db.get_packet.assert_called_once_with(
        PACKET["packet_id"],
        tenant_id=TENANT,
        correlation_id="trace-004",
    )


def test_production_save_marks_possible_commit_unknown_when_readback_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIVAN_ENV", "production")
    db = MagicMock()
    db.check_schema_version.return_value = {"schema_version": "0.2.0"}
    db.check_packet_capabilities.return_value = {
        "api_version": "gpm.packet-persistence.v1",
        "capabilities": {
            "create_packet": True,
            "read_packet": True,
            "idempotent_create": True,
            "quote_lineage": True,
        },
    }
    db.create_packet.return_value = dict(PACKET)
    db.get_packet.side_effect = GiraffeDBClientError(
        "readback unavailable",
        error_code="GPM_DB_TRANSPORT_ERROR",
    )
    store = GPMPacketStore(db_client=db)

    with pytest.raises(HTTPException) as exc_info:
        store.save(
            PACKET,
            tenant_id=TENANT,
            idempotency_key="idem-003",
            correlation_id="trace-005",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {
        "error": "GPM_PERSISTENCE_OUTCOME_UNKNOWN",
        "packet_id": PACKET["packet_id"],
    }


class _CapturingStore:
    is_durable = True

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.decisions: list[dict] = []

    def decide(self, *args, **kwargs):
        self.decisions.append({"args": args, **kwargs})
        raise AssertionError("Advisory creation must not invoke a second approval")

    def get(self, packet_id: str, **kwargs):
        return None  # This fixture represents a first request, not a replay.

    def save(self, packet: dict, **kwargs) -> dict:
        self.calls.append({"packet": dict(packet), **kwargs})
        return dict(packet)


@pytest.fixture()
def quote_guidance_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AIVAN_ENV", "production")
    store = _CapturingStore()
    _reset_store(store)  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(router, prefix="/api/gpm")
    app.dependency_overrides[require_gpm_principal] = principal_for_tenant(TENANT)
    with patch(
        "aivan.gpm.router.analyze_quote",
        return_value={
            "quote_position": "within_mid_range",
            "recommendation": "negotiate",
            "confidence": "low",
            "reasoning": "advisory",
        },
    ):
        with TestClient(app) as client:
            yield client, store


def _guidance_payload() -> dict:
    return {
        "case_id": "case-001",
        "quote_id": "quote-001",
        "sku": "SKU-001",
        "supplier_id": "supplier-001",
        "supplier_quote": 12.5,
        "currency": "USD",
        "quantity": 10,
        "buyer_unit_price": 15.0,
        "buyer_total": 150.0,
        "supplier_total": 125.0,
        "margin_rate": 0.1667,
        "gltg_run_id": "gltg-run-001",
        "gltg_api_version": "v2",
    }


def test_same_tenant_and_idempotency_key_produce_stable_packet_identity(
    quote_guidance_client,
) -> None:
    client, store = quote_guidance_client
    headers = {
        "Idempotency-Key": "gpm-idem-001",
        "X-AIVAN-Trace-ID": "trace-006",
        "X-AIVAN-Actor-ID": "sales-001",
        "X-AIVAN-Role": "sales",
    }
    first = client.post("/api/gpm/quote-guidance", json=_guidance_payload(), headers=headers)
    second = client.post("/api/gpm/quote-guidance", json=_guidance_payload(), headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["packet_id"] == second.json()["packet_id"]
    assert store.calls[0]["idempotency_key"] == "gpm-idem-001"
    assert store.calls[0]["correlation_id"] == "trace-006"
    packet = store.calls[0]["packet"]
    assert packet["case_id"] == "case-001"
    assert packet["quote_id"] == "quote-001"
    assert packet["actor_id"] == "sales-001"
    assert packet["actor_role"] == "sales"
    assert packet["currency"] == "USD"
    assert packet["buyer_unit_price"] == 15.0
    assert packet["model_result"] == {
        "quote_position": "within_mid_range",
        "recommendation": "negotiate",
        "confidence": "low",
        "reasoning": "advisory",
    }
    assert packet["lineage"] == {
        "source_trace_id": "trace-006",
        "case_id": "case-001",
        "quote_id": "quote-001",
        "supplier_id": "supplier-001",
        "gltg_run_id": "gltg-run-001",
        "gltg_api_version": "v2",
    }


def test_unavailable_model_does_not_create_a_persisted_guidance_packet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIVAN_ENV", "production")
    store = _CapturingStore()
    _reset_store(store)  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(router, prefix="/api/gpm")
    app.dependency_overrides[require_gpm_principal] = principal_for_tenant(TENANT)
    with patch(
        "aivan.gpm.router.analyze_quote",
        return_value={
            "runtime_status": "unavailable",
            "reason": "provider_unavailable",
            "operator_action_required": True,
        },
    ):
        with TestClient(app) as client:
            response = client.post(
                "/api/gpm/quote-guidance",
                json=_guidance_payload(),
                headers={
                    "Idempotency-Key": "gpm-idem-model-down",
                    "X-AIVAN-Trace-ID": "trace-model-down",
                    "X-AIVAN-Actor-ID": "sales-001",
                    "X-AIVAN-Role": "sales",
                },
            )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "error": "GPM_MODEL_UNAVAILABLE",
        "reason": "provider_unavailable",
    }
    assert store.calls == []


def test_status_query_reads_persisted_result_without_running_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIVAN_ENV", "production")
    store = MagicMock()
    store.is_durable = True
    stored = {
        **PACKET,
        "case_id": "case-001",
        "quote_id": "quote-001",
        "actor_id": "sales-001",
        "actor_role": "sales",
        "model_result": {
            "recommendation": "negotiate",
            "quote_position": "within_mid_range",
            "confidence": "low",
        },
        "lineage": {"source_trace_id": "trace-create"},
    }
    store.get.return_value = stored
    _reset_store(store)
    app = FastAPI()
    app.include_router(router, prefix="/api/gpm")
    app.dependency_overrides[require_gpm_principal] = principal_for_tenant(TENANT)

    with patch("aivan.gpm.router.analyze_quote") as analyze:
        with TestClient(app) as client:
            response = client.get(
                f"/api/gpm/quote-guidance/{PACKET['packet_id']}",
                headers={"X-AIVAN-Trace-ID": "trace-readback"},
            )

    assert response.status_code == 200
    assert response.json()["model_result"]["recommendation"] == "negotiate"
    assert response.json()["lineage"] == {"source_trace_id": "trace-create"}
    analyze.assert_not_called()
    store.get.assert_called_once_with(
        PACKET["packet_id"],
        tenant_id=TENANT,
        correlation_id="trace-readback",
    )


def test_status_query_rejects_invalid_correlation_before_provider_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIVAN_ENV", "production")
    store = MagicMock()
    store.is_durable = True
    _reset_store(store)
    app = FastAPI()
    app.include_router(router, prefix="/api/gpm")
    app.dependency_overrides[require_gpm_principal] = principal_for_tenant(TENANT)

    with TestClient(app) as client:
        response = client.get(
            f"/api/gpm/quote-guidance/{PACKET['packet_id']}",
            headers={"X-AIVAN-Trace-ID": "../unsafe"},
        )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "GPM_INVALID_CORRELATION_ID"
    store.get.assert_not_called()


def test_production_create_requires_idempotency_key(quote_guidance_client) -> None:
    client, store = quote_guidance_client
    response = client.post(
        "/api/gpm/quote-guidance",
        json=_guidance_payload(),
        headers={"X-AIVAN-Trace-ID": "trace-007"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "GPM_IDEMPOTENCY_KEY_REQUIRED"
    assert store.calls == []


def test_production_create_requires_actor_context_before_model_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIVAN_ENV", "production")
    store = _CapturingStore()
    _reset_store(store)  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(router, prefix="/api/gpm")
    app.dependency_overrides[require_gpm_principal] = principal_for_tenant(TENANT)
    with patch("aivan.gpm.router.analyze_quote") as analyze:
        with TestClient(app) as client:
            response = client.post(
                "/api/gpm/quote-guidance",
                json=_guidance_payload(),
                headers={
                    "Idempotency-Key": "gpm-idem-missing-actor",
                    "X-AIVAN-Trace-ID": "trace-missing-actor",
                },
            )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "GPM_ACTOR_CONTEXT_REQUIRED"
    analyze.assert_not_called()
    assert store.calls == []


def test_capabilities_preserve_legacy_api_without_requiring_second_stage1_approval(
    quote_guidance_client,
) -> None:
    client, store = quote_guidance_client
    response = client.get("/api/gpm/capabilities")

    assert response.status_code == 200
    features = response.json()["features"]
    assert features["quote_guidance"] is True
    # The shared 2026-10-02 PRD preserves useful secure APIs; availability is
    # not a requirement to add their approval to the bounded consumer flow.
    assert features["approval_workflow"] is True
    assert features["rejection_workflow"] is True
    created = client.post("/api/gpm/quote-guidance", json=_guidance_payload(), headers={
        "Idempotency-Key": "synthetic-advisory-only", "X-AIVAN-Trace-ID": "trace-advisory",
        "X-AIVAN-Actor-ID": "sales-001", "X-AIVAN-Role-Context": "sales",
    })
    assert created.status_code == 201, created.text
    assert created.json()["approval_status"] == "pending"
    assert created.json()["human_approval_required"] is True
    assert created.json()["dispatched"] is False
    assert len(store.calls) == 1
    assert store.decisions == []


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_production_decision_routes_reject_body_operator_without_side_effects(
    quote_guidance_client,
    action: str,
) -> None:
    client, store = quote_guidance_client
    response = client.post(
        f"/api/gpm/quote-guidance/gpm_pkt_contract001/{action}",
        json={"operator_id": "operator-001"},
    )

    assert response.status_code == 422
    assert any(item["loc"] == ["body", "operator_id"] and item["type"] == "extra_forbidden"
               for item in response.json()["detail"])
    assert store.calls == []
    assert store.decisions == []


def test_missing_provider_auth_stops_before_any_http(monkeypatch):
    monkeypatch.delenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", raising=False)
    monkeypatch.delenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", raising=False)
    client = GiraffeDBClient("http://giraffe-db.test")
    with patch.object(client._session, "get") as request:
        with pytest.raises(PersistenceContractError):
            client.check_packet_capabilities(TENANT)
    request.assert_not_called()


@pytest.mark.parametrize("status", [202, 204, 301, 302, 307, 308])
def test_capability_probe_rejects_noncontract_http_success(status):
    client = GiraffeDBClient("http://giraffe-db.test")
    body = {"api_version": "gpm.packet-persistence.v1",
            "capabilities": {"create_packet": True, "read_packet": True,
                             "idempotent_create": True, "quote_lineage": True}}
    with patch.object(client._session, "get", return_value=_response(status, body)):
        with pytest.raises(PersistenceContractError):
            client.check_packet_capabilities(TENANT)


def test_tenant_service_profile_never_falls_back_to_another_tenant(monkeypatch):
    monkeypatch.setenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", '{"tenant-a":"synthetic-a"}')
    client = GiraffeDBClient("http://giraffe-db.test")
    with patch.object(client._session, "get") as request:
        with pytest.raises(PersistenceContractError):
            client.check_packet_capabilities("tenant-b")
    request.assert_not_called()


