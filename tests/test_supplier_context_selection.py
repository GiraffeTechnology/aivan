"""Supplier criteria and complete paginated private-DB reads."""
from __future__ import annotations

import httpx
import pytest

from aivan.integrations.giraffe_db import GiraffeDBClient, GiraffeDBContextError
from aivan.schemas.requirement import BuyerRequirement


def _supplier(number, *, category="hardware", material="steel", tenant="tenant-a"):
    return {
        "supplier_id": f"SUP-{number:06d}",
        "supplier_name": f"Supplier {number}",
        "tenant_id": tenant,
        "categories_json": [category],
        "materials_json": [material],
        "active": True,
    }


def _remote_client(monkeypatch, db_session, handler):
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "https://giraffe-db.test")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "test-service-secret")
    real_client = httpx.Client

    class Client(real_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", Client)
    return GiraffeDBClient(db_session, tenant_id="tenant-a")


@pytest.mark.parametrize(
    ("criteria", "expected"),
    [
        ({"category": "apparel"}, [1]),
        ({"fabric_material": "cotton"}, [2]),
        ({"material_spec": "cotton blend"}, [2]),
        ({"category": "apparel", "fabric_material": "cotton"}, [1, 2]),
        ({}, [1, 2, 3]),
        ({"category": "  APPAREL  "}, [1]),
        ({"category": "unknown"}, []),
    ],
)
def test_only_supplied_criteria_participate_in_supplier_match(
    monkeypatch, db_session, criteria, expected
):
    items = [
        _supplier(1, category="apparel"),
        _supplier(2, material="cotton"),
        _supplier(3),
    ]

    def handler(request):
        return httpx.Response(200, json={"items": items, "total": 3, "limit": 100, "offset": 0})

    client = _remote_client(monkeypatch, db_session, handler)
    found = client.query_suppliers(BuyerRequirement(**criteria))
    assert [s.supplier_id for s in found] == [f"SUP-{n:06d}" for n in expected]


def test_reads_later_supplier_pages_before_requirement_filtering(monkeypatch, db_session):
    records = [_supplier(i) for i in range(100)] + [_supplier(100, category="apparel")]
    requests = []

    def handler(request):
        requests.append(request)
        offset = int(request.url.params["offset"])
        return httpx.Response(200, json={
            "items": records[offset:offset + 100], "total": 101, "limit": 100, "offset": offset,
        })

    client = _remote_client(monkeypatch, db_session, handler)
    found = client.query_suppliers(BuyerRequirement(category="apparel"))
    assert [s.supplier_id for s in found] == ["SUP-000100"]
    assert [int(r.url.params["offset"]) for r in requests] == [0, 100]
    assert all(r.url.params["active"] == "true" for r in requests)
    assert all(r.headers["X-Service-Tenant-ID"] == "tenant-a" for r in requests)
    assert all(r.headers["X-Service-Auth"] == "test-service-secret" for r in requests)


@pytest.mark.parametrize("empty_material", ["", "   "])
def test_empty_supplier_material_is_not_a_material_match(monkeypatch, db_session, empty_material):
    items = [_supplier(1, material=empty_material), _supplier(2, material="cotton")]

    def handler(request):
        return httpx.Response(200, json={"items": items, "total": 2, "limit": 100, "offset": 0})

    client = _remote_client(monkeypatch, db_session, handler)
    found = client.query_suppliers(BuyerRequirement(fabric_material="cotton"))
    assert [s.supplier_id for s in found] == ["SUP-000002"]


def test_uses_provider_page_size_until_reported_total(monkeypatch, db_session):
    records = [_supplier(i, category="apparel") for i in range(5)]
    offsets = []

    def handler(request):
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        return httpx.Response(200, json={
            "items": records[offset:offset + 2], "total": 5, "limit": 2, "offset": offset,
        })

    client = _remote_client(monkeypatch, db_session, handler)
    assert len(client.query_suppliers(BuyerRequirement(category="apparel"))) == 5
    assert offsets == [0, 2, 4]


@pytest.mark.parametrize("failure", ["outage", "tenant", "repeated", "empty", "offset", "total"])
def test_later_page_failure_never_returns_partial_supplier_catalog(monkeypatch, db_session, failure):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={
                "items": [_supplier(1, category="apparel")], "total": 2, "limit": 1, "offset": 0,
            })
        if failure == "outage":
            return httpx.Response(503)
        record = _supplier(2, category="apparel", tenant="tenant-b" if failure == "tenant" else "tenant-a")
        if failure == "repeated":
            record = _supplier(1, category="apparel")
        return httpx.Response(200, json={
            "items": [] if failure == "empty" else [record],
            "total": 3 if failure == "total" else 2,
            "limit": 1, "offset": 0 if failure == "offset" else 1,
        })

    client = _remote_client(monkeypatch, db_session, handler)
    with pytest.raises(GiraffeDBContextError):
        client.query_suppliers(BuyerRequirement(category="apparel"))
    assert calls == 2


