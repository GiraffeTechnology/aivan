"""Fail-closed HTTP client for the standalone Stage 1 GPM guidance API."""

from __future__ import annotations

import math
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from aivan.integrations.transport_safety import reject_test_transport_in_production


DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_TIMEOUT_SECONDS = 15.0
_SAFE_CONTEXT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")
_SAFE_PACKET_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SAFE_CURRENCY = re.compile(r"^[A-Z]{3}$")
_DEFAULT_TRANSPORT: "httpx.BaseTransport | None" = None


class GPMGuidanceUnavailableError(RuntimeError):
    """Raised when GPM guidance cannot be proven safe for Stage 1 use."""


def set_default_transport(transport: "httpx.BaseTransport | None") -> None:
    """Install a suite-only transport; production policy rejects test transports."""

    reject_test_transport_in_production(transport, component="gpm-guidance-client")
    global _DEFAULT_TRANSPORT
    _DEFAULT_TRANSPORT = transport


def _is_ascii(value: str) -> bool:
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def _endpoint_allowed(base_url: str, *, transport_supplied: bool) -> bool:
    if transport_supplied:
        return True
    parsed = urlparse(base_url)
    if parsed.scheme == "https" and parsed.hostname:
        return True
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


class GPMGuidanceClient:
    """Create a non-authoritative guidance packet; never approve or dispatch."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        effective_transport = transport if transport is not None else _DEFAULT_TRANSPORT
        reject_test_transport_in_production(
            effective_transport, component="gpm-guidance-client"
        )
        self.base_url = (
            base_url or os.environ.get("GPM_API_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else float(os.environ.get("GPM_API_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
        )
        self._transport = effective_transport

    @staticmethod
    def _trusted_headers(
        *,
        tenant_id: str,
        actor_id: str,
        actor_role: str,
        trace_id: str,
        idempotency_key: str,
    ) -> dict[str, str]:
        api_key = os.environ.get("GPM_API_KEY", "").strip()
        values = (tenant_id, actor_id, actor_role, trace_id, idempotency_key, api_key)
        if not all(values) or not all(_is_ascii(item) for item in values):
            raise GPMGuidanceUnavailableError("GPM_TRUSTED_PROFILE_MISSING")
        if (
            not _SAFE_CONTEXT_ID.fullmatch(tenant_id)
            or not _SAFE_CONTEXT_ID.fullmatch(actor_id)
            or not _SAFE_CONTEXT_ID.fullmatch(actor_role)
            or not _SAFE_CONTEXT_ID.fullmatch(trace_id)
        ):
            raise GPMGuidanceUnavailableError("GPM_TRUSTED_PROFILE_MISSING")
        if not _SAFE_CONTEXT_ID.fullmatch(idempotency_key):
            raise GPMGuidanceUnavailableError("GPM_TRUSTED_PROFILE_MISSING")
        return {
            "X-AIVAN-API-Key": api_key,
            "X-AIVAN-Tenant-ID": tenant_id,
            "X-AIVAN-Actor-ID": actor_id,
            "X-AIVAN-Role": actor_role,
            "X-AIVAN-Trace-ID": trace_id,
            "Idempotency-Key": idempotency_key,
        }

    @staticmethod
    def _validate_response(
        data: Any,
        *,
        tenant_id: str,
        actor_id: str,
        actor_role: str,
        trace_id: str,
        case_id: str,
        quote_id: str,
        supplier_id: str | None,
        supplier_quote: float,
        currency: str,
        buyer_unit_price: float,
        buyer_total: float,
        supplier_total: float,
        margin_rate: float,
        gltg_run_id: str,
        gltg_api_version: str,
    ) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise GPMGuidanceUnavailableError("GPM_RESPONSE_INVALID")
        packet_id = data.get("packet_id")
        recommendation = data.get("recommendation")
        confidence = data.get("confidence")
        if (
            not isinstance(packet_id, str)
            or not _SAFE_PACKET_ID.fullmatch(packet_id)
            or data.get("tenant_id") != tenant_id
            or data.get("actor_id") != actor_id
            or data.get("actor_role") != actor_role
            or data.get("case_id") != case_id
            or data.get("quote_id") != quote_id
            or data.get("supplier_id") != supplier_id
            or data.get("supplier_quote") != supplier_quote
            or data.get("currency") != currency
            or data.get("buyer_unit_price") != buyer_unit_price
            or data.get("buyer_total") != buyer_total
            or data.get("supplier_total") != supplier_total
            or data.get("margin_rate") != margin_rate
            or data.get("gltg_run_id") != gltg_run_id
            or data.get("gltg_api_version") != gltg_api_version
            or not isinstance(recommendation, str)
            or not recommendation.strip()
            or not isinstance(confidence, str)
            or not confidence.strip()
            or data.get("human_approval_required") is not True
            or data.get("approval_status") != "pending"
            or data.get("dispatched") is not False
            or not isinstance(data.get("model_result"), dict)
            or not isinstance(data.get("lineage"), dict)
            or data["lineage"].get("source_trace_id") != trace_id
            or data["lineage"].get("case_id") != case_id
            or data["lineage"].get("quote_id") != quote_id
            or data["lineage"].get("supplier_id") != supplier_id
            or data["lineage"].get("gltg_run_id") != gltg_run_id
            or data["lineage"].get("gltg_api_version") != gltg_api_version
            or data["model_result"].get("recommendation") != recommendation
            or data["model_result"].get("confidence") != confidence
        ):
            raise GPMGuidanceUnavailableError("GPM_RESPONSE_INVALID")
        return data

    def create_guidance(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        actor_role: str,
        trace_id: str,
        idempotency_key: str,
        case_id: str,
        quote_id: str,
        sku: str,
        supplier_id: str | None,
        supplier_quote: float,
        currency: str,
        quantity: int | None,
        buyer_unit_price: float,
        buyer_total: float,
        supplier_total: float,
        margin_rate: float,
        gltg_run_id: str,
        gltg_api_version: str,
        evidence_ids: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        numeric_values = (
            supplier_quote,
            buyer_unit_price,
            buyer_total,
            supplier_total,
            margin_rate,
        )
        if (
            not isinstance(case_id, str)
            or not _SAFE_CONTEXT_ID.fullmatch(case_id)
            or not isinstance(quote_id, str)
            or not _SAFE_CONTEXT_ID.fullmatch(quote_id)
            or not isinstance(gltg_run_id, str)
            or not _SAFE_CONTEXT_ID.fullmatch(gltg_run_id)
            or not isinstance(gltg_api_version, str)
            or not _SAFE_CONTEXT_ID.fullmatch(gltg_api_version)
            or not _SAFE_CURRENCY.fullmatch(currency)
            or any(not math.isfinite(value) or value < 0 for value in numeric_values)
            or margin_rate >= 1
            or (quantity is not None and quantity <= 0)
        ):
            raise GPMGuidanceUnavailableError("GPM_REQUEST_INVALID")
        headers = self._trusted_headers(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
        )
        if not _endpoint_allowed(
            self.base_url, transport_supplied=self._transport is not None
        ):
            raise GPMGuidanceUnavailableError("GPM_ENDPOINT_INVALID_OR_INSECURE")
        payload = {
            "case_id": case_id,
            "quote_id": quote_id,
            "sku": sku,
            "supplier_id": supplier_id,
            "supplier_quote": supplier_quote,
            "currency": currency,
            "quantity": quantity,
            "buyer_unit_price": buyer_unit_price,
            "buyer_total": buyer_total,
            "supplier_total": supplier_total,
            "margin_rate": margin_rate,
            "gltg_run_id": gltg_run_id,
            "gltg_api_version": gltg_api_version,
            "evidence_ids": evidence_ids,
            "notes": notes,
        }
        try:
            with httpx.Client(
                timeout=self.timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.post(
                    f"{self.base_url}/api/gpm/quote-guidance",
                    json=payload,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise GPMGuidanceUnavailableError("GPM_TIMEOUT") from exc
        except httpx.HTTPError as exc:
            raise GPMGuidanceUnavailableError("GPM_CONNECTION_FAILED") from exc
        if response.status_code != 201:
            code = (
                f"GPM_HTTP_{response.status_code}"
                if response.status_code >= 400
                else f"GPM_UNEXPECTED_STATUS_{response.status_code}"
            )
            raise GPMGuidanceUnavailableError(code)
        try:
            data = response.json()
        except ValueError as exc:
            raise GPMGuidanceUnavailableError("GPM_RESPONSE_INVALID") from exc
        return self._validate_response(
            data,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            trace_id=trace_id,
            case_id=case_id,
            quote_id=quote_id,
            supplier_id=supplier_id,
            supplier_quote=supplier_quote,
            currency=currency,
            buyer_unit_price=buyer_unit_price,
            buyer_total=buyer_total,
            supplier_total=supplier_total,
            margin_rate=margin_rate,
            gltg_run_id=gltg_run_id,
            gltg_api_version=gltg_api_version,
        )
