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
        self.service_auth = os.environ.get(
            "GIRAFFE_DB_SERVICE_AUTH_SECRET", ""
        ).strip()
        self.timeout = float(os.environ.get("GIRAFFE_DB_TIMEOUT_SECONDS", "10"))
        self._transport = transport if transport is not None else _DEFAULT_TRANSPORT
        reject_test_transport_in_production(
            self._transport, component="giraffe-db-order-confirmation"
        )
        if not self.base_url:
            raise OrderConfirmationError("ORDER_CONFIRMATION_DB_ENDPOINT_REQUIRED")
        if not self.service_auth:
            raise OrderConfirmationError("ORDER_CONFIRMATION_DB_AUTH_REQUIRED")
        try:
            self.service_auth.encode("ascii")
        except UnicodeEncodeError as exc:
            raise OrderConfirmationError("ORDER_CONFIRMATION_DB_AUTH_INVALID") from exc

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
        encoded_key = quote_path_segment(idempotency_key, safe="")
        response = self._request(
            "GET", f"/api/data/write-results/{operation}/{encoded_key}"
        )
        if response.status_code == 404:
            raise OrderConfirmationError(
                f"ORDER_CONFIRMATION_INDETERMINATE_COMMIT:{operation}"
            )
        if response.status_code != 200:
            raise OrderConfirmationError(
                f"ORDER_CONFIRMATION_INDETERMINATE_COMMIT:{operation}"
            )
        payload = self._json_object(
            response, code=f"ORDER_CONFIRMATION_INDETERMINATE_COMMIT:{operation}"
        )
        record = payload.get("record")
        if payload.get("status") != "committed" or not isinstance(record, dict):
            raise OrderConfirmationError(
                f"ORDER_CONFIRMATION_INDETERMINATE_COMMIT:{operation}"
            )
        return record

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
                return self._json_object(
                    response, code="ORDER_CONFIRMATION_DB_INVALID_RESPONSE"
                )
            except OrderConfirmationError:
                return self._recover_write(operation, idempotency_key)
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
        return OrderConfirmationResult(
            procurement_case_id=procurement_case_id,
            rfq_id=_provider_id(
                order_readback.get("rfq_id"),
                code="ORDER_CONFIRMATION_READBACK_MISMATCH",
            ),
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

        return OrderConfirmationResult(
            procurement_case_id=procurement_case_id,
            rfq_id=rfq_id,
            supplier_quote_id=supplier_quote_id,
            purchase_order_id=purchase_order_id,
            status="confirmed",
            readback_verified=True,
        )
