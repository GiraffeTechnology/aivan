"""Stage 1 advisory GPM guidance boundary."""

from __future__ import annotations

import hashlib
import json
import os

from aivan.integrations.gpm_guidance_client import (
    GPMGuidanceClient,
    GPMGuidanceUnavailableError,
)
from aivan.openclaw.contracts import OpenClawEvent
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply


def _gltg_reference(gltg_result) -> str:
    provider_run_id = getattr(gltg_result, "gltg_run_id", None)
    if isinstance(provider_run_id, str) and provider_run_id.strip():
        return provider_run_id.strip()
    snapshot = {
        name: getattr(gltg_result, name, None)
        for name in (
            "p50_days",
            "p80_days",
            "p90_days",
            "selected_confidence_days",
            "deadline_risk_level",
            "source_api_version",
            "assessment_schema_version",
            "supplier_ids",
        )
    }
    canonical = json.dumps(
        snapshot,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"gltg-snapshot-sha256-{digest}"


def _gpm_actor(event: OpenClawEvent) -> tuple[str, str]:
    if event.authenticated_actor_id and event.authenticated_actor_role:
        return event.authenticated_actor_id, event.authenticated_actor_role
    service_actor = os.environ.get("GPM_SERVICE_ACTOR_ID", "").strip()
    service_role = os.environ.get("GPM_SERVICE_ACTOR_ROLE", "").strip()
    if service_actor and service_role:
        return service_actor, service_role
    if os.environ.get("AIVAN_ENV", "local").strip().lower() != "production":
        return "aivan-gpm-client", "orchestrator"
    return "", ""


def create_stage1_gpm_guidance(
    *,
    project,
    event: OpenClawEvent,
    requirement: BuyerRequirement,
    selected_option,
    replies: list[SupplierReply],
    gltg_result,
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
    quote = selected_option.quote
    if selected_reply is None or selected_reply.unit_price is None or quote is None:
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
    actor_id, actor_role = _gpm_actor(event)
    packet = GPMGuidanceClient().create_guidance(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role=actor_role,
        trace_id=trace_id,
        idempotency_key=idempotency_key,
        case_id=project.project_id,
        quote_id=selected_option.option_id,
        sku=(requirement.product_type or requirement.category or "apparel"),
        supplier_id=selected_reply.supplier_id or None,
        supplier_quote=float(quote.unit_price),
        currency=quote.currency,
        quantity=requirement.quantity,
        buyer_unit_price=float(quote.buyer_unit_price),
        buyer_total=float(quote.buyer_total),
        supplier_total=float(quote.supplier_total),
        margin_rate=float(quote.margin_rate),
        gltg_run_id=_gltg_reference(gltg_result),
        gltg_api_version=getattr(gltg_result, "source_api_version", ""),
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
