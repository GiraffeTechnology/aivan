"""Contract tests for the standalone Stage 1 GPM quote-guidance client."""

from __future__ import annotations

import json

import httpx
import pytest

from aivan.integrations.gpm_guidance_client import (
    GPMGuidanceClient,
    GPMGuidanceUnavailableError,
)


def _response(**overrides):
    value = {
        "packet_id": "gpm_pkt_stage1",
        "tenant_id": "tenant-alpha",
        "case_id": "case-1",
        "quote_id": "quote-1",
        "actor_id": "sales-1",
        "actor_role": "sales",
        "sku": "shirt",
        "supplier_id": "supplier-1",
        "supplier_quote": 12.5,
        "currency": "USD",
        "quantity": 1000,
        "buyer_unit_price": 15.0,
        "buyer_total": 15000.0,
        "supplier_total": 12500.0,
        "margin_rate": 0.1667,
        "quote_position": "within_mid_range",
        "recommendation": "negotiate",
        "confidence": "low",
        "human_approval_required": True,
        "approval_status": "pending",
        "dispatched": False,
        "llm_reasoning": "{}",
        "evidence_ids": "[]",
        "notes": "case=case-1",
        "gltg_run_id": "gltg-run-1",
        "gltg_api_version": "v2",
        "model_result": {
            "recommendation": "negotiate",
            "quote_position": "within_mid_range",
            "confidence": "low",
            "runtime_status": "available",
        },
        "lineage": {
            "source_trace_id": "trace-stage1",
            "case_id": "case-1",
            "quote_id": "quote-1",
            "supplier_id": "supplier-1",
            "gltg_run_id": "gltg-run-1",
            "gltg_api_version": "v2",
        },
    }
    value.update(overrides)
    return value


def _client(monkeypatch, handler):
    monkeypatch.setenv("GPM_API_KEY", "gpm-service-key")
    return GPMGuidanceClient(
        base_url="http://gpm.test",
        transport=httpx.MockTransport(handler),
    )


def _tenant_headers(tenant_id):
    return GPMGuidanceClient._trusted_headers(
        tenant_id=tenant_id, actor_id="operator", actor_role="buyer",
        trace_id="trace-tenants", idempotency_key="guidance-tenants",
    )


def test_tenant_key_map_selects_only_authenticated_tenant_key(monkeypatch):
    monkeypatch.setenv("GPM_TENANT_API_KEYS", json.dumps({
        "tenant-alpha": "private-gpm-alpha", "tenant-beta": "private-gpm-beta",
    }))
    monkeypatch.setenv("GPM_API_KEY", "must-not-be-used")
    for tenant, key in (("tenant-alpha", "private-gpm-alpha"), ("tenant-beta", "private-gpm-beta")):
        headers = _tenant_headers(tenant)
        assert headers["X-AIVAN-Tenant-ID"] == tenant
        assert headers["X-AIVAN-API-Key"] == key
    with pytest.raises(GPMGuidanceUnavailableError, match="GPM_TRUSTED_PROFILE_MISSING"):
        _tenant_headers("unconfigured-tenant")


@pytest.mark.parametrize("configured", ["invalid-json", "[]", '{"tenant-alpha": null}', '{"tenant-alpha": ""}'])
def test_invalid_tenant_key_map_fails_closed(monkeypatch, configured):
    monkeypatch.setenv("GPM_TENANT_API_KEYS", configured)
    monkeypatch.setenv("GPM_API_KEY", "must-not-be-used")
    with pytest.raises(GPMGuidanceUnavailableError, match="GPM_TENANT_AUTH_MISCONFIGURED"):
        _tenant_headers("tenant-alpha")


def test_test_transport_is_rejected_in_production(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "production")

    with pytest.raises(RuntimeError, match="forbidden in production"):
        GPMGuidanceClient(
            base_url="http://gpm.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(201, json=_response())
            ),
        )


