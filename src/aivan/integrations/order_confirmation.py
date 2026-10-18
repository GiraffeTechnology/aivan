"""Tenant-bound order confirmation through the giraffe-db Data API.

Aivan owns the human action and workflow projection. giraffe-db remains the
authoritative store for the selected supplier quote and confirmed order.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote as quote_path_segment

import httpx

from aivan.domain.roles import ActorIdentity
from aivan.integrations.giraffe_db_auth import ServiceAuthError, service_auth_for_tenant
from aivan.integrations.transport_safety import reject_test_transport_in_production


_SAFE_PROVIDER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_DEFAULT_TRANSPORT: httpx.BaseTransport | None = None


class OrderConfirmationError(RuntimeError):
    """Stable, non-sensitive failure from the order-confirmation dependency."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OrderConfirmationResult:
    procurement_case_id: str
    rfq_id: str
    supplier_quote_id: str
    purchase_order_id: str
    status: str
    readback_verified: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "procurement_case_id": self.procurement_case_id,
            "rfq_id": self.rfq_id,
            "supplier_quote_id": self.supplier_quote_id,
            "purchase_order_id": self.purchase_order_id,
            "status": self.status,
            "readback_verified": self.readback_verified,
        }


def set_order_confirmation_transport(transport: httpx.BaseTransport | None) -> None:
    """Install a test-only transport; production rejects transport overrides."""

    reject_test_transport_in_production(
        transport, component="giraffe-db-order-confirmation"
    )
    global _DEFAULT_TRANSPORT
    _DEFAULT_TRANSPORT = transport


def _provider_id(value: Any, *, code: str) -> str:
    normalized = str(value or "").strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or not _SAFE_PROVIDER_ID.fullmatch(normalized)
    ):
        raise OrderConfirmationError(code)
    return normalized


