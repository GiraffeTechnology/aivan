"""Unit tests for the standalone GLTG API client.

These use an httpx MockTransport so no live GLTG server is required.
"""

from __future__ import annotations

import json

import httpx
import pytest

from aivan.integrations.gltg_client import GLTGClient, GLTGClientResult


def _handler(captured: dict):
    def handle(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["content"] = request.content.decode() if request.content else ""
        captured["headers"] = dict(request.headers)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "service": "gltg"})
        if request.url.path == "/v1/lead-time/estimate":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "estimated_lead_time_days": 28,
                    "p50_days": 24,
                    "p80_days": 28,
                    "p90_days": 35,
                    "minimum_feasible_days": 20,
                    "earliest_delivery_date": "2026-07-25",
                    "feasible": True,
                    "supplier_count": 1,
                    "selected_supplier_id": "M1",
                    "warnings": [],
                    "calculation_trace": [],
                },
            )
        if request.url.path == "/v2/lead-time/simulate":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "gltg_run_id": "GLTG_test_001",
                    "assessment_schema_version": "gltg-assessment-v1",
                    "model_provider": "mock",
                    "model_name": "qwen3.5",
                    "evaluation_mode": "llm",
                    "quantiles": {"p50_days": 32, "p80_days": 45, "p90_days": 56},
                    "risk": {
                        "deadline_risk_level": "medium",
                        "selected_confidence_days": 45,
                        "deadline_feasible": True,
                    },
                    "assessment_packet": {"follow_up_questions": ["Confirm material availability"]},
                    "manual_review_required": True,
                    "fallback_supplier_required": False,
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    return handle


def _client(captured: dict) -> GLTGClient:
    return GLTGClient(base_url="http://gltg.test", transport=httpx.MockTransport(_handler(captured)))


def test_health_ok():
    cap: dict = {}
    res = _client(cap).health()
    assert res.ok is True
    assert res.data == {"status": "ok", "service": "gltg"}
    assert cap["method"] == "GET"


def test_estimate_lead_time_posts_payload():
    cap: dict = {}
    res = _client(cap).estimate_lead_time(
        order={"quantity": 10000, "product_type": "apparel"},
        suppliers=[{"supplier_id": "M1", "production_days": 14}],
    )
    assert res.ok is True
    assert res.data["estimated_lead_time_days"] == 28
    assert cap["method"] == "POST"
    assert "10000" in cap["content"]


def test_invalid_order_is_rejected_before_request():
    cap: dict = {}
    res = _client(cap).estimate_lead_time(order={}, suppliers=[])
    assert res.ok is False
    assert "quantity" in (res.error or "")
    # request never sent
    assert cap == {}


def test_http_error_surfaces_structured_error():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = GLTGClient(base_url="http://gltg.test", transport=httpx.MockTransport(handle))
    res = client.estimate_lead_time(order={"quantity": 1}, suppliers=[])
    assert res.ok is False
    assert res.status_code == 500
    assert "HTTP 500" in (res.error or "")


def test_redirect_is_not_accepted_as_gltg_success(monkeypatch):
    monkeypatch.setenv("GLTG_SERVICE_AUTH_SECRET", "service-test-secret")

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, json={"quantiles": {}})

    client = GLTGClient(
        base_url="http://gltg.test",
        transport=httpx.MockTransport(handle),
    )
    res = client.simulate_lead_time_v2(
        {
            "request_id": "REQ_test",
            "tenant_id": "tenant-alpha",
            "order": {"quantity": 1},
        }
    )

    assert res.ok is False
    assert res.status_code == 302
    assert res.error == "GLTG_UNEXPECTED_STATUS_302"


def test_connection_error_does_not_fall_back():
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = GLTGClient(base_url="http://gltg.test", transport=httpx.MockTransport(handle))
    res = client.health()
    assert isinstance(res, GLTGClientResult)
    assert res.ok is False
    assert res.data is None  # never a locally computed value


def test_simulate_lead_time_v2_posts_trusted_service_headers(monkeypatch):
    monkeypatch.setenv("GLTG_SERVICE_AUTH_SECRET", "service-test-secret")
    cap: dict = {}
    res = _client(cap).simulate_lead_time_v2(
        {
            "request_id": "REQ_test",
            "tenant_id": "tenant-alpha",
            "source_system": "aivan",
            "order": {"quantity": 10000, "product_type": "apparel"},
            "supplier": {"supplier_id": "M1"},
        }
    )
    assert res.ok is True
    assert res.data["gltg_run_id"] == "GLTG_test_001"
    assert cap["method"] == "POST"
    assert cap["url"].endswith("/v2/lead-time/simulate")
    assert cap["headers"]["x-service-tenant-id"] == "tenant-alpha"
    assert cap["headers"]["x-service-auth"] == "service-test-secret"


def test_simulate_lead_time_v2_rejects_missing_service_auth_without_network(monkeypatch):
    monkeypatch.delenv("GLTG_SERVICE_AUTH_SECRET", raising=False)
    cap: dict = {}

    res = _client(cap).simulate_lead_time_v2(
        {
            "request_id": "REQ_test",
            "tenant_id": "tenant-alpha",
            "source_system": "aivan",
            "order": {"quantity": 10000, "product_type": "apparel"},
            "supplier": {"supplier_id": "M1"},
        }
    )

    assert res.ok is False
    assert res.error == "GLTG_TRUSTED_PROFILE_MISSING"
    assert cap == {}


