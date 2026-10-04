"""Supplier stub gating boundary tests (PRD §10, §18.10)."""
from __future__ import annotations

import httpx
import pytest

from aivan.integrations import giraffe_db
from aivan.integrations.giraffe_db import (
    GiraffeDBClient,
    GiraffeDBContextError,
    stub_suppliers_allowed,
)
from aivan.execution.safety import evaluate_supplier_readiness
from aivan.schemas.requirement import BuyerRequirement
from aivan.sourcing.supplier_registry import clear_registry


def _requirement() -> BuyerRequirement:
    return BuyerRequirement(category="apparel", product_type="shirt", quantity=5000)


def test_production_context_requires_real_giraffe_db_endpoint(monkeypatch, db_session):
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.delenv("GIRAFFE_DB_BASE_URL", raising=False)
    clear_registry()
    assert stub_suppliers_allowed() is False
    with pytest.raises(GiraffeDBContextError, match="GIRAFFE_DB_CONTEXT_ENDPOINT_REQUIRED"):
        GiraffeDBClient(db_session).build_context(_requirement())


def test_real_giraffe_db_supplier_context_uses_tenant_bound_service_auth(monkeypatch, db_session):
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "https://giraffe-db.test")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "service-secret")
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "tenant_id": "tenant-a",
                        "supplier_id": "SUP-000001",
                        "supplier_name": "Verified Mill",
                        "company_type": "manufacturer",
                        "categories_json": ["apparel"],
                        "capabilities_json": ["cut-and-sew"],
                        "materials_json": ["cotton"],
                        "languages_json": ["en"],
                        "channels_json": ["email"],
                        "incoterms_json": ["FOB"],
                        "logistics_modes_json": ["sea"],
                        "risk_tags_json": ["capacity-review"],
                        "delivery_score": 0.91,
                        "past_performance_score": 0.88,
                        "active": True,
                    }
                ],
                "total": 1,
                "limit": 100,
                "offset": 0,
            },
        )

    real_client = httpx.Client

    class PatchedClient(real_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", PatchedClient)
    context = GiraffeDBClient(db_session, tenant_id="tenant-a").build_context(_requirement())

    assert [supplier["supplier_id"] for supplier in context.suppliers] == ["SUP-000001"]
    assert context.suppliers[0]["name"] == "Verified Mill"
    assert context.historical_rfqs == []
    assert context.historical_quotations == []
    assert context.user_preferences == []
    assert context.approval_history == []
    assert len(captured) == 1
    assert captured[0].url.path == "/api/data/suppliers"
    assert captured[0].headers["X-Service-Tenant-ID"] == "tenant-a"
    assert captured[0].headers["X-Service-Auth"] == "service-secret"


def test_real_giraffe_db_context_rejects_missing_service_auth_before_network(monkeypatch, db_session):
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "https://giraffe-db.test")
    monkeypatch.delenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", raising=False)

    with pytest.raises(GiraffeDBContextError, match="GIRAFFE_DB_CONTEXT_AUTH_REQUIRED"):
        GiraffeDBClient(db_session, tenant_id="tenant-a").build_context(_requirement())


def test_real_giraffe_db_context_rejects_cross_tenant_supplier(monkeypatch, db_session):
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "https://giraffe-db.test")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "service-secret")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [{"tenant_id": "tenant-b", "supplier_id": "SUP-000002", "supplier_name": "Wrong"}],
                "total": 1,
                "limit": 100,
                "offset": 0,
            },
        )

    real_client = httpx.Client

    class PatchedClient(real_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", PatchedClient)
    with pytest.raises(GiraffeDBContextError, match="GIRAFFE_DB_CONTEXT_TENANT_MISMATCH"):
        GiraffeDBClient(db_session, tenant_id="tenant-a").build_context(_requirement())


def test_stub_suppliers_enabled_only_when_configured(monkeypatch, db_session):
    monkeypatch.setenv("AIVAN_ENV", "local")
    clear_registry()

    monkeypatch.setenv("AIVAN_ALLOW_STUB_SUPPLIERS", "true")
    assert stub_suppliers_allowed() is True
    context = GiraffeDBClient(db_session).build_context(_requirement())
    assert context.suppliers  # demo stubs present

    monkeypatch.setenv("AIVAN_ALLOW_STUB_SUPPLIERS", "false")
    context = GiraffeDBClient(db_session).build_context(_requirement())
    assert context.suppliers == []


def test_no_suppliers_returns_pending_supplier_selection():
    feasibility, ready = evaluate_supplier_readiness([])
    assert feasibility == "none"
    assert ready is False


def test_zero_suppliers_pending_selection():
    from aivan.execution.safety import supplier_action

    assert supplier_action([]) == "pending_supplier_selection"


def test_one_supplier_proceeds_without_inventing_additional_candidates():
    from aivan.execution.safety import supplier_action

    action = supplier_action([{"supplier_id": "s1", "email": "a@x.com"}])
    assert action == "proceed"
    assert evaluate_supplier_readiness([{"supplier_id": "s1", "email": "a@x.com"}]) == ("single", True)


def test_two_suppliers_allowed_with_thin_feasibility():
    feasibility, ready = evaluate_supplier_readiness(
        [{"supplier_id": "s1", "email": "a@x.com"}, {"supplier_id": "s2", "email": "b@x.com"}]
    )
    assert feasibility == "thin"
    assert ready is True


def test_less_than_three_suppliers_does_not_error():
    one = evaluate_supplier_readiness([{"supplier_id": "s1", "email": "a@x.com"}])
    two = evaluate_supplier_readiness(
        [{"supplier_id": "s1", "email": "a@x.com"}, {"supplier_id": "s2", "email": "b@x.com"}]
    )
    three = evaluate_supplier_readiness(
        [
            {"supplier_id": "s1", "email": "a@x.com"},
            {"supplier_id": "s2", "email": "b@x.com"},
            {"supplier_id": "s3", "email": "c@x.com"},
        ]
    )
    assert one[0] == "single"
    assert two == ("thin", True)
    assert three == ("sufficient", True)
