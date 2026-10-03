"""GPM FastAPI router — quote guidance, approval workflow, and packet listing."""
from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field

from aivan.gpm.auth import require_auth
from aivan.gpm.giraffe_db_client import GPM_PACKET_API_VERSION
from aivan.gpm.llm_runtime import analyze_quote, mock_quote_analysis
from aivan.gpm.packet_store import GPMPacketStore
from aivan.gpm.request_identity import matches_request, request_fingerprint
from aivan.gpm.record_id import validation_error as record_id_validation_error

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level singletons; replaced in tests via _reset_store().
_packet_store: GPMPacketStore = GPMPacketStore(db_client=None)
_db_client = None
_SAFE_REQUEST_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")


def _reset_store(store: GPMPacketStore) -> None:
    """Replace the module-level store — used in tests."""
    global _packet_store
    _packet_store = store


def _init_store() -> None:
    """Called at server startup to initialise giraffe-db backed store if configured."""
    global _packet_store, _db_client
    base_url = os.environ.get("GIRAFFE_DB_BASE_URL", "")
    if base_url:
        from aivan.gpm.giraffe_db_client import GiraffeDBClient

        _db_client = GiraffeDBClient(base_url=base_url)
        _packet_store = GPMPacketStore(db_client=_db_client)
    else:
        _db_client = None
        _packet_store = GPMPacketStore(db_client=None)


def get_db_client():
    return _db_client


async def require_gpm_tenant(request: Request) -> str:
    """Authenticate a tenant and prohibit production in-memory degradation."""

    tenant_id = await require_auth(request)
    correlation_id = request.headers.get("X-AIVAN-Trace-ID", "").strip() or None
    _packet_store.ensure_tenant_ready(
        tenant_id,
        correlation_id=correlation_id,
    )
    return tenant_id


class QuoteGuidanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    case_id: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    quote_id: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    sku: str
    supplier_id: Optional[str] = None
    supplier_quote: float = Field(ge=0)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    quantity: Optional[int] = Field(default=None, ge=1)
    buyer_unit_price: float = Field(ge=0)
    buyer_total: float = Field(ge=0)
    supplier_total: float = Field(ge=0)
    margin_rate: float = Field(ge=0, lt=1)
    gltg_run_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    )
    gltg_api_version: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    )
    evidence_ids: Optional[list[str]] = None
    notes: Optional[str] = None


class ApprovalRequest(BaseModel):
    operator_id: str
    notes: Optional[str] = None