@pytest.mark.parametrize("tenant_id", ["", "租户-alpha"])
def test_simulate_lead_time_v2_rejects_invalid_tenant_without_network(
    monkeypatch, tenant_id
):
    monkeypatch.setenv("GLTG_SERVICE_AUTH_SECRET", "service-test-secret")
    cap: dict = {}

    res = _client(cap).simulate_lead_time_v2(
        {
            "request_id": "REQ_test",
            "tenant_id": tenant_id,
            "source_system": "aivan",
            "order": {"quantity": 10000, "product_type": "apparel"},
            "supplier": {"supplier_id": "M1"},
        }
    )

    assert res.ok is False
    assert res.error == "GLTG_TRUSTED_PROFILE_MISSING"
    assert cap == {}


def test_facade_uses_v2_when_configured(monkeypatch):
    from aivan.integrations.gltg import GLTGClient as GLTGFacade
    from aivan.schemas.requirement import BuyerRequirement
    from aivan.schemas.rfq import RFQStrategy

    monkeypatch.setenv("GLTG_API_VERSION", "v2")
    monkeypatch.setenv("GLTG_SERVICE_AUTH_SECRET", "service-test-secret")
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-alpha")
    cap: dict = {}
    facade = GLTGFacade(http=_client(cap))

    result = facade.simulate(
        BuyerRequirement(category="apparel", product_type="shirt", quantity=10000, destination="Vancouver", delivery_days=45),
        RFQStrategy(lead_time_confidence="P80"),
        supplier_count=2,
    )

    assert cap["url"].endswith("/v2/lead-time/simulate")
    assert result.source_api_version == "v2"
    assert result.gltg_run_id == "GLTG_test_001"
    assert result.assessment_schema_version == "gltg-assessment-v1"
    assert result.assessment_packet["follow_up_questions"]
    assert result.p50_days == 32
    assert result.selected_confidence_days == 45


def test_facade_binds_supplier_anchor_to_private_db_evidence(monkeypatch):
    from aivan.integrations.gltg import GLTGClient as GLTGFacade
    from aivan.schemas.requirement import BuyerRequirement
    from aivan.schemas.rfq import RFQStrategy

    monkeypatch.setenv("GLTG_API_VERSION", "v2")
    monkeypatch.setenv("GLTG_SERVICE_AUTH_SECRET", "service-test-secret")
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-alpha")
    cap: dict = {}

    GLTGFacade(http=_client(cap)).simulate(
        BuyerRequirement(
            category="apparel",
            product_type="shirt",
            quantity=10_000,
            destination="Vancouver",
        ),
        RFQStrategy(lead_time_confidence="P80"),
        supplier_count=1,
        supplier_id="GDB_SYN_V1_SUP_000001",
    )

    payload = json.loads(cap["content"])
    assert payload["supplier"]["supplier_id"] == "GDB_SYN_V1_SUP_000001"
    assert payload["evidence"] == {"use_giraffe_db": True}


def test_facade_rejects_missing_private_db_evidence(monkeypatch):
    from aivan.integrations.gltg import GLTGClient as GLTGFacade
    from aivan.integrations.gltg import GLTGUnavailableError
    from aivan.schemas.requirement import BuyerRequirement
    from aivan.schemas.rfq import RFQStrategy

    monkeypatch.setenv("GLTG_API_VERSION", "v2")
    monkeypatch.setenv("GLTG_SERVICE_AUTH_SECRET", "service-test-secret")
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-alpha")

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "quantiles": {"p50_days": 30, "p80_days": 36, "p90_days": 40},
                "warnings": [
                    {"code": "EVIDENCE_NOT_FOUND", "message": "not found"}
                ],
            },
        )

    with pytest.raises(GLTGUnavailableError, match="GLTG_EVIDENCE_NOT_FOUND"):
        GLTGFacade(
            http=GLTGClient(
                base_url="http://gltg.test",
                transport=httpx.MockTransport(handle),
            )
        ).simulate(
            BuyerRequirement(
                category="apparel",
                product_type="shirt",
                quantity=10_000,
                destination="Vancouver",
            ),
            RFQStrategy(lead_time_confidence="P80"),
            supplier_count=1,
            supplier_id="GDB_SYN_V1_SUP_000001",
        )


def test_giraffe_db_headers_include_service_auth_secret(monkeypatch):
    from aivan.integrations.giraffe_db import _giraffe_db_service_headers

    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "svc-test-secret")

    assert _giraffe_db_service_headers("tenant-alpha") == {
        "X-Service-Tenant-ID": "tenant-alpha",
        "X-Service-Auth": "svc-test-secret",
    }


def test_giraffe_db_headers_omit_empty_service_auth(monkeypatch):
    from aivan.integrations.giraffe_db import _giraffe_db_service_headers

    monkeypatch.delenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", raising=False)

    assert _giraffe_db_service_headers("tenant-alpha") == {"X-Service-Tenant-ID": "tenant-alpha"}
