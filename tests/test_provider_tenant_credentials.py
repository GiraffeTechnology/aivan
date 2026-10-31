"""Synthetic credential-selection contracts; no live-provider acceptance claims."""
from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from aivan.integrations.attachment_client import AttachmentClient, AttachmentError
from aivan.integrations.giraffe_db import (
    GiraffeDBClient, GiraffeDBContextError, _giraffe_db_service_headers,
)
from aivan.integrations.order_confirmation import (
    GiraffeDBOrderConfirmationClient, OrderConfirmationError,
)
from aivan.schemas.requirement import BuyerRequirement
from tests.test_order_confirmation import (
    AUTH, CASE_ID, RFQ_ID, TENANT, ProviderContractFixture, _identity, _option,
)

CONSUMERS = ("context", "graph", "order", "attachment")
TENANT_KEYS = {"tenant-alpha": "synthetic-key-alpha", "tenant-beta": "synthetic-key-beta"}


@pytest.fixture(autouse=True)
def synthetic_configuration(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://127.0.0.1:9876")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "synthetic-shared-key")
    monkeypatch.delenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", raising=False)


def selected_auth(consumer: str, tenant: str) -> str:
    if consumer == "context":
        GiraffeDBClient(None, tenant_id=tenant)._validate_context_configuration()
        return _giraffe_db_service_headers(tenant, require_auth=True)["X-Service-Auth"]
    if consumer == "graph":
        headers = _giraffe_db_service_headers(tenant, "synthetic-operation-key")
        assert headers["Idempotency-Key"] == "synthetic-operation-key"
        assert headers["X-Service-Tenant-ID"] == tenant
        return headers.get("X-Service-Auth", "")
    if consumer == "order":
        client = GiraffeDBOrderConfirmationClient(tenant_id=tenant, trace_id="synthetic-trace")
        headers = client._headers(idempotency_key="synthetic-operation-key")
        assert headers["X-Service-Tenant-ID"] == tenant
        assert headers["X-AIVAN-Trace-ID"] == headers["X-AIVAN-Correlation-ID"] == "synthetic-trace"
        assert headers["Idempotency-Key"] == "synthetic-operation-key"
        return headers["X-Service-Auth"]
    return AttachmentClient(tenant, "synthetic-trace").auth


@pytest.mark.parametrize("consumer", CONSUMERS)
@pytest.mark.parametrize("tenant", TENANT_KEYS)
def test_synthetic_map_selects_only_requested_tenant(monkeypatch, consumer, tenant):
    monkeypatch.setenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", json.dumps(TENANT_KEYS))
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "unsafe\nignored-shared-key")
    assert selected_auth(consumer, tenant) == TENANT_KEYS[tenant]


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_synthetic_shared_key_mode_requires_map_absent(consumer):
    assert selected_auth(consumer, "tenant-alpha") == "synthetic-shared-key"


INVALID_MAPS = [
    "", " ", "not-json", "null", "[]", '"text"', "true", "42", "{}",
    '{"tenant-alpha":"first","tenant-alpha":"second"}',
    json.dumps({"tenant-beta": "sensitive-fixture-marker"}),
    *[json.dumps({"tenant-alpha": value}) for value in (
        None, True, 7, [], {}, "", " ", " leading", "trailing ", "internal space",
        "key\rheader", "key\nheader", "key\theader", "key\x00header", "key\x7fheader", "key\u00e9",
    )],
    *[json.dumps({"tenant-alpha": "sensitive-fixture-marker", key: "key"})
      for key in ("", " ", "tenant/invalid", "tenant\ninvalid", "tenant\u00e9")],
    json.dumps({"tenant-alpha": "sensitive-fixture-marker", "tenant-beta": None}),
]


@pytest.mark.parametrize("consumer", CONSUMERS)
@pytest.mark.parametrize("raw_mapping", INVALID_MAPS)
def test_synthetic_bad_map_fails_before_network_without_shared_fallback(monkeypatch, consumer, raw_mapping):
    monkeypatch.setenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", raw_mapping)
    def forbidden_client(*args, **kwargs):
        pytest.fail("Invalid credential configuration must not create an HTTP client")
    monkeypatch.setattr(httpx, "Client", forbidden_client)
    with pytest.raises((GiraffeDBContextError, OrderConfirmationError, AttachmentError)) as failure:
        selected_auth(consumer, "tenant-alpha")
    assert "sensitive-fixture-marker" not in str(failure.value)
    assert failure.value.__suppress_context__ is True


