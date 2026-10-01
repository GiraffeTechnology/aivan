"""Stage 1 advisory GPM guidance boundary."""

from __future__ import annotations

import hashlib

from aivan.integrations.gpm_guidance_client import (
    GPMGuidanceClient,
    GPMGuidanceUnavailableError,
)
from aivan.openclaw.contracts import OpenClawEvent
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply


def create_stage1_gpm_guidance(
    *,
    project,
    event: OpenClawEvent,
    requirement: BuyerRequirement,
    selected_option,
    replies: list[SupplierReply],
) -> dict:
    """Create advisory guidance without approving, rejecting, or dispatching."""

    selected_reply = next(
        (
            item
            for item in replies
            if (selected_option.supplier_id and item.supplier_id == selected_option.supplier_id)
            or (
                selected_option.candidate_id
                and item.candidate_id == selected_option.candidate_id
            )
        ),
        None,
    )
    if selected_reply is None and len(replies) == 1:
        selected_reply = replies[0]
    if selected_reply is None or selected_reply.unit_price is None:
        raise GPMGuidanceUnavailableError("GPM_SOURCE_QUOTE_MISSING")
    tenant_id = project.tenant_id or event.tenant_id or "legacy"
    trace_seed = event.source_trace_id or event.message_id or project.project_id
    trace_id = event.source_trace_id or (
        "trace_" + hashlib.sha256(trace_seed.encode("utf-8")).hexdigest()[:24]
    )
    idempotency_material = (
        f"{tenant_id}:{project.project_id}:{event.message_id}:"
        f"{selected_option.option_id}:gpm-guidance"
    )
    idempotency_key = (
        "gpm_" + hashlib.sha256(idempotency_material.encode("utf-8")).hexdigest()[:32]
    )
    packet = GPMGuidanceClient().create_guidance(
        tenant_id=tenant_id,
        trace_id=trace_id,
        idempotency_key=idempotency_key,
        sku=(requirement.product_type or requirement.category or "apparel"),
        supplier_id=selected_reply.supplier_id or None,
        supplier_quote=float(selected_reply.unit_price),
        currency=selected_reply.currency or "USD",
        quantity=requirement.quantity,
        notes=f"case={project.project_id};option={selected_option.option_id}",
    )
    return {
        "packet_id": packet["packet_id"],
        "recommendation": packet["recommendation"],
        "confidence": packet["confidence"],
        "human_approval_required": True,
        "approval_status": "pending",
        "dispatched": False,
    }
