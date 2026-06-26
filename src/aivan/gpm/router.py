"""GPM FastAPI router — quote guidance, approval workflow, and packet listing."""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from aivan.gpm.auth import require_auth
from aivan.gpm.llm_runtime import analyze_quote, mock_quote_analysis
from aivan.gpm.packet_store import GPMPacketStore

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


class QuoteGuidanceRequest(BaseModel):
    sku: str
    supplier_id: Optional[str] = None
    supplier_quote: float
    currency: str = "USD"
    quantity: Optional[int] = None
    evidence_ids: Optional[list[str]] = None
    notes: Optional[str] = None


class ApprovalRequest(BaseModel):
    operator_id: str
    notes: Optional[str] = None


@router.post("/quote-guidance", status_code=201)
async def create_quote_guidance(
    body: QuoteGuidanceRequest,
    tenant_id: str = Depends(require_auth),
) -> dict:
    """Analyse a supplier quote and persist the resulting decision packet."""
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
        "tenant_id": tenant_id,
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

    persisted = _packet_store.save(packet)
    return persisted


@router.get("/quote-guidance/{packet_id}")
async def get_quote_guidance(
    packet_id: str,
    tenant_id: str = Depends(require_auth),
) -> dict:
    packet = _packet_store.get(packet_id, tenant_id=tenant_id)
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
    tenant_id: str = Depends(require_auth),
) -> dict:
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
    tenant_id: str = Depends(require_auth),
) -> dict:
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
    tenant_id: str = Depends(require_auth),
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
    return {
        "status": "ok",
        "packet_persistence": "durable" if _packet_store.is_durable else "in_memory_only",
        "giraffe_db_connected": _packet_store.is_durable,
    }


@router.get("/capabilities")
async def capabilities() -> dict:
    has_secret = bool(os.environ.get("AIVAN_AUTH_SECRET"))
    has_db = _db_client is not None
    auth_mode = (
        "multi_tenant_hmac_giraffe_db"
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
