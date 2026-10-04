"""Consumer mapping tests; synthetic transport is not live provider acceptance."""
from __future__ import annotations

import copy
import json

import httpx
import pytest

from aivan.integrations.gltg import GLTGClient, GLTGUnavailableError
from aivan.integrations.gltg_client import GLTGClient as HttpClient
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.rfq import RFQStrategy


def response():
    return {
        "ok": True, "gltg_run_id": "synthetic-run-v2", "model_version": "fixture-v2",
        "quantiles": {"p50_days": 76.53, "p80_days": 91.3, "p90_days": 91.8},
        "risk": {"selected_confidence_days": 91.3, "deadline_feasible": False},
        "components": {"production_days": 1.25},
        "source_observation_ids": ["observation-actual-input"],
        "warnings": [{"code": "MISSING_HISTORY", "message": "No history", "severity": "low"}],
        "persistence": {"status": "unavailable", "persisted_to_giraffe_db": False},
        "explanation_json": {"summary": "Provider-owned explanation"},
    }


def facade(monkeypatch, data, captured):
    monkeypatch.delenv("GLTG_API_VERSION", raising=False)
    monkeypatch.setenv("GLTG_SERVICE_AUTH_SECRET", "synthetic-auth-only")
    def handle(req):
        captured.append({"path": req.url.path, "body": json.loads(req.content),
                         "tenant": req.headers.get("x-service-tenant-id")})
        return httpx.Response(200, json=data)
    return GLTGClient(HttpClient(base_url="http://synthetic.test", transport=httpx.MockTransport(handle)))


def test_default_facade_is_authenticated_v2_with_facts_and_lineage(monkeypatch):
    captured = []
    factors = {"processing": {"setup_days": 2.25}, "material": {"material_availability_status": "in_stock"}}
    req = BuyerRequirement(product_type="shirt", quantity=100, extra={
        "trade_processing_factors": factors, "source_observation_ids": ["observation-actual-input"]})
    original = copy.deepcopy(req.model_dump())
    result = facade(monkeypatch, response(), captured).simulate(
        req, RFQStrategy(), 1, supplier_id="actual-supplier", tenant_id="tenant-alpha")
    call = captured[0]
    assert call["path"] == "/v2/lead-time/simulate"
    assert call["tenant"] == call["body"]["tenant_id"] == "tenant-alpha"
    assert call["body"]["supplier"]["supplier_id"] == "actual-supplier"
    assert call["body"]["supplier"].get("confidence") is None
    assert call["body"]["trade_processing_factors"] == factors
    assert call["body"]["source_observation_ids"] == ["observation-actual-input"]
    assert call["body"]["evidence"] == {"use_giraffe_db": True}
    assert result.source_api_version == "v2"
    assert (result.p50_days, result.p80_days, result.p90_days) == (76.53, 91.3, 91.8)
    assert result.minimum_feasible_days is None
    assert result.source_observation_ids == ["observation-actual-input"]
    assert result.persistence["status"] == "unavailable"
    assert req.model_dump() == original


def test_reply_estimate_preserves_provider_components_and_missing_earliest(monkeypatch):
    captured = []
    result = facade(monkeypatch, response(), captured).estimate_for_requirement(
        BuyerRequirement(product_type="shirt", quantity=100), supplier_id="actual-supplier", tenant_id="tenant-alpha")
    assert result.earliest_possible_days is None
    assert result.expected_days == 76.53
    assert result.calculated_lead_time_days == 91.3
    assert result.critical_path == []
    assert [(row.name, row.days, row.source) for row in result.components] == [("production_days", 1.25, "gltg")]
    assert result.gltg_run_id == "synthetic-run-v2"
    assert result.source_observation_ids == ["observation-actual-input"]


