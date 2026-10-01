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
        "sku": "shirt",
        "supplier_id": "supplier-1",
        "supplier_quote": 12.5,
        "currency": "USD",
        "quantity": 1000,
        "quote_position": "within_mid_range",
        "recommendation": "negotiate",
        "confidence": "low",
        "human_approval_required": True,
        "approval_status": "pending",
        "dispatched": False,
        "llm_reasoning": "{}",
        "evidence_ids": "[]",
        "notes": "case=case-1",
    }
    value.update(overrides)
    return value


def _client(monkeypatch, handler):
    monkeypatch.setenv("GPM_API_KEY", "gpm-service-key")
    return GPMGuidanceClient(
        base_url="http://gpm.test",
        transport=httpx.MockTransport(handler),
    )


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
        trace_id="trace-stage1",
        idempotency_key="gpm-case-1-option-1",
        sku="shirt",
        supplier_id="supplier-1",
        supplier_quote=12.5,
        currency="USD",
        quantity=1000,
        notes="case=case-1",
    )

    request = captured["request"]
    assert request.url.path == "/api/gpm/quote-guidance"
    assert request.headers["X-AIVAN-API-Key"] == "gpm-service-key"
    assert request.headers["X-AIVAN-Tenant-ID"] == "tenant-alpha"
    assert request.headers["X-AIVAN-Trace-ID"] == "trace-stage1"
    assert request.headers["Idempotency-Key"] == "gpm-case-1-option-1"
    assert captured["payload"] == {
        "sku": "shirt",
        "supplier_id": "supplier-1",
        "supplier_quote": 12.5,
        "currency": "USD",
        "quantity": 1000,
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
            trace_id="trace-stage1",
            idempotency_key="gpm-case-1-option-1",
            sku="shirt",
            supplier_id="supplier-1",
            supplier_quote=12.5,
            currency="USD",
            quantity=1000,
        )
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
            trace_id="trace-stage1",
            idempotency_key="gpm-case-1-option-1",
            sku="shirt",
            supplier_id="supplier-1",
            supplier_quote=12.5,
            currency="USD",
            quantity=1000,
        )


@pytest.mark.parametrize(
    "response",
    [
        _response(tenant_id="tenant-other"),
        _response(dispatched=True),
        _response(approval_status="approved"),
        _response(human_approval_required=False),
        _response(packet_id="../packet"),
    ],
)
def test_invalid_or_unsafe_response_fails_closed(monkeypatch, response):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=response)

    with pytest.raises(GPMGuidanceUnavailableError, match="GPM_RESPONSE_INVALID"):
        _client(monkeypatch, handler).create_guidance(
            tenant_id="tenant-alpha",
            trace_id="trace-stage1",
            idempotency_key="gpm-case-1-option-1",
            sku="shirt",
            supplier_id="supplier-1",
            supplier_quote=12.5,
            currency="USD",
            quantity=1000,
        )