@pytest.mark.parametrize("metadata", [
    {}, {"total": True, "limit": 100, "offset": 0},
    {"total": "0", "limit": 100, "offset": 0},
    {"total": -1, "limit": 100, "offset": 0},
    {"total": 0, "limit": 0, "offset": 0},
])
def test_malformed_pagination_is_not_a_complete_catalog(monkeypatch, db_session, metadata):
    def handler(request):
        return httpx.Response(200, json={"items": [], **metadata})

    client = _remote_client(monkeypatch, db_session, handler)
    with pytest.raises(GiraffeDBContextError, match="GIRAFFE_DB_CONTEXT_INVALID_RESPONSE"):
        client.query_suppliers(BuyerRequirement(category="apparel"))


def test_empty_catalog_completes_without_extra_requests(monkeypatch, db_session):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"items": [], "total": 0, "limit": 100, "offset": 0})

    client = _remote_client(monkeypatch, db_session, handler)
    assert client.query_suppliers(BuyerRequirement(category="apparel")) == []
    assert len(calls) == 1


@pytest.mark.parametrize("criteria, expected", [
    ({"category": "textile"}, ["known_sup_guangzhou_textile"]),
    ({"fabric_material": "cotton"}, ["known_sup_shenzhen_apparel", "known_sup_guangzhou_textile"]),
    ({"category": "hardware"}, []),
    ({"fabric_material": "steel"}, []),
    ({}, ["known_sup_shenzhen_apparel", "known_sup_guangzhou_textile"]),
])
def test_local_demo_fallback_uses_the_same_requirement_filter(monkeypatch, db_session, criteria, expected):
    from aivan.sourcing import supplier_registry

    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("AIVAN_ALLOW_STUB_SUPPLIERS", "true")
    monkeypatch.delenv("GIRAFFE_DB_BASE_URL", raising=False)
    monkeypatch.setattr(supplier_registry, "list_active", lambda **kwargs: [])
    found = GiraffeDBClient(db_session, tenant_id="tenant-a").query_suppliers(BuyerRequirement(**criteria))
    assert [supplier.supplier_id for supplier in found] == expected


def test_unmatched_registry_does_not_enable_unrelated_demo_suppliers(monkeypatch, db_session):
    from aivan.sourcing import supplier_registry
    from aivan.sourcing.supplier_models import SupplierProfile

    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("AIVAN_ALLOW_STUB_SUPPLIERS", "true")
    monkeypatch.delenv("GIRAFFE_DB_BASE_URL", raising=False)
    registered = SupplierProfile(supplier_id="local-registry", name="Registered mill", categories=["apparel"])
    monkeypatch.setattr(supplier_registry, "list_active", lambda **kwargs: [registered])
    client = GiraffeDBClient(db_session, tenant_id="tenant-a")
    assert client.query_suppliers(BuyerRequirement(category="hardware")) == []
    assert client.query_suppliers(BuyerRequirement(category="apparel")) == [registered]