@router.post("/quote-guidance", status_code=201, response_model=None)
async def create_quote_guidance(
    body: QuoteGuidanceRequest,
    request: Request = None,
    tenant_id: str = Depends(require_gpm_tenant),
) -> dict | JSONResponse:
    """Analyse a supplier quote and persist the resulting decision packet."""
    # A supplier_id that is a retired giraffe-db legacy id is rejected, never
    # remapped. AIVAN's own (non-giraffe-db) supplier ids pass through. The
    # envelope is returned at the top level (not wrapped under FastAPI's
    # ``detail``) because consumers match on ``error``/``received`` directly.
    if body.supplier_id is not None:
        id_error = record_id_validation_error(body.supplier_id)
        if id_error is not None:
            return JSONResponse(status_code=422, content=id_error)

    headers = request.headers if request is not None else {}
    idempotency_key = headers.get("Idempotency-Key", "").strip()
    correlation_id = headers.get("X-AIVAN-Trace-ID", "").strip() or None
    actor_id = headers.get("X-AIVAN-Actor-ID", "").strip() or None
    actor_role = headers.get("X-AIVAN-Role", "").strip() or None
    if os.environ.get("AIVAN_ENV", "local").strip().lower() == "production":
        if not idempotency_key:
            raise HTTPException(
                status_code=400,
                detail={"error": "GPM_IDEMPOTENCY_KEY_REQUIRED"},
            )
        if not _SAFE_REQUEST_TOKEN.fullmatch(idempotency_key):
            raise HTTPException(
                status_code=400,
                detail={"error": "GPM_IDEMPOTENCY_KEY_INVALID"},
            )
        if (
            not actor_id
            or not actor_role
            or not _SAFE_REQUEST_TOKEN.fullmatch(actor_id)
            or not _SAFE_REQUEST_TOKEN.fullmatch(actor_role)
        ):
            raise HTTPException(
                status_code=400,
                detail={"error": "GPM_ACTOR_CONTEXT_REQUIRED"},
            )
    if correlation_id and not _SAFE_REQUEST_TOKEN.fullmatch(correlation_id):
        raise HTTPException(
            status_code=400,
            detail={"error": "GPM_CORRELATION_ID_INVALID"},
        )

    if idempotency_key:
        packet_identity = hashlib.sha256(
            f"{tenant_id}:{idempotency_key}".encode("utf-8")
        ).hexdigest()[:16]
        packet_id = f"gpm_pkt_{packet_identity}"
    else:
        packet_id = f"gpm_pkt_{uuid.uuid4().hex[:16]}"

    if idempotency_key:
        previous = _packet_store.get(packet_id, tenant_id=tenant_id, correlation_id=correlation_id)
        if previous is not None:
            if previous.get("packet_id") != packet_id:
                raise HTTPException(status_code=503, detail={"error": "GPM_PERSISTENCE_OUTCOME_UNKNOWN", "packet_id": packet_id})
            payload = body.model_dump()
            if not matches_request(previous, payload, tenant_id=tenant_id,
                                   actor_id=actor_id, actor_role=actor_role):
                raise HTTPException(status_code=409, detail={"error": "GPM_IDEMPOTENCY_CONFLICT", "packet_id": packet_id})
            # Keep the originally persisted analysis and source trace. These
            # transport headers attest replay of the same complete input.
            return JSONResponse(status_code=201, content=jsonable_encoder(previous), headers={
                "X-GPM-Replayed": "true", "X-GPM-Request-SHA256": request_fingerprint(
                    payload, tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role),
            })

    runtime_mode = os.environ.get("GPM_LLM_RUNTIME_MODE", "").lower()
    if runtime_mode == "mock":
        analysis = mock_quote_analysis(body.sku, body.supplier_quote)
    else:
        analysis = analyze_quote(
            sku=body.sku,
            supplier_quote=body.supplier_quote,
            currency=body.currency,
            quantity=body.quantity,
        )
    if analysis.get("runtime_status") == "unavailable":
        raise HTTPException(
            status_code=503,
            detail={
                "error": "GPM_MODEL_UNAVAILABLE",
                "reason": analysis.get("reason", "provider_error"),
            },
        )


    packet: dict = {
        "packet_id": packet_id,
        "tenant_id": tenant_id,
        "case_id": body.case_id,
        "quote_id": body.quote_id,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "sku": body.sku,
        "supplier_id": body.supplier_id,
        "supplier_quote": body.supplier_quote,
        "currency": body.currency,
        "quantity": body.quantity,
        "buyer_unit_price": body.buyer_unit_price,
        "buyer_total": body.buyer_total,
        "supplier_total": body.supplier_total,
        "margin_rate": body.margin_rate,
        "gltg_run_id": body.gltg_run_id,
        "gltg_api_version": body.gltg_api_version,
        "quote_position": analysis.get("quote_position"),
        "recommendation": analysis.get("recommendation"),
        "confidence": analysis.get("confidence"),
        "model_result": analysis,
        "lineage": {
            "source_trace_id": correlation_id,
            "case_id": body.case_id,
            "quote_id": body.quote_id,
            "supplier_id": body.supplier_id,
            "gltg_run_id": body.gltg_run_id,
            "gltg_api_version": body.gltg_api_version,
        },
        "human_approval_required": True,
        "approval_status": "pending",
        "dispatched": False,
        "llm_reasoning": json.dumps({"reasoning": analysis.get("reasoning"), "runtime_status": analysis.get("runtime_status")}),
        "evidence_ids": json.dumps(body.evidence_ids or []),
        "notes": body.notes,
    }

    persisted = _packet_store.save(
        packet,
        idempotency_key=idempotency_key or None,
        correlation_id=correlation_id,
    )
    return persisted


@router.get("/quote-guidance/{packet_id}")
async def get_quote_guidance(
    packet_id: str,
    request: Request,
    tenant_id: str = Depends(require_gpm_tenant),
) -> dict:
    correlation_id = request.headers.get("X-AIVAN-Trace-ID", "").strip() or None
    if correlation_id and not _SAFE_REQUEST_TOKEN.fullmatch(correlation_id):
        raise HTTPException(
            status_code=400,
            detail={"error": "GPM_CORRELATION_ID_INVALID"},
        )
    packet = _packet_store.get(
        packet_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
    )
    if packet is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if packet.get("tenant_id") != tenant_id:
        raise HTTPException(
            status_code=403,
            detail={"error": "forbidden", "message": "packet does not belong to this tenant"},
        )
    return packet


