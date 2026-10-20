"""Transport unit regressions, not real DB/service/restart acceptance."""
from __future__ import annotations

import httpx
import pytest

from aivan.domain.roles import normalize_actor_identity
from aivan.integrations.order_confirmation import (
    GiraffeDBOrderConfirmationClient,
    OrderConfirmationError,
)

KEY = "synthetic-recovery-key"
TENANT = "synthetic-recovery-tenant"
OPERATIONS = ("supplier_quotes", "purchase_orders")


def _primary(operation):
    return {"supplier_quotes": "quote_id", "purchase_orders": "po_id"}[operation]


def _path(operation):
    return "/api/data/" + operation.replace("_", "-")


def _record(operation, *, echoes=True):
    result = {_primary(operation): "synthetic-committed-record"}
    if echoes:
        result.update(tenant_id=TENANT, idempotency_key=KEY)
    return result


def _receipt(operation, *, echoes=True):
    record = _record(operation, echoes=echoes)
    return {"status": "committed", "target_id": record[_primary(operation)], "record": record}


def _client(monkeypatch, handler):
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://provider.invalid")
    monkeypatch.delenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", raising=False)
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "synthetic-unit-profile-only")

    def transport(request):
        assert request.headers["X-Service-Tenant-ID"] == TENANT
        assert request.headers["X-Service-Auth"] == "synthetic-unit-profile-only"
        assert request.headers["X-AIVAN-Trace-ID"] == "order_synthetic_recovery"
        assert request.headers["X-AIVAN-Correlation-ID"] == "order_synthetic_recovery"
        if request.method == "POST":
            assert request.headers.get("Idempotency-Key") == KEY
        else:
            assert "Idempotency-Key" not in request.headers
        return handler(request)

    return GiraffeDBOrderConfirmationClient(
        tenant_id=TENANT, trace_id="order_synthetic_recovery",
        transport=httpx.MockTransport(transport),
    )


@pytest.mark.parametrize("operation", OPERATIONS)
def test_lost_ack_and_failed_recovery_keep_unknown_commit_without_second_post(monkeypatch, operation):
    calls = []

    def handle(request):
        calls.append((request.method, request.url.path))
        raise httpx.ReadError("private fixture response must not be exposed", request=request)

    with pytest.raises(OrderConfirmationError) as caught:
        _client(monkeypatch, handle)._post(operation, _path(operation), {}, KEY)
    assert caught.value.code == f"ORDER_CONFIRMATION_INDETERMINATE_COMMIT:{operation}"
    assert str(caught.value) == caught.value.code
    assert calls == [("POST", _path(operation)),
                     ("GET", f"/api/data/write-results/{operation}/{KEY}")]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("malformation", ["empty", "list", "missing-id", "bad-id", "foreign-tenant"])
def test_bad_200_ack_uses_original_receipt_without_repeating_post(monkeypatch, operation, malformation):
    calls = []
    bad = {
        "empty": {}, "list": [], "missing-id": {"status": "committed"},
        "bad-id": {_primary(operation): "../wrong"},
        "foreign-tenant": {**_record(operation), "tenant_id": "foreign-tenant"},
    }[malformation]

    def handle(request):
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(200, json=bad)
        assert request.url.path == f"/api/data/write-results/{operation}/{KEY}"
        return httpx.Response(200, json=_receipt(operation))

    record = _client(monkeypatch, handle)._post(operation, _path(operation), {}, KEY)
    assert record == _record(operation)
    assert calls == ["POST", "GET"]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("malformation", [
    "target", "tenant", "key", "operation-id", "record", "status",
])
def test_receipt_identity_mismatch_is_not_a_commit_ack(monkeypatch, operation, malformation):
    calls = []
    receipt = _receipt(operation)
    if malformation == "target":
        receipt["target_id"] = "another-record"
    elif malformation == "tenant":
        receipt["record"]["tenant_id"] = "foreign-tenant"
    elif malformation == "key":
        receipt["record"]["idempotency_key"] = "another-commercial-key"
    elif malformation == "operation-id":
        receipt["record"] = {_primary("purchase_orders" if operation == "supplier_quotes" else "supplier_quotes"): "wrong-kind"}
    elif malformation == "record":
        receipt["record"] = []
    else:
        receipt["status"] = "pending"

    def handle(request):
        calls.append(request.method)
        if request.method == "POST":
            raise httpx.ReadError("lost response", request=request)
        return httpx.Response(200, json=receipt)

    with pytest.raises(OrderConfirmationError) as caught:
        _client(monkeypatch, handle)._post(operation, _path(operation), {}, KEY)
    assert caught.value.code == f"ORDER_CONFIRMATION_INDETERMINATE_COMMIT:{operation}"
    assert calls == ["POST", "GET"]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("status", [301, 302, 404, 409, 500])
