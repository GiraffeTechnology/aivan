"""Replay synthetic stored analysis without claiming a live-model acceptance."""
from __future__ import annotations

import copy
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from aivan.gpm.packet_store import GPMPacketStore
from aivan.gpm.router import _reset_store, require_gpm_tenant, router
from aivan.gpm.request_identity import request_fingerprint

PAYLOAD = {"case_id": "case-1", "quote_id": "quote-1", "sku": "Cotton shirts", "supplier_id": "supplier-1",
           "supplier_quote": 12.5, "currency": "USD", "quantity": 100, "buyer_unit_price": 15,
           "buyer_total": 1500, "supplier_total": 1250, "margin_rate": .1667, "gltg_run_id": "gltg-1",
           "gltg_api_version": "v2", "evidence_ids": None, "notes": None}
HEADERS = {"Idempotency-Key": "same-business-input", "X-AIVAN-Actor-ID": "operator-1",
           "X-AIVAN-Role": "sales", "X-AIVAN-Trace-ID": "trace-first"}


@pytest.fixture
def boundary(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.delenv("GPM_LLM_RUNTIME_MODE", raising=False)
    persisted = {}
    provider = MagicMock()
    provider.get_packet.side_effect = lambda identity, **kwargs: copy.deepcopy(persisted.get(identity))
    def create(packet, **kwargs):
        persisted[packet["packet_id"]] = copy.deepcopy(packet)
        return copy.deepcopy(packet)
    provider.create_packet.side_effect = create
    store = GPMPacketStore(provider)
    _reset_store(store)
    app = FastAPI(); app.include_router(router, prefix="/api/gpm")
    app.dependency_overrides[require_gpm_tenant] = lambda: "tenant-1"
    model = MagicMock(side_effect=[{"recommendation": "negotiate", "confidence": "medium",
                    "quote_position": "within_mid_range", "reasoning": "Synthetic analysis first response.",
                    "runtime_status": "synthetic-test", "model_provider": "synthetic-test"},
                    AssertionError("the model must not run again for a committed request")])
    monkeypatch.setattr("aivan.gpm.router.analyze_quote", model)
    with TestClient(app) as client:
        yield client, model, provider, persisted
    _reset_store(GPMPacketStore())


def test_committed_replay_skips_model_and_preserves_original_trace_after_restart(boundary):
    client, model, provider, _ = boundary
    first = client.post("/api/gpm/quote-guidance", json=PAYLOAD, headers=HEADERS)
    assert first.status_code == 201, first.text
    _reset_store(GPMPacketStore(provider))  # no memory survives the store restart
    repeated = client.post("/api/gpm/quote-guidance", json=PAYLOAD,
                           headers={**HEADERS, "X-AIVAN-Trace-ID": "trace-retry"})
    assert repeated.status_code == 201 and repeated.json() == first.json()
    assert repeated.json()["lineage"]["source_trace_id"] == "trace-first"
    assert repeated.headers["X-GPM-Replayed"] == "true"
    assert repeated.headers["X-GPM-Request-SHA256"] == request_fingerprint(
        PAYLOAD, tenant_id="tenant-1", actor_id="operator-1", actor_role="sales")
    assert model.call_count == 1 and provider.create_packet.call_count == 1


@pytest.mark.parametrize("changes", [{"case_id": "other-case"}, {"quote_id": "quote-revised"},
    {"supplier_id": "other-supplier"}, {"supplier_quote": 13}, {"currency": "EUR"}, {"quantity": 101},
    {"buyer_total": 1501}, {"buyer_unit_price": 16}, {"supplier_total": 1251}, {"margin_rate": .2},
    {"gltg_run_id": "gltg-revised"}, {"gltg_api_version": "v3"}, {"evidence_ids": ["evidence-new"]},
    {"notes": "These are revised commercial instructions."}, {"sku": "Coats"}])
def test_changed_business_input_conflicts_before_model(boundary, changes):
    client, model, provider, _ = boundary
    assert client.post("/api/gpm/quote-guidance", json=PAYLOAD, headers=HEADERS).status_code == 201
    replay = client.post("/api/gpm/quote-guidance", json={**PAYLOAD, **changes}, headers=HEADERS)
    assert replay.status_code == 409 and replay.json()["detail"]["error"] == "GPM_IDEMPOTENCY_CONFLICT"
    assert model.call_count == 1 and provider.create_packet.call_count == 1


@pytest.mark.parametrize("header,value", [("X-AIVAN-Actor-ID", "operator-other"), ("X-AIVAN-Role", "buyer")])
def test_different_actor_cannot_reuse_request_identity(boundary, header, value):
    client, model, _, _ = boundary
    assert client.post("/api/gpm/quote-guidance", json=PAYLOAD, headers=HEADERS).status_code == 201
    assert client.post("/api/gpm/quote-guidance", json=PAYLOAD, headers={**HEADERS, header: value}).status_code == 409
    assert model.call_count == 1


def test_provider_read_failure_does_not_trigger_new_model_result(boundary):
    from aivan.gpm.giraffe_db_client import GiraffeDBClientError
    client, model, provider, _ = boundary
    provider.get_packet.side_effect = GiraffeDBClientError("synthetic provider outage")
    response = client.post("/api/gpm/quote-guidance", json=PAYLOAD, headers=HEADERS)
    assert response.status_code == 503 and model.call_count == 0
    provider.create_packet.assert_not_called()


def test_provider_cannot_substitute_another_packet_identity_on_replay(boundary):
    client, model, provider, persisted = boundary
    first = client.post("/api/gpm/quote-guidance", json=PAYLOAD, headers=HEADERS)
    assert first.status_code == 201
    identity = first.json()["packet_id"]
    persisted[identity]["packet_id"] = "gpm_pkt_wrong_identity"
    response = client.post("/api/gpm/quote-guidance", json=PAYLOAD, headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "GPM_PERSISTENCE_OUTCOME_UNKNOWN"
    assert model.call_count == 1 and provider.create_packet.call_count == 1


def test_explicit_zero_model_guidance_uses_totals_and_durable_replay(boundary, monkeypatch):
    client, model, provider, _ = boundary
    monkeypatch.setenv("AIVAN_LLM_API_ENABLED", "false")
    mock_analysis = MagicMock(side_effect=AssertionError("zero-model is not mock analysis"))
    monkeypatch.setattr("aivan.gpm.router.mock_quote_analysis", mock_analysis)
    monkeypatch.setenv("GPM_LLM_RUNTIME_MODE", "mock")
    first = client.post("/api/gpm/quote-guidance", json=PAYLOAD, headers=HEADERS)
    assert first.status_code == 201, first.text
    packet = first.json()
    assert packet["recommendation"] == "human_review_required"
    assert packet["quote_position"] == "insufficient_data"
    assert packet["confidence"] == "low"
    assert packet["model_result"]["runtime_status"] == "disabled"
    assert packet["model_result"]["model_provider"] == "none"
    assert packet["model_result"]["model_name"] is None
    assert packet["model_result"]["calculation"] == {
        "supplied_supplier_total": 1250, "supplied_buyer_total": 1500,
        "quoted_total_difference": 250, "quoted_total_difference_rate": .17,
    }
    assert packet["approval_status"] == "pending" and packet["dispatched"] is False
    _reset_store(GPMPacketStore(provider))
    repeated = client.post("/api/gpm/quote-guidance", json=PAYLOAD, headers=HEADERS)
    assert repeated.status_code == 201 and repeated.json() == packet
    assert repeated.headers["X-GPM-Replayed"] == "true"
    model.assert_not_called()
    mock_analysis.assert_not_called()
    assert provider.create_packet.call_count == 1


def test_explicit_zero_model_does_not_mask_persistence_failure(boundary, monkeypatch):
    from aivan.gpm.giraffe_db_client import GiraffeDBClientError
    client, model, provider, _ = boundary
    monkeypatch.setenv("AIVAN_LLM_API_ENABLED", "false")
    provider.create_packet.side_effect = GiraffeDBClientError("synthetic provider outage")
    response = client.post("/api/gpm/quote-guidance", json=PAYLOAD, headers=HEADERS)
    assert response.status_code == 503
    model.assert_not_called()