class GiraffeDBOrderConfirmationClient:
    """Persist and reconcile one human-authorized order confirmation."""

    def __init__(
        self,
        *,
        tenant_id: str,
        trace_id: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.tenant_id = _provider_id(
            tenant_id, code="ORDER_CONFIRMATION_TENANT_REQUIRED"
        )
        self.trace_id = _provider_id(
            trace_id, code="ORDER_CONFIRMATION_TRACE_REQUIRED"
        )
        self.base_url = os.environ.get("GIRAFFE_DB_BASE_URL", "").strip().rstrip("/")
        self.timeout = float(os.environ.get("GIRAFFE_DB_TIMEOUT_SECONDS", "10"))
        self._transport = transport if transport is not None else _DEFAULT_TRANSPORT
        reject_test_transport_in_production(
            self._transport, component="giraffe-db-order-confirmation"
        )
        if not self.base_url:
            raise OrderConfirmationError("ORDER_CONFIRMATION_DB_ENDPOINT_REQUIRED")
        try:
            self.service_auth = service_auth_for_tenant(self.tenant_id)
        except ServiceAuthError as exc:
            raise OrderConfirmationError(
                f"ORDER_CONFIRMATION_DB_AUTH_{exc.reason.upper()}"
            ) from None

    def _headers(self, *, idempotency_key: str = "") -> dict[str, str]:
        headers = {
            "X-Service-Tenant-ID": self.tenant_id,
            "X-Service-Auth": self.service_auth,
            "X-AIVAN-Trace-ID": self.trace_id,
            "X-AIVAN-Correlation-ID": self.trace_id,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            with httpx.Client(
                timeout=self.timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                return client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=payload,
                    headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            raise OrderConfirmationError(
                "ORDER_CONFIRMATION_DB_UNAVAILABLE"
            ) from exc

    @staticmethod
    def _json_object(response: httpx.Response, *, code: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise OrderConfirmationError(code) from exc
        if not isinstance(payload, dict):
            raise OrderConfirmationError(code)
        return payload

    def _get(self, path: str, *, not_found_code: str) -> dict[str, Any]:
        response = self._request("GET", path)
        if response.status_code == 404:
            raise OrderConfirmationError(not_found_code)
        if response.status_code != 200:
            raise OrderConfirmationError(
                f"ORDER_CONFIRMATION_DB_HTTP_{response.status_code}"
            )
        return self._json_object(
            response, code="ORDER_CONFIRMATION_DB_INVALID_RESPONSE"
        )

    def _recover_write(self, operation: str, idempotency_key: str) -> dict[str, Any]:
        code = f"ORDER_CONFIRMATION_INDETERMINATE_COMMIT:{operation}"
        encoded_key = quote_path_segment(idempotency_key, safe="")
        try:
            response = self._request(
                "GET", f"/api/data/write-results/{operation}/{encoded_key}"
            )
        except OrderConfirmationError:
            # A failed recovery read cannot establish that the earlier POST
            # failed or authorize creating a different commercial operation.
            raise OrderConfirmationError(code) from None
        if response.status_code != 200:
            raise OrderConfirmationError(code)
        payload = self._json_object(response, code=code)
        record = payload.get("record")
        primary_key = {"supplier_quotes": "quote_id", "purchase_orders": "po_id"}.get(operation)
        if (primary_key is None or payload.get("status") != "committed"
                or not self._valid_write_record(record, operation, idempotency_key)
                or payload.get("target_id") != record[primary_key]):
            raise OrderConfirmationError(code)
        return record

    def _valid_write_record(self, record, operation: str, idempotency_key: str) -> bool:
        primary_key = {"supplier_quotes": "quote_id", "purchase_orders": "po_id"}.get(operation)
        if not isinstance(record, dict) or primary_key is None:
            return False
        value = record.get(primary_key)
        if not isinstance(value, str) or not _SAFE_PROVIDER_ID.fullmatch(value):
            return False
        # Trust the authenticated tenant/key-scoped endpoint. Compatible
        # providers need not add echoes; if supplied, they must not disagree.
        if "tenant_id" in record and record["tenant_id"] != self.tenant_id:
            return False
        if "idempotency_key" in record and record["idempotency_key"] != idempotency_key:
            return False
        return True

    def _read_after_write(self, path: str, *, not_found_code: str) -> dict[str, Any]:
        try:
            return self._get(path, not_found_code=not_found_code)
        except OrderConfirmationError:
            # Both provider writes have returned a record. Missing/unavailable
            # readback is not evidence that those writes did not commit.
            raise OrderConfirmationError(
                "ORDER_CONFIRMATION_INDETERMINATE_COMMIT:readback"
            ) from None

    def _verify_readback_links(
        self, quote: dict, order: dict, graph: dict, *, case_id: str,
        quote_id: str, order_id: str, rfq_id: str | None = None,
        supplier_id: str | None = None,
    ) -> str:
        """Reject contradictory evidence without requiring new provider echoes."""
        code = "ORDER_CONFIRMATION_READBACK_MISMATCH"

        def check(record, expected):
            if not isinstance(record, dict) or any(
                key in record and record[key] != value for key, value in expected.items()
            ):
                raise OrderConfirmationError(code)

        case = graph.get("procurement_case")
        if not isinstance(case, dict) or case.get("procurement_case_id") != case_id:
            raise OrderConfirmationError(code)
        check(case, {"tenant_id": self.tenant_id})
        rfq_id = rfq_id or _provider_id(order.get("rfq_id"), code=code)
        supplier_id = supplier_id or quote.get("supplier_id") or order.get("supplier_id")
        common = {"tenant_id": self.tenant_id, "procurement_case_id": case_id, "rfq_id": rfq_id}
        if supplier_id is not None:
            common["supplier_id"] = supplier_id
        check(quote, common)
        check(order, common)
        if case.get("buyer_id") is not None:
            check(order, {"buyer_id": case["buyer_id"]})
        for row in graph.get("supplier_quotes", []):
            if isinstance(row, dict) and row.get("quote_id") == quote_id:
                check(row, common)
        for row in graph.get("purchase_orders", []):
            if isinstance(row, dict) and row.get("po_id") == order_id:
                check(row, {**common, "selected_quote_id": quote_id, "status": "confirmed"})
        # The graph may omit optional collections, but supplied relationships
        # must agree with the exact direct-record readback.
        if "rfqs" in graph:
            rfqs = graph["rfqs"]
            matches = [row for row in rfqs if isinstance(row, dict) and row.get("id") == rfq_id] if isinstance(rfqs, list) else []
            if not matches:
                raise OrderConfirmationError(code)
            for row in matches:
                check(row, {"tenant_id": self.tenant_id, "procurement_case_id": case_id})
        return rfq_id

    def _post(
        self,
        operation: str,
        path: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        try:
            with httpx.Client(
                timeout=self.timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.post(
                    f"{self.base_url}{path}",
                    json=payload,
                    headers=self._headers(idempotency_key=idempotency_key),
                )
        except httpx.HTTPError:
            return self._recover_write(operation, idempotency_key)

        if response.status_code == 200:
            try:
                record = self._json_object(
                    response, code="ORDER_CONFIRMATION_DB_INVALID_RESPONSE"
                )
            except OrderConfirmationError:
                return self._recover_write(operation, idempotency_key)
            if not self._valid_write_record(record, operation, idempotency_key):
                return self._recover_write(operation, idempotency_key)
            return record
        if response.status_code in {401, 403}:
            raise OrderConfirmationError("ORDER_CONFIRMATION_DB_AUTH_REJECTED")
        if response.status_code == 409:
            raise OrderConfirmationError("ORDER_CONFIRMATION_IDEMPOTENCY_CONFLICT")
        if 400 <= response.status_code < 500:
            raise OrderConfirmationError(
                f"ORDER_CONFIRMATION_DB_HTTP_{response.status_code}"
            )
        return self._recover_write(operation, idempotency_key)

    def _operation_key(
        self, *, project_id: str, option_id: str, request_key: str, operation: str
    ) -> str:
        # The business action is keyed by the selected option version, not by a
        # transient HTTP attempt. A browser/process restart must resume the
        # same provider writes instead of creating another quote or order.
        _provider_id(
            request_key, code="ORDER_CONFIRMATION_IDEMPOTENCY_KEY_REQUIRED"
        )
        material = f"{self.tenant_id}\0{project_id}\0{option_id}\0{operation}".encode(
            "utf-8"
        )
        return f"aivan-order:{hashlib.sha256(material).hexdigest()}"

    def reconcile_order(
        self,
        *,
        procurement_case_id: str,
        supplier_quote_id: str,
        purchase_order_id: str,
    ) -> OrderConfirmationResult:
        """Re-read a previously confirmed order from the authoritative DB."""

        procurement_case_id = _provider_id(
            procurement_case_id, code="ORDER_CONFIRMATION_DB_GRAPH_REQUIRED"
        )
        supplier_quote_id = _provider_id(
            supplier_quote_id, code="ORDER_CONFIRMATION_QUOTE_RESPONSE_INVALID"
        )
        purchase_order_id = _provider_id(
            purchase_order_id, code="ORDER_CONFIRMATION_ORDER_RESPONSE_INVALID"
        )
        quote_readback = self._get(
            f"/api/data/supplier-quotes/{quote_path_segment(supplier_quote_id, safe='')}",
            not_found_code="ORDER_CONFIRMATION_QUOTE_READBACK_MISSING",
        )
        order_readback = self._get(
            f"/api/data/purchase-orders/{quote_path_segment(purchase_order_id, safe='')}",
            not_found_code="ORDER_CONFIRMATION_ORDER_READBACK_MISSING",
        )
        final_graph = self._get(
            f"/api/data/procurement-cases/{quote_path_segment(procurement_case_id, safe='')}/transaction-graph",
            not_found_code="ORDER_CONFIRMATION_DB_GRAPH_NOT_FOUND",
        )
        if (
            quote_readback.get("quote_id") != supplier_quote_id
            or order_readback.get("po_id") != purchase_order_id
            or order_readback.get("selected_quote_id") != supplier_quote_id
            or order_readback.get("status") != "confirmed"
        ):
            raise OrderConfirmationError("ORDER_CONFIRMATION_READBACK_MISMATCH")
        graph_quotes = final_graph.get("supplier_quotes")
        graph_orders = final_graph.get("purchase_orders")
        if not isinstance(graph_quotes, list) or not any(
            isinstance(item, dict) and item.get("quote_id") == supplier_quote_id
            for item in graph_quotes
        ):
            raise OrderConfirmationError("ORDER_CONFIRMATION_GRAPH_QUOTE_MISSING")
        if not isinstance(graph_orders, list) or not any(
            isinstance(item, dict) and item.get("po_id") == purchase_order_id
            for item in graph_orders
        ):
            raise OrderConfirmationError("ORDER_CONFIRMATION_GRAPH_ORDER_MISSING")
        rfq_id = self._verify_readback_links(
            quote_readback, order_readback, final_graph,
            case_id=procurement_case_id, quote_id=supplier_quote_id, order_id=purchase_order_id,
        )
        return OrderConfirmationResult(
            procurement_case_id=procurement_case_id,
            rfq_id=rfq_id,
            supplier_quote_id=supplier_quote_id,
            purchase_order_id=purchase_order_id,
            status="confirmed",
            readback_verified=True,
        )

    def confirm_order(
        self,
        *,
        project_id: str,
        graph_reference: dict[str, Any],
        selected_option: dict[str, Any],
        identity: ActorIdentity,
        request_key: str,
    ) -> OrderConfirmationResult:
        """Persist quote and order, then verify direct and graph readback."""

        project_id = _provider_id(
            project_id, code="ORDER_CONFIRMATION_PROJECT_REQUIRED"
        )
        request_key = _provider_id(
            request_key, code="ORDER_CONFIRMATION_IDEMPOTENCY_KEY_REQUIRED"
        )
        procurement_case_id = _provider_id(
            graph_reference.get("procurement_case_id"),
            code="ORDER_CONFIRMATION_DB_GRAPH_REQUIRED",
        )
        rfq_id = _provider_id(
            graph_reference.get("rfq_id"),
            code="ORDER_CONFIRMATION_DB_GRAPH_REQUIRED",
        )
        option_id = _provider_id(
            selected_option.get("option_id"),
            code="ORDER_CONFIRMATION_SELECTED_OPTION_REQUIRED",
        )
        supplier_id = _provider_id(
            selected_option.get("supplier_id"),
            code="ORDER_CONFIRMATION_SUPPLIER_ID_REQUIRED",
        )
        if not identity.actor_id:
            raise OrderConfirmationError("ORDER_CONFIRMATION_ACTOR_REQUIRED")

        graph = self._get(
            f"/api/data/procurement-cases/{quote_path_segment(procurement_case_id, safe='')}/transaction-graph",
            not_found_code="ORDER_CONFIRMATION_DB_GRAPH_NOT_FOUND",
        )
        procurement_case = graph.get("procurement_case")
        if not isinstance(procurement_case, dict):
            raise OrderConfirmationError("ORDER_CONFIRMATION_DB_GRAPH_INVALID")
        if procurement_case.get("procurement_case_id") != procurement_case_id:
            raise OrderConfirmationError("ORDER_CONFIRMATION_DB_GRAPH_MISMATCH")
        buyer_id = _provider_id(
            procurement_case.get("buyer_id"),
            code="ORDER_CONFIRMATION_BUYER_ID_REQUIRED",
        )
        rfqs = graph.get("rfqs")
        if not isinstance(rfqs, list) or not any(
            isinstance(item, dict) and item.get("id") == rfq_id for item in rfqs
        ):
            raise OrderConfirmationError("ORDER_CONFIRMATION_RFQ_NOT_FOUND")

        authorization = {
            "actor_id": identity.actor_id,
            "actor_role": identity.business_role.value,
            "authorization_basis": identity.authorization_basis,
            "source_trace_id": self.trace_id,
        }
        quote_key = self._operation_key(
            project_id=project_id,
            option_id=option_id,
            request_key=request_key,
            operation="supplier_quotes",
        )
        quote_record = self._post(
            "supplier_quotes",
            "/api/data/supplier-quotes",
            {
                "procurement_case_id": procurement_case_id,
                "rfq_id": rfq_id,
                "supplier_id": supplier_id,
                "quote_status": "confirmed",
                "verification_status": "operator_confirmed",
                "source_trace_id": self.trace_id,
                "idempotency_key": quote_key,
                "metadata_json": {
                    "source_system": "aivan",
                    "aivan_project_id": project_id,
                    "selected_option": selected_option,
                    "human_authorization": authorization,
                },
            },
            quote_key,
        )
        supplier_quote_id = _provider_id(
            quote_record.get("quote_id"),
            code="ORDER_CONFIRMATION_QUOTE_RESPONSE_INVALID",
        )

        order_key = self._operation_key(
            project_id=project_id,
            option_id=option_id,
            request_key=request_key,
            operation="purchase_orders",
        )
        order_record = self._post(
            "purchase_orders",
            "/api/data/purchase-orders",
            {
                "procurement_case_id": procurement_case_id,
                "rfq_id": rfq_id,
                "buyer_id": buyer_id,
                "supplier_id": supplier_id,
                "selected_quote_id": supplier_quote_id,
                "status": "confirmed",
                "source_trace_id": self.trace_id,
                "idempotency_key": order_key,
                "metadata_json": {
                    "source_system": "aivan",
                    "aivan_project_id": project_id,
                    "selected_option_id": option_id,
                    "human_authorization": authorization,
                },
            },
            order_key,
        )
        purchase_order_id = _provider_id(
            order_record.get("po_id"),
            code="ORDER_CONFIRMATION_ORDER_RESPONSE_INVALID",
        )

        quote_readback = self._read_after_write(
            f"/api/data/supplier-quotes/{quote_path_segment(supplier_quote_id, safe='')}",
            not_found_code="ORDER_CONFIRMATION_QUOTE_READBACK_MISSING",
        )
        order_readback = self._read_after_write(
            f"/api/data/purchase-orders/{quote_path_segment(purchase_order_id, safe='')}",
            not_found_code="ORDER_CONFIRMATION_ORDER_READBACK_MISSING",
        )
        final_graph = self._read_after_write(
            f"/api/data/procurement-cases/{quote_path_segment(procurement_case_id, safe='')}/transaction-graph",
            not_found_code="ORDER_CONFIRMATION_DB_GRAPH_NOT_FOUND",
        )
        if (
            quote_readback.get("quote_id") != supplier_quote_id
            or quote_readback.get("supplier_id") != supplier_id
            or order_readback.get("po_id") != purchase_order_id
            or order_readback.get("selected_quote_id") != supplier_quote_id
            or order_readback.get("status") != "confirmed"
        ):
            raise OrderConfirmationError("ORDER_CONFIRMATION_READBACK_MISMATCH")
        graph_quotes = final_graph.get("supplier_quotes")
        graph_orders = final_graph.get("purchase_orders")
        if not isinstance(graph_quotes, list) or not any(
            isinstance(item, dict) and item.get("quote_id") == supplier_quote_id
            for item in graph_quotes
        ):
            raise OrderConfirmationError("ORDER_CONFIRMATION_GRAPH_QUOTE_MISSING")
        if not isinstance(graph_orders, list) or not any(
            isinstance(item, dict) and item.get("po_id") == purchase_order_id
            for item in graph_orders
        ):
            raise OrderConfirmationError("ORDER_CONFIRMATION_GRAPH_ORDER_MISSING")

        self._verify_readback_links(
            quote_readback, order_readback, final_graph,
            case_id=procurement_case_id, quote_id=supplier_quote_id, order_id=purchase_order_id,
            rfq_id=rfq_id, supplier_id=supplier_id,
        )
        return OrderConfirmationResult(
            procurement_case_id=procurement_case_id,
            rfq_id=rfq_id,
            supplier_quote_id=supplier_quote_id,
            purchase_order_id=purchase_order_id,
            status="confirmed",
            readback_verified=True,
        )