def test_unusable_recovery_http_status_cannot_resend_or_follow_redirect(monkeypatch, operation, status):
    calls = []

    def handle(request):
        calls.append(request.method)
        if request.method == "POST":
            raise httpx.ReadError("lost response", request=request)
        return httpx.Response(status, headers={"Location": "https://untrusted.invalid/"})

    with pytest.raises(OrderConfirmationError) as caught:
        _client(monkeypatch, handle)._post(operation, _path(operation), {}, KEY)
    assert caught.value.code == f"ORDER_CONFIRMATION_INDETERMINATE_COMMIT:{operation}"
    assert calls == ["POST", "GET"]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("recover", [False, True])
def test_request_bound_provider_does_not_need_new_identity_echo_fields(monkeypatch, operation, recover):
    calls = []

    def handle(request):
        calls.append(request.method)
        if request.method == "POST":
            if recover:
                raise httpx.ReadError("lost response", request=request)
            return httpx.Response(200, json=_record(operation, echoes=False))
        return httpx.Response(200, json=_receipt(operation, echoes=False))

    assert _client(monkeypatch, handle)._post(operation, _path(operation), {}, KEY) == _record(operation, echoes=False)
    assert calls == (["POST", "GET"] if recover else ["POST"])


@pytest.mark.parametrize("status,code", [
    (401, "ORDER_CONFIRMATION_DB_AUTH_REJECTED"),
    (403, "ORDER_CONFIRMATION_DB_AUTH_REJECTED"),
    (409, "ORDER_CONFIRMATION_IDEMPOTENCY_CONFLICT"),
    (422, "ORDER_CONFIRMATION_DB_HTTP_422"),
])
def test_definite_post_failures_remain_distinct_and_do_not_query_or_resend(monkeypatch, status, code):
    calls = []

    def handle(request):
        calls.append(request.method)
        return httpx.Response(status, json={"private": "fixture-only downstream body"})

    with pytest.raises(OrderConfirmationError) as caught:
        _client(monkeypatch, handle)._post("supplier_quotes", "/api/data/supplier-quotes", {}, KEY)
    assert caught.value.code == code
    assert str(caught.value) == code
    assert calls == ["POST"]


@pytest.mark.parametrize("status", [404, 503, 302, 200])
def test_readback_failure_after_writes_keeps_indeterminate_semantics(monkeypatch, status):
    calls = []

    def handle(request):
        calls.append(request.method)
        return httpx.Response(status, content=b"non-JSON readback")

    with pytest.raises(OrderConfirmationError) as caught:
        _client(monkeypatch, handle)._read_after_write(
            "/api/data/purchase-orders/synthetic-po", not_found_code="ORDER_CONFIRMATION_ORDER_READBACK_MISSING",
        )
    assert caught.value.code == "ORDER_CONFIRMATION_INDETERMINATE_COMMIT:readback"
    assert calls == ["GET"]


def test_unknown_quote_commit_does_not_advance_to_a_purchase_order_write(monkeypatch):
    calls = []
    posted_keys = []

    def handle(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/data/procurement-cases/synthetic-case/transaction-graph":
            return httpx.Response(200, json={
                "procurement_case": {"procurement_case_id": "synthetic-case", "buyer_id": "synthetic-buyer"},
                "rfqs": [{"id": "synthetic-rfq"}],
            })
        # Exercise actual confirm_order control flow, without claiming a real
        # provider commit, database transaction or cross-service acceptance.
        raise httpx.ReadError("response lost", request=request)

    client = _client(monkeypatch, handle)
    # confirm_order's existing commercial key is stable per selected option;
    # capture it rather than requiring the private-helper fixture key above.
    def transport(request):
        assert request.headers["X-Service-Tenant-ID"] == TENANT
        assert request.headers["X-Service-Auth"] == "synthetic-unit-profile-only"
        assert request.headers["X-AIVAN-Correlation-ID"] == "order_synthetic_recovery"
        if request.method == "POST":
            posted_keys.append(request.headers["Idempotency-Key"])
            assert posted_keys[-1].startswith("aivan-order:")
        elif "/write-results/" in request.url.path:
            assert request.url.path.rsplit("/", 1)[-1] == posted_keys[-1]
        return handle(request)
    client._transport = httpx.MockTransport(transport)
    with pytest.raises(OrderConfirmationError) as caught:
        client.confirm_order(
            project_id="synthetic-project",
            graph_reference={"procurement_case_id": "synthetic-case", "rfq_id": "synthetic-rfq"},
            selected_option={"option_id": "synthetic-option", "supplier_id": "synthetic-supplier"},
            identity=normalize_actor_identity(actor_id="synthetic-human", business_role="approver",
                execution_mode="approval", authorization_basis="synthetic-unit-only"),
            request_key="synthetic-browser-attempt",
        )
    assert caught.value.code == "ORDER_CONFIRMATION_INDETERMINATE_COMMIT:supplier_quotes"
    assert len(calls) == 3
    assert calls[0] == ("GET", "/api/data/procurement-cases/synthetic-case/transaction-graph")
    assert calls[1] == ("POST", "/api/data/supplier-quotes")
    assert calls[2][0] == "GET" and calls[2][1].startswith("/api/data/write-results/supplier_quotes/")
    assert all("purchase-orders" not in path for _, path in calls)
