"""Contract tests for human order confirmation and giraffe-db readback."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aivan.api.main import app
from aivan.db.models import Base
from aivan.db.models.domain import AuditLogRecord
from aivan.db.models.execution import ExecutionEventRecord
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.db.session import get_db
from aivan.domain.roles import normalize_actor_identity
from aivan.integrations.order_confirmation import (
    GiraffeDBOrderConfirmationClient,
    OrderConfirmationError,
    set_order_confirmation_transport,
)


TENANT = "test_tenant"
AUTH = "giraffe-db-test-auth"
CASE_ID = "case-provider-1"
RFQ_ID = "rfq-provider-1"
BUYER_ID = "buyer-provider-1"
SUPPLIER_ID = "supplier-provider-1"
OPTION_ID = "option-version-1"


class ProviderContractFixture:
    """In-process HTTP contract fixture; not real-service acceptance evidence."""

    def __init__(self, *, fail_quote_after_commit: bool = False):
        self.fail_quote_after_commit = fail_quote_after_commit
        self.quote_failure_emitted = False
        self.quotes: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.write_results: dict[tuple[str, str], dict] = {}
        self.post_calls: list[tuple[str, str]] = []

    def graph(self) -> dict:
        return {
            "procurement_case": {
                "procurement_case_id": CASE_ID,
                "buyer_id": BUYER_ID,
                "tenant_id": TENANT,
            },
            "rfqs": [{"id": RFQ_ID, "procurement_case_id": CASE_ID}],
            "supplier_quotes": list(self.quotes.values()),
            "purchase_orders": list(self.orders.values()),
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Service-Tenant-ID"] == TENANT
        assert request.headers["X-Service-Auth"] == AUTH
        assert request.headers["X-AIVAN-Trace-ID"].startswith("order_")
        path = request.url.path
        if request.method == "GET" and path == f"/api/data/procurement-cases/{CASE_ID}/transaction-graph":
            return httpx.Response(200, json=self.graph())
        if request.method == "GET" and path.startswith("/api/data/supplier-quotes/"):
            record = self.quotes.get(path.rsplit("/", 1)[-1])
            return httpx.Response(200, json=record) if record else httpx.Response(404)
        if request.method == "GET" and path.startswith("/api/data/purchase-orders/"):
            record = self.orders.get(path.rsplit("/", 1)[-1])
            return httpx.Response(200, json=record) if record else httpx.Response(404)
        if request.method == "GET" and path.startswith("/api/data/write-results/"):
            _, operation, key = path.rsplit("/", 2)
            record = self.write_results.get((operation, key))
            if record is None:
                return httpx.Response(404)
            return httpx.Response(
                200,
                json={"status": "committed", "target_id": next(
                    value for name, value in record.items() if name in {"quote_id", "po_id"}
                ), "record": record},
            )
        if request.method != "POST":
            return httpx.Response(404)

        key = request.headers["Idempotency-Key"]
        body = json.loads(request.content)
        if path == "/api/data/supplier-quotes":
            operation = "supplier_quotes"
            existing = self.write_results.get((operation, key))
            if existing is None:
                existing = {**body, "tenant_id": TENANT, "quote_id": "quote-confirmed-1"}
                self.quotes[existing["quote_id"]] = existing
                self.write_results[(operation, key)] = existing
            self.post_calls.append((operation, key))
            if self.fail_quote_after_commit and not self.quote_failure_emitted:
                self.quote_failure_emitted = True
                raise httpx.ReadError("response lost after commit", request=request)
            return httpx.Response(200, json=existing)
        if path == "/api/data/purchase-orders":
            operation = "purchase_orders"
            existing = self.write_results.get((operation, key))
            if existing is None:
                existing = {**body, "tenant_id": TENANT, "po_id": "po-confirmed-1"}
                self.orders[existing["po_id"]] = existing
                self.write_results[(operation, key)] = existing
            self.post_calls.append((operation, key))
            return httpx.Response(200, json=existing)
        return httpx.Response(404)


def _option() -> dict:
    return {
        "option_id": OPTION_ID,
        "supplier_id": SUPPLIER_ID,
        "option_label": "Selected supplier quotation",
        "quote": {"currency": "USD", "buyer_unit_price": 12.5, "quantity": 100},
        "lead_time_estimate": {"p50_days": 12.5, "p80_days": 16.25, "p90_days": 20.75},
    }


def _identity():
    return normalize_actor_identity(
        actor_id="approver-1",
        business_role="approver",
        execution_mode="approval",
        authorization_basis="test-principal",
    )


def _client(monkeypatch, fixture: ProviderContractFixture):
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://giraffe-db.test")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", AUTH)
    return GiraffeDBOrderConfirmationClient(
        tenant_id=TENANT,
        trace_id="order_contract_test",
        transport=httpx.MockTransport(fixture),
    )


def test_order_confirmation_persists_quote_order_and_verified_readback(monkeypatch):
    fixture = ProviderContractFixture()
    client = _client(monkeypatch, fixture)
    result = client.confirm_order(
        project_id="project-1",
        graph_reference={"procurement_case_id": CASE_ID, "rfq_id": RFQ_ID},
        selected_option=_option(),
        identity=_identity(),
        request_key="browser-attempt-1",
    )
    assert result.as_dict() == {
        "procurement_case_id": CASE_ID,
        "rfq_id": RFQ_ID,
        "supplier_quote_id": "quote-confirmed-1",
        "purchase_order_id": "po-confirmed-1",
        "status": "confirmed",
        "readback_verified": True,
    }
    quote = next(iter(fixture.quotes.values()))
    order = next(iter(fixture.orders.values()))
    assert quote["metadata_json"]["selected_option"]["quote"]["buyer_unit_price"] == 12.5
    assert order["selected_quote_id"] == quote["quote_id"]
    assert order["metadata_json"]["human_authorization"]["actor_id"] == "approver-1"


def test_order_confirmation_recovers_response_lost_after_provider_commit(monkeypatch):
    fixture = ProviderContractFixture(fail_quote_after_commit=True)
    result = _client(monkeypatch, fixture).confirm_order(
        project_id="project-1",
        graph_reference={"procurement_case_id": CASE_ID, "rfq_id": RFQ_ID},
        selected_option=_option(),
        identity=_identity(),
        request_key="browser-attempt-1",
    )
    assert result.readback_verified is True
    assert len(fixture.quotes) == len(fixture.orders) == 1


def test_order_confirmation_rejects_missing_supplier_before_any_write(monkeypatch):
    fixture = ProviderContractFixture()
    client = _client(monkeypatch, fixture)
    with pytest.raises(OrderConfirmationError, match="ORDER_CONFIRMATION_SUPPLIER_ID_REQUIRED"):
        client.confirm_order(
            project_id="project-1",
            graph_reference={"procurement_case_id": CASE_ID, "rfq_id": RFQ_ID},
            selected_option={**_option(), "supplier_id": ""},
            identity=_identity(),
            request_key="browser-attempt-1",
        )
    assert fixture.post_calls == []


def test_order_confirmation_does_not_follow_redirect_or_assume_commit(monkeypatch):
    fixture = ProviderContractFixture()

    def redirect_quote(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/data/supplier-quotes":
            return httpx.Response(307, headers={"location": "/untrusted"})
        return fixture(request)

    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://giraffe-db.test")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", AUTH)
    client = GiraffeDBOrderConfirmationClient(
        tenant_id=TENANT,
        trace_id="order_redirect_test",
        transport=httpx.MockTransport(redirect_quote),
    )
    with pytest.raises(
        OrderConfirmationError,
        match="ORDER_CONFIRMATION_INDETERMINATE_COMMIT:supplier_quotes",
    ):
        client.confirm_order(
            project_id="project-1",
            graph_reference={"procurement_case_id": CASE_ID, "rfq_id": RFQ_ID},
            selected_option=_option(),
            identity=_identity(),
            request_key="browser-attempt-1",
        )
    assert fixture.quotes == {}
    assert fixture.orders == {}


@pytest.fixture
def order_api(monkeypatch):
    monkeypatch.setenv("AIVAN_API_KEY", "aivan-api-key")
    monkeypatch.setenv("AIVAN_TENANT_ID", TENANT)
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://giraffe-db.test")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", AUTH)
    fixture = ProviderContractFixture()
    set_order_confirmation_transport(httpx.MockTransport(fixture))
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    project = ProjectRepository(db).create(
        conversation_id="order-confirmation-thread",
        customer_id="buyer-1",
        tenant_id=TENANT,
    )
    project.case_state = "approved"
    project.requirement_json = {
        "giraffe_db_graph": {"procurement_case_id": CASE_ID, "rfq_id": RFQ_ID}
    }
    project.selected_option_json = _option()
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, db, project.project_id, fixture
    finally:
        app.dependency_overrides.clear()
        set_order_confirmation_transport(None)
        db.close()
        engine.dispose()


def _api_headers(*, role: str = "approver", key: str = "confirm-attempt-1") -> dict[str, str]:
    return {
        "X-AIVAN-API-Key": "aivan-api-key",
        "X-AIVAN-Actor-ID": "approver-1",
        "X-AIVAN-Role-Context": role,
        "X-AIVAN-Execution-Mode": "approval",
        "X-AIVAN-Trace-ID": "trace_order_confirmation",
        "Idempotency-Key": key,
    }


def test_workbench_human_confirmation_and_restart_readback(order_api):
    client, db, project_id, fixture = order_api
    first = client.post(
        f"/api/workbench/cases/{project_id}/order-confirmation",
        headers=_api_headers(),
        json={"selected_option_id": OPTION_ID},
    )
    assert first.status_code == 200, first.json()
    assert first.json()["readback_verified"] is True
    assert first.json()["recovered"] is False
    db.expire_all()
    project = ProjectRepository(db).get(project_id, tenant_id=TENANT)
    assert project.status == "order_confirmed"
    assert project.requirement_json["order_confirmation"]["purchase_order_id"] == "po-confirmed-1"
    assert db.query(AuditLogRecord).filter_by(event_type="ORDER_CONFIRMED").count() == 1
    assert db.query(ExecutionEventRecord).filter_by(event_type="ORDER_CONFIRMATION_PERSISTED").count() == 1

    recovered = client.get(
        f"/api/workbench/cases/{project_id}/order-confirmation",
        headers=_api_headers(key="readback-attempt"),
    )
    assert recovered.status_code == 200
    assert recovered.json()["recovered"] is True
    assert recovered.json()["purchase_order_id"] == "po-confirmed-1"

    replay = client.post(
        f"/api/workbench/cases/{project_id}/order-confirmation",
        headers=_api_headers(key="another-browser-attempt"),
        json={"selected_option_id": OPTION_ID},
    )
    assert replay.status_code == 200
    assert replay.json()["recovered"] is True
    assert len(fixture.quotes) == len(fixture.orders) == 1
    assert db.query(AuditLogRecord).filter_by(event_type="ORDER_CONFIRMED").count() == 1


def test_workbench_order_confirmation_denies_non_approver_without_provider_write(order_api):
    client, _db, project_id, fixture = order_api
    response = client.post(
        f"/api/workbench/cases/{project_id}/order-confirmation",
        headers=_api_headers(role="buyer"),
        json={"selected_option_id": OPTION_ID},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "ORDER_CONFIRMATION_FORBIDDEN"
    assert fixture.post_calls == []


def test_workbench_order_confirmation_missing_provider_config_is_structured_503(
    order_api, monkeypatch
):
    client, _db, project_id, fixture = order_api
    monkeypatch.delenv("GIRAFFE_DB_BASE_URL")
    response = client.post(
        f"/api/workbench/cases/{project_id}/order-confirmation",
        headers=_api_headers(),
        json={"selected_option_id": OPTION_ID},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "error": "ORDER_CONFIRMATION_DB_ENDPOINT_REQUIRED"
    }
    assert fixture.post_calls == []
