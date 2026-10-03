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
from aivan.pricing.quote_calculator import calculate_supplier_total
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply
from aivan.execution.source_quote import source_quote_reference


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
            for item in reversed(replies)
            if (
                item.supplier_id == selected_option.supplier_id
                if selected_option.supplier_id
                else bool(selected_option.candidate_id)
                and item.candidate_id == selected_option.candidate_id
            )
        ),
        None,
    )
    quote = selected_option.quote
    if selected_reply is None or selected_reply.unit_price is None or quote is None:
        raise GPMGuidanceUnavailableError("GPM_SOURCE_QUOTE_MISSING")
    quote_reference = source_quote_reference(selected_reply)
    bound_reference = selected_option.source_quote_reference
    if bound_reference and bound_reference != quote_reference:
        raise GPMGuidanceUnavailableError("GPM_SOURCE_QUOTE_SUPERSEDED")
    if ((quote.currency or "").strip().upper() != (selected_reply.currency or "").strip().upper()
            or (not bound_reference and quote.unit_price != selected_reply.unit_price)):
        raise GPMGuidanceUnavailableError("GPM_SOURCE_QUOTE_MISMATCH")
    tenant_id = project.tenant_id or event.tenant_id or "legacy"
    trace_seed = event.source_trace_id or event.message_id or project.project_id
    trace_id = event.source_trace_id or (
        "trace_" + hashlib.sha256(trace_seed.encode("utf-8")).hexdigest()[:24]
    )
    actor_id, actor_role = _gpm_actor(event)
    # Buyer-facing options intentionally hide source costs. Advisory calculations
    # still use the bound supplier quote and the existing MOQ/fee calculation.
    supplier_cost = calculate_supplier_total(
        unit_price=float(selected_reply.unit_price), quantity=quote.quantity,
        moq=selected_reply.moq or 0, sample_fee=quote.sample_fee,
        tooling_fee=quote.tooling_fee, packaging_fee=quote.packaging_fee,
        domestic_logistics_fee=quote.domestic_logistics_fee, qc_fee=quote.qc_fee,
    )["supplier_total"]
    request = dict(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role=actor_role,
        trace_id=trace_id,
        case_id=project.project_id,
        quote_id=quote_reference,
        sku=(requirement.product_type or requirement.category or "apparel"),
        supplier_id=selected_reply.supplier_id or None,
        supplier_quote=float(selected_reply.unit_price),
        currency=quote.currency,
        quantity=requirement.quantity,
        buyer_unit_price=float(quote.buyer_unit_price),
        buyer_total=float(quote.buyer_total),
        supplier_total=supplier_cost,
        margin_rate=float(quote.margin_rate),
        gltg_run_id=_gltg_reference(gltg_result),
        gltg_api_version=getattr(gltg_result, "source_api_version", ""),
        notes="This advisory request uses the selected supplier quotation and its recorded source references.",
    )
    # Exact request identity includes tenant/actor, selected terms and GLTG
    # lineage. Regenerating only a UI option ID does not mint a new decision.
    canonical = json.dumps({key: value for key, value in request.items() if key != "trace_id"},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    idempotency_key = "gpm_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    packet = GPMGuidanceClient().create_guidance(idempotency_key=idempotency_key, **request)
    return {
        "packet_id": packet["packet_id"],
        "recommendation": packet["recommendation"],
        "confidence": packet["confidence"],
        "human_approval_required": True,
        "approval_status": "pending",
        "dispatched": False,
        "quote_id": quote_reference,
    }