@router.post("/quote-guidance/{packet_id}/approve")
async def approve_packet(
    packet_id: str,
    body: ApprovalRequest,
    tenant_id: str = Depends(require_gpm_tenant),
) -> dict:
    if os.environ.get("AIVAN_ENV", "local").strip().lower() == "production":
        raise HTTPException(
            status_code=409,
            detail={"error": "GPM_DECISION_PATH_DISABLED"},
        )
    packet = _packet_store.get(packet_id, tenant_id=tenant_id)
    if packet is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if packet.get("tenant_id") != tenant_id:
        raise HTTPException(
            status_code=403,
            detail={"error": "forbidden", "message": "packet does not belong to this tenant"},
        )
    if packet.get("approval_status") != "pending":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "already_decided",
                "current_status": packet.get("approval_status"),
            },
        )

    updated = _packet_store.update_status(
        packet_id, "approved", body.operator_id, body.notes, tenant_id=tenant_id
    )

    assert updated is not None and updated.get("dispatched") is False, (
        "dispatched must remain False after approval"
    )
    return updated


@router.post("/quote-guidance/{packet_id}/reject")
async def reject_packet(
    packet_id: str,
    body: ApprovalRequest,
    tenant_id: str = Depends(require_gpm_tenant),
) -> dict:
    if os.environ.get("AIVAN_ENV", "local").strip().lower() == "production":
        raise HTTPException(
            status_code=409,
            detail={"error": "GPM_DECISION_PATH_DISABLED"},
        )
    packet = _packet_store.get(packet_id, tenant_id=tenant_id)
    if packet is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if packet.get("tenant_id") != tenant_id:
        raise HTTPException(
            status_code=403,
            detail={"error": "forbidden", "message": "packet does not belong to this tenant"},
        )
    if packet.get("approval_status") != "pending":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "already_decided",
                "current_status": packet.get("approval_status"),
            },
        )

    updated = _packet_store.update_status(
        packet_id, "rejected", body.operator_id, body.notes, tenant_id=tenant_id
    )

    assert updated is not None and updated.get("dispatched") is False, (
        "dispatched must remain False after rejection"
    )
    return updated


@router.get("/packets")
async def list_gpm_packets(
    status: Optional[str] = None,
    tenant_id: str = Depends(require_gpm_tenant),
) -> dict:
    """List current tenant's packets with optional status filter."""
    packets = _packet_store.list_by_tenant(tenant_id=tenant_id, status=status)
    return {
        "packets": packets,
        "total": len(packets),
        "persistence": "durable" if _packet_store.is_durable else "in_memory_only",
    }


@router.get("/healthz")
async def healthz() -> dict:
    production = os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"
    ready = _packet_store.is_durable or not production
    return {
        "status": "ok" if ready else "not_ready",
        "packet_persistence": "durable" if _packet_store.is_durable else "in_memory_only",
        "giraffe_db_connected": _packet_store.is_durable,
    }


@router.get("/capabilities")
async def capabilities() -> dict:
    has_secret = bool(os.environ.get("AIVAN_AUTH_SECRET"))
    has_request_context_auth = bool(
        os.environ.get("AIVAN_API_KEY") or os.environ.get("AIVAN_TENANT_API_KEYS")
    )
    has_db = _db_client is not None
    production = os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"
    auth_mode = (
        "production_misconfigured"
        if production and (not has_db or not _packet_store.is_durable)
        else "production_request_context"
        if production and has_request_context_auth
        else "production_hmac_giraffe_db"
        if production and has_secret and has_db
        else "multi_tenant_hmac_giraffe_db"
        if has_secret and has_db
        else "multi_tenant_hmac_only"
        if has_secret
        else "dev_unauthenticated"
    )
    return {
        "module": "gpm",
        "version": "0.3.0",
        "features": {
            "quote_guidance": True,
            "approval_workflow": False,
            "rejection_workflow": False,
            "stage1_advisory_only": True,
            "durable_packet_persistence": _packet_store.is_durable,
            "approval_audit_trail": False,
        },
        "persistence": {
            "mode": "giraffe_db" if _packet_store.is_durable else "in_memory_only",
            "restart_safe": _packet_store.is_durable,
            "expected_api_version": GPM_PACKET_API_VERSION,
        },
        "auth": {
            "mode": auth_mode,
            "tenant_verification": "realtime_giraffe_db" if has_db else "hmac_only",
        },
    }