def test_create_guidance_sends_tenant_auth_trace_and_idempotency(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["payload"] = json.loads(request.content)
        return httpx.Response(201, json=_response())

    result = _client(monkeypatch, handler).create_guidance(
        tenant_id="tenant-alpha",
        actor_id="sales-1",
        actor_role="sales",
        trace_id="trace-stage1",
        idempotency_key="gpm-case-1-option-1",
        case_id="case-1",
        quote_id="quote-1",
        sku="shirt",
        supplier_id="supplier-1",
        supplier_quote=12.5,
        currency="USD",
        quantity=1000,
        buyer_unit_price=15.0,
        buyer_total=15000.0,
        supplier_total=12500.0,
        margin_rate=0.1667,
        gltg_run_id="gltg-run-1",
        gltg_api_version="v2",
        notes="case=case-1",
    )

    request = captured["request"]
    assert request.url.path == "/api/gpm/quote-guidance"
    assert request.headers["X-AIVAN-API-Key"] == "gpm-service-key"
    assert request.headers["X-AIVAN-Tenant-ID"] == "tenant-alpha"
    assert request.headers["X-AIVAN-Actor-ID"] == "sales-1"
    assert request.headers["X-AIVAN-Role"] == "sales"
    assert request.headers["X-AIVAN-Trace-ID"] == "trace-stage1"
    assert request.headers["Idempotency-Key"] == "gpm-case-1-option-1"
    assert captured["payload"] == {
        "case_id": "case-1",
        "quote_id": "quote-1",
        "sku": "shirt",
        "supplier_id": "supplier-1",
        "supplier_quote": 12.5,
        "currency": "USD",
        "quantity": 1000,
        "buyer_unit_price": 15.0,
        "buyer_total": 15000.0,
        "supplier_total": 12500.0,
        "margin_rate": 0.1667,
        "gltg_run_id": "gltg-run-1",
        "gltg_api_version": "v2",
        "evidence_ids": None,
        "notes": "case=case-1",
    }
    assert result["packet_id"] == "gpm_pkt_stage1"
    assert result["recommendation"] == "negotiate"
    assert result["dispatched"] is False


def test_missing_api_key_fails_before_network(monkeypatch):
    monkeypatch.delenv("GPM_API_KEY", raising=False)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201, json=_response())

    client = GPMGuidanceClient(
        base_url="http://gpm.test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(GPMGuidanceUnavailableError, match="GPM_TRUSTED_PROFILE_MISSING"):
        client.create_guidance(
            tenant_id="tenant-alpha",
            actor_id="sales-1",
            actor_role="sales",
            trace_id="trace-stage1",
            idempotency_key="gpm-case-1-option-1",
            case_id="case-1",
            quote_id="quote-1",
            sku="shirt",
            supplier_id="supplier-1",
            supplier_quote=12.5,
            currency="USD",
            quantity=1000,
            buyer_unit_price=15.0,
            buyer_total=15000.0,
            supplier_total=12500.0,
            margin_rate=0.1667,
            gltg_run_id="gltg-run-1",
            gltg_api_version="v2",
        )
    assert calls == []


@pytest.mark.parametrize(
    "override",
    [
        {"currency": "usd"},
        {"buyer_total": -1.0},
        {"margin_rate": 1.0},
        {"quote_id": "../quote"},
    ],
)
def test_invalid_pricing_identity_fails_before_network(monkeypatch, override):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201, json=_response())

    values = {
        "tenant_id": "tenant-alpha",
        "actor_id": "sales-1",
        "actor_role": "sales",
        "trace_id": "trace-stage1",
        "idempotency_key": "gpm-case-1-option-1",
        "case_id": "case-1",
        "quote_id": "quote-1",
        "sku": "shirt",
        "supplier_id": "supplier-1",
        "supplier_quote": 12.5,
        "currency": "USD",
        "quantity": 1000,
        "buyer_unit_price": 15.0,
        "buyer_total": 15000.0,
        "supplier_total": 12500.0,
        "margin_rate": 0.1667,
        "gltg_run_id": "gltg-run-1",
        "gltg_api_version": "v2",
    }
    values.update(override)

    with pytest.raises(GPMGuidanceUnavailableError, match="GPM_REQUEST_INVALID"):
        _client(monkeypatch, handler).create_guidance(**values)
    assert calls == []