@pytest.mark.parametrize("consumer", CONSUMERS)
@pytest.mark.parametrize("secret", [" ", " leading", "trailing ", "internal space", "key\r", "key\n", "key\t", "key\x7f", "key\u00e9"])
def test_synthetic_unsafe_shared_secret_fails_closed(monkeypatch, consumer, secret):
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", secret)
    with pytest.raises((GiraffeDBContextError, OrderConfirmationError, AttachmentError)):
        selected_auth(consumer, "tenant-alpha")


def test_synthetic_context_http_uses_map_and_checks_response_tenant(monkeypatch):
    monkeypatch.setenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", json.dumps(TENANT_KEYS))
    observed = []
    wrong_tenant = False
    def handler(request):
        observed.append(request)
        assert request.headers["X-Service-Tenant-ID"] == "tenant-beta"
        assert request.headers["X-Service-Auth"] == TENANT_KEYS["tenant-beta"]
        return httpx.Response(200, json={"total": 1, "offset": 0, "limit": 100, "items": [{
            "tenant_id": "tenant-alpha" if wrong_tenant else "tenant-beta",
            "supplier_id": "supplier-synthetic", "supplier_name": "Synthetic mill",
            "categories_json": ["apparel"],
        }]})
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)))
    client = GiraffeDBClient(None, tenant_id="tenant-beta")
    assert len(client.query_suppliers(BuyerRequirement(category="apparel"))) == 1
    wrong_tenant = True
    with pytest.raises(GiraffeDBContextError, match="GIRAFFE_DB_CONTEXT_TENANT_MISMATCH"):
        client.query_suppliers(BuyerRequirement(category="apparel"))
    assert len(observed) == 2


@pytest.mark.parametrize("lost_reply", [False, True])
def test_synthetic_order_map_preserves_commit_recovery_and_readback(monkeypatch, lost_reply):
    monkeypatch.setenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", json.dumps({TENANT: AUTH, "tenant-other": "synthetic-other"}))
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "")
    fixture = ProviderContractFixture(fail_quote_after_commit=lost_reply)
    client = GiraffeDBOrderConfirmationClient(
        tenant_id=TENANT, trace_id="order_synthetic_map", transport=httpx.MockTransport(fixture),
    )
    kwargs = dict(project_id="project-synthetic", graph_reference={"procurement_case_id": CASE_ID, "rfq_id": RFQ_ID},
                  selected_option=_option(), identity=_identity(), request_key="synthetic-retry")
    first = client.confirm_order(**kwargs)
    replay = client.confirm_order(**kwargs)
    assert first == replay
    assert first.readback_verified is True
    assert len(fixture.quotes) == len(fixture.orders) == 1
    assert len(fixture.write_results) == 2


def test_synthetic_attachment_map_preserves_readback_and_idempotency(monkeypatch):
    monkeypatch.setenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", json.dumps(TENANT_KEYS))
    monkeypatch.delenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", raising=False)
    content = b"Synthetic cotton shirt specification"
    metadata = {"tenant_id": "tenant-beta", "procurement_case_id": "case-synthetic", "attachment_id": "attachment-synthetic",
                "file_name": "spec.txt", "content_type": "text/plain", "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    requests = []
    def handler(request):
        requests.append(request)
        assert request.headers["X-Service-Tenant-ID"] == "tenant-beta"
        assert request.headers["X-Service-Auth"] == TENANT_KEYS["tenant-beta"]
        assert request.headers["X-AIVAN-Trace-ID"] == request.headers["X-AIVAN-Correlation-ID"] == "synthetic-trace"
        if request.method == "POST":
            assert request.headers["Idempotency-Key"] == "synthetic-key"
            assert json.loads(request.content)["sha256"] == metadata["sha256"]
            return httpx.Response(201, json=metadata)
        if request.url.path.endswith("/content"):
            return httpx.Response(200, content=content)
        return httpx.Response(200, json=metadata)
    client = AttachmentClient("tenant-beta", "synthetic-trace", transport=httpx.MockTransport(handler))
    assert client.create("case-synthetic", "spec.txt", "text/plain", content, "synthetic-key") == metadata
    assert client.content("attachment-synthetic", "case-synthetic") == (metadata, content)
    assert len(requests) == 4