@pytest.mark.parametrize("quantiles", [
    {"p50_days": -1, "p80_days": 2, "p90_days": 3},
    {"p50_days": 3, "p80_days": 2, "p90_days": 4},
    {"p50_days": 1, "p80_days": 3, "p90_days": 2},
    {"p50_days": "1", "p80_days": 2, "p90_days": 3},
    {"p50_days": True, "p80_days": 2, "p90_days": 3},
    {"p50_days": None, "p80_days": 2, "p90_days": 3},
])
def test_invalid_canonical_quantiles_cannot_become_options(monkeypatch, quantiles):
    data = response()
    data["quantiles"] = quantiles
    with pytest.raises(GLTGUnavailableError):
        facade(monkeypatch, data, []).simulate(BuyerRequirement(quantity=1), RFQStrategy(), 1, tenant_id="tenant-alpha")


def test_zero_selected_quantile_is_not_replaced_with_p80(monkeypatch):
    data = response()
    data["quantiles"] = {"p50_days": 0, "p80_days": 1.5, "p90_days": 2.5}
    data["risk"]["selected_confidence_days"] = 0
    result = facade(monkeypatch, data, []).estimate_for_requirement(BuyerRequirement(quantity=1), tenant_id="tenant-alpha")
    assert result.calculated_lead_time_days == 0


@pytest.mark.parametrize("data", [{"ok": False}, [], {"quantiles": [], "risk": {}}])
def test_invalid_provider_envelope_is_stable_failure(monkeypatch, data):
    with pytest.raises(GLTGUnavailableError):
        facade(monkeypatch, data, []).simulate(BuyerRequirement(quantity=1), RFQStrategy(), 1, tenant_id="tenant-alpha")


def test_missing_auth_default_v2_makes_no_network_call(monkeypatch):
    captured = []
    client = facade(monkeypatch, response(), captured)
    monkeypatch.delenv("GLTG_SERVICE_AUTH_SECRET")
    with pytest.raises(GLTGUnavailableError, match="GLTG_TRUSTED_PROFILE_MISSING"):
        client.simulate(BuyerRequirement(quantity=1), RFQStrategy(), 1, tenant_id="tenant-alpha")
    assert captured == []


@pytest.mark.parametrize("metadata", [{"source_observation_ids": "invented"}, {"source_observation_ids": [""]}, {"trade_processing_factors": []}])
def test_invalid_facts_metadata_rejected_before_network(monkeypatch, metadata):
    captured = []
    client = facade(monkeypatch, response(), captured)
    with pytest.raises(GLTGUnavailableError, match="GLTG_INPUT_EVIDENCE_INVALID"):
        client.simulate(BuyerRequirement(quantity=1, extra=metadata), RFQStrategy(), 1, tenant_id="tenant-alpha")
    assert captured == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_quantile_rejected_without_rounding(value):
    data = response()
    data["quantiles"]["p50_days"] = value
    with pytest.raises(GLTGUnavailableError, match="GLTG_RESPONSE_QUANTILES_INVALID"):
        GLTGClient._normalize_v2_result(data)


@pytest.mark.parametrize("status", [401, 403, 422, 503, 302])
def test_provider_denial_never_retries_v1(monkeypatch, status):
    monkeypatch.delenv("GLTG_API_VERSION", raising=False)
    monkeypatch.setenv("GLTG_SERVICE_AUTH_SECRET", "synthetic-auth-only")
    calls = []
    def handle(req):
        calls.append(req.url.path)
        return httpx.Response(status, json={"message": "private downstream body"})
    client = GLTGClient(HttpClient(base_url="http://synthetic.test", transport=httpx.MockTransport(handle)))
    with pytest.raises(GLTGUnavailableError) as exc:
        client.simulate(BuyerRequirement(quantity=1), RFQStrategy(), 1, tenant_id="tenant-alpha")
    assert str(status) in str(exc.value)
    assert "private" not in str(exc.value)
    assert calls == ["/v2/lead-time/simulate"]


def test_transport_exception_never_returns_sensitive_context(monkeypatch):
    monkeypatch.setenv("GLTG_SERVICE_AUTH_SECRET", "synthetic-auth-only")
    def handle(req):
        raise httpx.ConnectError("sensitive-credential-context")
    result = HttpClient(base_url="http://synthetic.test", transport=httpx.MockTransport(handle)).simulate_lead_time_v2(
        {"tenant_id": "tenant-alpha", "order": {"quantity": 1}})
    assert result.error == "GLTG_UNAVAILABLE"
    assert result.data is None
