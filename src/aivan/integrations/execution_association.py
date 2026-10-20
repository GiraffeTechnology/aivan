"""Read an existing provider association; never create an execution projection."""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from aivan.integrations.order_confirmation import (
    GiraffeDBOrderConfirmationClient,
    OrderConfirmationError,
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


class ExecutionAssociationError(RuntimeError):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ExecutionAssociationError(409, "EXECUTION_SOURCE_REFERENCE_INVALID")
    return value


def _uuid(value: Any) -> str:
    if not isinstance(value, str):
        raise ExecutionAssociationError(502, "EXECUTION_ASSOCIATION_ID_INVALID")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise ExecutionAssociationError(502, "EXECUTION_ASSOCIATION_ID_INVALID") from None
    if str(parsed) != value or parsed.int == 0:
        raise ExecutionAssociationError(502, "EXECUTION_ASSOCIATION_ID_INVALID")
    return value


class ExecutionAssociationReader:
    """Use only GETs and the existing tenant-bound provider transport identity."""

    def __init__(self, client: GiraffeDBOrderConfirmationClient):
        self.client = client

    def _get(self, path: str) -> dict[str, Any]:
        try:
            response = self.client._request("GET", path)
        except OrderConfirmationError:
            raise ExecutionAssociationError(503, "EXECUTION_PROVIDER_UNAVAILABLE") from None
        if response.status_code == 404:
            raise ExecutionAssociationError(404, "EXECUTION_ASSOCIATION_NOT_FOUND")
        if response.status_code in {401, 403}:
            raise ExecutionAssociationError(503, "EXECUTION_PROVIDER_AUTH_REJECTED")
        if response.status_code == 409:
            raise ExecutionAssociationError(409, "EXECUTION_SOURCE_CHANGED")
        if response.status_code >= 500:
            raise ExecutionAssociationError(503, "EXECUTION_PROVIDER_UNAVAILABLE")
        if response.status_code != 200:
            raise ExecutionAssociationError(502, "EXECUTION_PROVIDER_RESPONSE_INVALID")
        try:
            result = response.json()
        except ValueError:
            raise ExecutionAssociationError(502, "EXECUTION_PROVIDER_RESPONSE_INVALID") from None
        if not isinstance(result, dict):
            raise ExecutionAssociationError(502, "EXECUTION_PROVIDER_RESPONSE_INVALID")
        return result

    def _order(self, order, expected):
        if order.get("tenant_id") != self.client.tenant_id:
            raise ExecutionAssociationError(404, "EXECUTION_ASSOCIATION_NOT_FOUND")
        if any(order.get(key) != value for key, value in expected.items()):
            raise ExecutionAssociationError(409, "EXECUTION_SOURCE_CHANGED")
        if order.get("status") != "confirmed":
            raise ExecutionAssociationError(409, "EXECUTION_SOURCE_NOT_CONFIRMED")
        metadata = order.get("metadata_json")
        if not isinstance(metadata, dict):
            raise ExecutionAssociationError(502, "EXECUTION_PROVIDER_RESPONSE_INVALID")
        source_hash = order.get("source_snapshot_hash")
        revision = order.get("execution_revision")
        if (not isinstance(source_hash, str) or not _HASH.fullmatch(source_hash)
                or type(revision) is not int or revision < 0):
            raise ExecutionAssociationError(502, "EXECUTION_PROVIDER_RESPONSE_INVALID")
        return source_hash, revision, metadata

    def read(self, *, case_id: str, confirmation: dict, graph: dict) -> dict:
        # References come from the authorized case, never a caller's PO/order query.
        case_id = _identifier(case_id)
        po_id = _identifier(confirmation.get("purchase_order_id"))
        quote_id = _identifier(confirmation.get("supplier_quote_id"))
        case_ref = _identifier(confirmation.get("procurement_case_id"))
        rfq_id = _identifier(confirmation.get("rfq_id"))
        if (confirmation.get("status") != "confirmed"
                or graph.get("procurement_case_id") != case_ref
                or graph.get("rfq_id") != rfq_id):
            raise ExecutionAssociationError(409, "EXECUTION_SOURCE_REFERENCE_INVALID")
        expected = {"po_id": po_id, "procurement_case_id": case_ref,
                    "rfq_id": rfq_id, "selected_quote_id": quote_id}
        path = f"/api/data/purchase-orders/{po_id}"
        first = self._get(path)
        source_hash, revision, metadata = self._order(first, expected)
        if metadata.get("aivan_project_id") != case_id:
            raise ExecutionAssociationError(404, "EXECUTION_ASSOCIATION_NOT_FOUND")
        envelope = self._get(f"{path}/execution-state")
        if envelope.get("tenant_id") != self.client.tenant_id:
            raise ExecutionAssociationError(404, "EXECUTION_ASSOCIATION_NOT_FOUND")
        if (envelope.get("po_id") != po_id
                or type(envelope.get("revision")) is not int
                or envelope["revision"] != revision
                or envelope.get("source_snapshot_hash") != source_hash):
            raise ExecutionAssociationError(409, "EXECUTION_SOURCE_CHANGED")
        # Re-read the source after the state read. A concurrent change is not
        # silently treated as a current association; no cross-GET atomicity claim.
        latest = self._get(path)
        latest_hash, latest_revision, latest_metadata = self._order(latest, expected)
        if (latest_hash != source_hash or latest_revision != revision
                or latest_metadata.get("aivan_project_id") != case_id
                or latest_metadata.get("abcdyi_execution") != envelope.get("state")):
            raise ExecutionAssociationError(409, "EXECUTION_SOURCE_CHANGED")
        state = envelope.get("state")
        base = {"schema_version": "aivan.execution-association.v1", "case_id": case_id,
                "purchase_order_id": po_id, "source_quote_id": quote_id,
                "source_snapshot_hash": source_hash, "revision": revision,
                "authoritative_source": "giraffe-db", "readback_verified": True,
                "execution_reads_available": False}
        if state is None and revision == 0:
            return {**base, "status": "unavailable", "reason": "EXECUTION_ASSOCIATION_MISSING",
                    "local_order_id": None, "local_project_id": None}
        if not isinstance(state, dict) or revision < 1:
            raise ExecutionAssociationError(502, "EXECUTION_PROVIDER_RESPONSE_INVALID")
        if (state.get("schema_version") != "abcdYi.execution.v1"
                or state.get("source_po_id") != po_id
                or state.get("source_quote_id") != quote_id
                or state.get("source_snapshot_hash") != source_hash):
            raise ExecutionAssociationError(409, "EXECUTION_ASSOCIATION_STALE")
        return {**base, "status": "associated", "reason": "EXECUTION_READ_ROUTING_UNAVAILABLE",
                "local_order_id": _uuid(state.get("local_order_id")),
                "local_project_id": _uuid(state.get("local_project_id"))}
