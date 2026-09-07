"""GPM FastAPI router — quote guidance, approval workflow, and packet listing."""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from aivan.gpm.auth import (
    GPMDecisionAuthorizationError,
    GPMPrincipal,
    require_principal,
)
from aivan.gpm.llm_runtime import analyze_quote, mock_quote_analysis
from aivan.gpm.packet_store import GPMPacketStore
from aivan.gpm.persistence_contract import (
    GPM_PERSISTENCE_CONTRACT_VERSION,
    PersistenceContractError,
)
from aivan.gpm.record_id import validation_error as record_id_validation_error

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level singletons; replaced in tests via _reset_store().
_packet_store: GPMPacketStore = GPMPacketStore(db_client=None)
_db_client = None


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


async def require_gpm_principal(request: Request) -> GPMPrincipal:
    """Authenticate tenant/operator context and reject production fallback."""

    try:
        principal = await require_principal(request)
    except GPMDecisionAuthorizationError as exc:
        raise HTTPException(status_code=400, detail={"error": exc.code}) from exc
    if (
        os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"
        and not _packet_store.is_durable
    ):
        raise HTTPException(
            status_code=503,
            detail={
                "error": "GPM_PERSISTENCE_UNAVAILABLE",
                "message": "production GPM requires durable giraffe-db persistence",
            },
        )
    return principal


async def require_gpm_tenant(request: Request) -> str:
    """Compatibility dependency exposing only the authenticated tenant."""

    return (await require_gpm_principal(request)).tenant_id


class QuoteGuidanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str
    supplier_id: Optional[str] = None
    supplier_quote: float
    currency: str = "USD"
    quantity: Optional[int] = None
    evidence_ids: Optional[list[str]] = None
    notes: Optional[str] = None


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: Optional[str] = None


@router.post("/quote-guidance", status_code=201, response_model=None)
async def create_quote_guidance(
    body: QuoteGuidanceRequest,
    principal: GPMPrincipal = Depends(require_gpm_principal),
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

    packet_id = f"gpm_pkt_{uuid.uuid4().hex[:16]}"

    packet: dict = {
        "packet_id": packet_id,
        "tenant_id": principal.tenant_id,
        "sku": body.sku,
        "supplier_id": body.supplier_id,
        "supplier_quote": body.supplier_quote,
        "currency": body.currency,
        "quantity": body.quantity,
        "quote_position": analysis.get("quote_position"),
        "recommendation": analysis.get("recommendation"),
        "confidence": analysis.get("confidence"),
        "human_approval_required": True,
        "approval_status": "pending",
        "dispatched": False,
        "llm_reasoning": json.dumps({"reasoning": analysis.get("reasoning"), "runtime_status": analysis.get("runtime_status")}),
        "evidence_ids": json.dumps(body.evidence_ids or []),
        "notes": body.notes,
    }

    persisted = _packet_store.save(
        packet,
        tenant_id=principal.tenant_id,
        correlation_id=principal.correlation_id,
    )
    return persisted


@router.get("/quote-guidance/{packet_id}")
async def get_quote_guidance(
    packet_id: str,
    principal: GPMPrincipal = Depends(require_gpm_principal),
) -> dict:
    packet = _packet_store.get(
        packet_id,
        tenant_id=principal.tenant_id,
        correlation_id=principal.correlation_id,
    )
    if packet is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    if packet.get("tenant_id") != principal.tenant_id:
        raise HTTPException(
            status_code=403,
            detail={"error": "forbidden", "message": "packet does not belong to this tenant"},
        )
    return packet


@router.post("/quote-guidance/{packet_id}/approve")
async def approve_packet(
    packet_id: str,
    body: ApprovalRequest,
    principal: GPMPrincipal = Depends(require_gpm_principal),
) -> dict:
    return _apply_decision(packet_id, "approved", body, principal)


@router.post("/quote-guidance/{packet_id}/reject")
async def reject_packet(
    packet_id: str,
    body: ApprovalRequest,
    principal: GPMPrincipal = Depends(require_gpm_principal),
) -> dict:
    return _apply_decision(packet_id, "rejected", body, principal)


def _apply_decision(
    packet_id: str,
    decision: str,
    body: ApprovalRequest,
    principal: GPMPrincipal,
) -> dict:
    try:
        return _packet_store.decide(
            packet_id,
            decision,
            principal=principal,
            notes=body.notes,
        )
    except GPMDecisionAuthorizationError as exc:
        raise HTTPException(
            status_code=403,
            detail={"error": exc.code, "correlation_id": principal.correlation_id},
        ) from exc
    except PersistenceContractError as exc:
        status_code = 409 if exc.code in {
            "GPM_ALREADY_DECIDED",
            "GPM_IDEMPOTENCY_CONFLICT",
        } else 404 if exc.code == "GPM_PACKET_NOT_FOUND" else 503
        raise HTTPException(
            status_code=status_code,
            detail={"error": exc.code, "correlation_id": exc.correlation_id},
        ) from exc


@router.get("/packets")
async def list_gpm_packets(
    status: Optional[str] = None,
    principal: GPMPrincipal = Depends(require_gpm_principal),
) -> dict:
    """List current tenant's packets with optional status filter."""
    packets = _packet_store.list_by_tenant(
        tenant_id=principal.tenant_id,
        status=status,
        correlation_id=principal.correlation_id,
    )
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
        "persistence_contract_version": GPM_PERSISTENCE_CONTRACT_VERSION,
        "features": {
            "quote_guidance": True,
            "approval_workflow": True,
            "rejection_workflow": True,
            "durable_packet_persistence": _packet_store.is_durable,
            "approval_audit_trail": _packet_store.is_durable,
        },
        "persistence": {
            "mode": "giraffe_db" if _packet_store.is_durable else "in_memory_only",
            "restart_safe": _packet_store.is_durable,
        },
        "auth": {
            "mode": auth_mode,
            "tenant_verification": "realtime_giraffe_db" if has_db else "hmac_only",
        },
    }