@pytest.mark.parametrize(
    ("status", "code"),
    [(302, "GPM_UNEXPECTED_STATUS_302"), (503, "GPM_HTTP_503")],
)
def test_non_201_is_never_accepted(monkeypatch, status, code):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "not_ready"})

    with pytest.raises(GPMGuidanceUnavailableError, match=code):
        _client(monkeypatch, handler).create_guidance(
            tenant_id="tenant-alpha",
            actor_id="sales-1",
            actor_role="sales",
            trace_id="trace-stage1",
            idempotency_key="gpm-case-1-option-1",
            case_id="case-1",
            quote_id="quote-1",
            sku="shirt",
            supplier_id="supplier-1",
            supplier_quote=12.5,
            currency="USD",
            quantity=1000,
            buyer_unit_price=15.0,
            buyer_total=15000.0,
            supplier_total=12500.0,
            margin_rate=0.1667,
            gltg_run_id="gltg-run-1",
            gltg_api_version="v2",
        )


@pytest.mark.parametrize(
    "response",
    [
        _response(tenant_id="tenant-other"),
        _response(dispatched=True),
        _response(approval_status="approved"),
        _response(human_approval_required=False),
        _response(packet_id="../packet"),
        _response(quote_id="quote-other"),
        _response(currency="EUR"),
        _response(buyer_total=999.0),
        _response(model_result={"recommendation": "accept", "confidence": "low"}),
    ],
)
def test_invalid_or_unsafe_response_fails_closed(monkeypatch, response):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=response)

    with pytest.raises(GPMGuidanceUnavailableError, match="GPM_RESPONSE_INVALID"):
        _client(monkeypatch, handler).create_guidance(
            tenant_id="tenant-alpha",
            actor_id="sales-1",
            actor_role="sales",
            trace_id="trace-stage1",
            idempotency_key="gpm-case-1-option-1",
            case_id="case-1",
            quote_id="quote-1",
            sku="shirt",
            supplier_id="supplier-1",
            supplier_quote=12.5,
            currency="USD",
            quantity=1000,
            buyer_unit_price=15.0,
            buyer_total=15000.0,
            supplier_total=12500.0,
            margin_rate=0.1667,
            gltg_run_id="gltg-run-1",
            gltg_api_version="v2",
        )


@pytest.mark.parametrize("replay_headers,accepted", [("valid", True), ("missing-hash", False), ("wrong-hash", False), ("absent", False)])
def test_original_trace_requires_verified_business_input_replay(monkeypatch, replay_headers, accepted):
    from aivan.gpm.request_identity import request_fingerprint
    def handler(request):
        headers = {}
        if replay_headers != "absent":
            headers["X-GPM-Replayed"] = "true"
        if replay_headers == "valid":
            headers["X-GPM-Request-SHA256"] = request_fingerprint(json.loads(request.content),
                tenant_id="tenant-alpha", actor_id="sales-1", actor_role="sales")
        if replay_headers == "wrong-hash":
            headers["X-GPM-Request-SHA256"] = "0" * 64
        return httpx.Response(201, json=_response(), headers=headers)
    request = dict(tenant_id="tenant-alpha", actor_id="sales-1", actor_role="sales", trace_id="new-transport-trace",
        idempotency_key="gpm-case-1-option-1", case_id="case-1", quote_id="quote-1", sku="shirt", supplier_id="supplier-1",
        supplier_quote=12.5, currency="USD", quantity=1000, buyer_unit_price=15, buyer_total=15000, supplier_total=12500,
        margin_rate=.1667, gltg_run_id="gltg-run-1", gltg_api_version="v2", notes="case=case-1")
    client = _client(monkeypatch, handler)
    if accepted:
        assert client.create_guidance(**request)["lineage"]["source_trace_id"] == "trace-stage1"
    else:
        with pytest.raises(GPMGuidanceUnavailableError, match="GPM_RESPONSE_INVALID"):
            client.create_guidance(**request)
