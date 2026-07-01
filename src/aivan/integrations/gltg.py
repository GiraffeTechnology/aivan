"""GLTG integration facade for AIVAN.

All lead-time calculation is owned by the standalone GLTG service
(https://github.com/GiraffeTechnology/GLTG). This module is a thin translator:
it builds GLTG API requests from AIVAN's RFQ context, calls the HTTP API via
``GLTGHttpClient``, and maps responses into AIVAN's DTOs.

It must NOT import any local calculator, local lead-time models for calculation,
or any fallback calculator. On GLTG failure it raises ``GLTGUnavailableError`` --
it never silently substitutes a locally computed estimate.
"""

from __future__ import annotations

import os

from aivan.integrations.gltg_client import GLTGClient as GLTGHttpClient
from aivan.schemas.leadtime import LeadTimeComponent, LeadTimeEstimate
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.rfq import FallbackTrigger, GLTGSimulation, RFQStrategy
from aivan.utils.ids import new_estimate_id


def _resolve_gltg_tenant() -> str:
    """Resolve the tenant for a GLTG v2 simulation call.

    Fails closed rather than defaulting to a shared placeholder tenant, so a
    misconfigured deployment cannot scope another tenant's behavioral stats or
    persist runs under the wrong tenant.
    """
    from aivan.tenancy.resolver import resolve_service_tenant

    return resolve_service_tenant(context="gltg_v2_simulation")


class GLTGUnavailableError(RuntimeError):
    """Raised when the GLTG service cannot be reached or returns an error.

    Surfacing this (instead of falling back to a local calculation) is
    deliberate: AIVAN must never invent GLTG outputs.
    """


class GLTGClient:
    """Stable facade for the standalone GLTG lead-time service (HTTP-backed)."""

    def __init__(self, http: GLTGHttpClient | None = None) -> None:
        self._http = http or GLTGHttpClient()

    # ------------------------------------------------------------------ #
    def simulate(
        self,
        requirement: BuyerRequirement,
        strategy: RFQStrategy,
        supplier_count: int,
    ) -> GLTGSimulation:
        data = self._estimate(
            quantity=requirement.quantity or 1000,
            destination=requirement.destination,
            logistics_preference=requirement.logistics_preference or "sea",
            deadline_days=requirement.delivery_days,
            capacity_per_day=None,
            lead_time_confidence=strategy.lead_time_confidence,
        )

        p50 = int(data["p50_days"])
        p80 = int(data["p80_days"])
        p90 = int(data["p90_days"])
        confidence_days = {"P50": p50, "P80": p80, "P90": p90}[strategy.lead_time_confidence]
        risk = data.get("risk_level", "unknown")

        fallback = FallbackTrigger(
            min_valid_supplier_replies=max(strategy.fallback_trigger.min_valid_supplier_replies, 2),
            max_wait_hours=strategy.fallback_trigger.max_wait_hours,
            lead_time_risk_threshold=risk
            if risk in {"low", "medium", "high"}
            else strategy.fallback_trigger.lead_time_risk_threshold,
        )

        return GLTGSimulation(
            p50_days=p50,
            p80_days=p80,
            p90_days=p90,
            minimum_feasible_days=int(data.get("minimum_feasible_days") or max(p50 - 5, 1)),
            supplier_set_feasibility="sufficient" if supplier_count >= 2 else "thin",
            known_suppliers_first_feasibility=self._feasibility(confidence_days, requirement.delivery_days),
            public_bidding_time_cost_days=3 if strategy.public_bidding == "enabled" else 5,
            fallback_trigger_recommendation=fallback,
            selected_confidence_days=confidence_days,
            deadline_risk_level=risk,
            explanation=(
                f"GLTG estimate via standalone service: p50={p50}d, p80={p80}d, p90={p90}d; "
                f"deadline risk={risk}."
            ),
            gltg_run_id=data.get("gltg_run_id"),
            source_api_version=data.get("source_api_version", "v1"),
            assessment_schema_version=data.get("assessment_schema_version"),
            assessment_packet=data.get("assessment_packet") or {},
            manual_review_required=data.get("manual_review_required"),
            fallback_supplier_required=data.get("fallback_supplier_required"),
        )

    # ------------------------------------------------------------------ #
    def estimate_for_requirement(
        self,
        requirement: BuyerRequirement,
        supplier_reply=None,
        supplier_id: str | None = None,
        candidate_id: str | None = None,
    ) -> LeadTimeEstimate:
        capacity = getattr(supplier_reply, "capacity_per_day", None) if supplier_reply else None
        declared = getattr(supplier_reply, "lead_time_days", None) if supplier_reply else None
        quantity = getattr(requirement, "quantity", None) or 1000
        destination = getattr(requirement, "destination", "")
        deadline_days = getattr(requirement, "delivery_days", None)

        data = self._estimate(
            quantity=quantity,
            destination=destination,
            logistics_preference=getattr(requirement, "logistics_preference", "sea") or "sea",
            deadline_days=deadline_days,
            capacity_per_day=capacity,
            lead_time_confidence="P80",
        )

        p50 = int(data["p50_days"])
        p80 = int(data["p80_days"])
        p90 = int(data["p90_days"])
        calculated = int(data["estimated_lead_time_days"])
        earliest = int(data.get("minimum_feasible_days") or max(calculated - 5, 1))
        risk = data.get("risk_level", "unknown")

        trace = (data.get("calculation_trace") or [{}])[0]
        components = [
            LeadTimeComponent(name="material_ready", days=int(trace.get("material_ready_days", 0) or 0), source="gltg"),
            LeadTimeComponent(
                name="production",
                days=int(trace.get("capacity_adjusted_production_days", 0) or 0),
                source="gltg",
                notes=f"qty={quantity}",
            ),
            LeadTimeComponent(name="qc", days=int(trace.get("qc_days", 0) or 0), source="gltg"),
            LeadTimeComponent(name="logistics", days=int(trace.get("logistics_days", 0) or 0), source="gltg"),
        ]

        missing_inputs: list[str] = []
        supplier_questions: list[str] = []
        if capacity is None:
            missing_inputs.append("actual_daily_capacity")
            supplier_questions.append("What is your actual daily production capacity for this product?")

        return LeadTimeEstimate(
            estimate_id=new_estimate_id(),
            project_id=getattr(requirement, "project_id", "") or "",
            supplier_id=supplier_id,
            candidate_id=candidate_id,
            category=getattr(requirement, "category", "apparel") or "apparel",
            quantity=quantity,
            destination=destination,
            declared_lead_time_days=declared,
            calculated_lead_time_days=calculated,
            earliest_possible_days=earliest,
            expected_days=p50,
            conservative_days=p80,
            p50_days=p50,
            p80_days=p80,
            p90_days=p90,
            risk_buffer_days=max(p80 - p50, 0),
            deadline_days=deadline_days,
            deadline_feasible=bool(data.get("feasible")) if deadline_days is not None else None,
            deadline_risk_level=risk,
            critical_path=["material_ready", "production", "logistics"],
            components=components,
            missing_inputs=missing_inputs,
            supplier_questions=supplier_questions,
            explanation=(
                f"GLTG estimate via standalone service for {quantity} pcs to "
                f"{destination or 'destination'}: calculated={calculated}d, p80={p80}d, risk={risk}."
            ),
        )

    # ------------------------------------------------------------------ #
    def _estimate(
        self,
        quantity: int,
        destination: str | None,
        logistics_preference: str,
        deadline_days: int | None,
        capacity_per_day: int | None,
        lead_time_confidence: str = "P80",
    ) -> dict:
        order = {
            "product_type": "apparel",
            "quantity": quantity,
            "destination": destination,
            "logistics_mode": logistics_preference,
            "deadline_days": deadline_days,
        }
        # A single requirement-level supplier (no stage data) -> GLTG applies its
        # own baseline stage estimates. AIVAN never computes stages locally.
        supplier = {"supplier_id": "requirement", "capacity_per_day": capacity_per_day, "confidence": 0.7}
        if os.environ.get("GLTG_API_VERSION", "v1").lower() == "v2":
            result = self._http.simulate_lead_time_v2(
                {
                    "request_id": new_estimate_id(),
                    "tenant_id": _resolve_gltg_tenant(),
                    "source_system": "aivan",
                    "source_trace_id": new_estimate_id(),
                    "case_context": {"supplier_id": supplier["supplier_id"]},
                    "order": {
                        "product_type": order["product_type"],
                        "quantity": quantity,
                        "quantity_unit": "pcs",
                        "destination": destination,
                        "logistics_mode": logistics_preference,
                        "deadline_days": deadline_days,
                    },
                    "supplier": supplier,
                    "constraints": {"lead_time_confidence": lead_time_confidence},
                }
            )
            if not result.ok or result.data is None:
                raise GLTGUnavailableError(result.error or "GLTG v2 returned no data")
            return self._normalize_v2_result(result.data)

        result = self._http.estimate_lead_time(order=order, suppliers=[supplier], constraints={})
        if not result.ok or result.data is None:
            raise GLTGUnavailableError(result.error or "GLTG returned no data")
        return result.data

    @staticmethod
    def _normalize_v2_result(data: dict) -> dict:
        quantiles = data.get("quantiles") or {}
        risk = data.get("risk") or {}
        p50 = quantiles.get("p50_days")
        p80 = quantiles.get("p80_days")
        p90 = quantiles.get("p90_days")
        selected = risk.get("selected_confidence_days") or p80
        if p50 is None or p80 is None or p90 is None or selected is None:
            raise GLTGUnavailableError("GLTG v2 response missing quantiles")
        return {
            "source_api_version": "v2",
            "gltg_run_id": data.get("gltg_run_id"),
            "assessment_schema_version": data.get("assessment_schema_version"),
            "assessment_packet": data.get("assessment_packet") or {},
            "manual_review_required": data.get("manual_review_required"),
            "fallback_supplier_required": data.get("fallback_supplier_required"),
            "estimated_lead_time_days": selected,
            "p50_days": p50,
            "p80_days": p80,
            "p90_days": p90,
            "minimum_feasible_days": p50,
            "risk_level": risk.get("deadline_risk_level", "unknown"),
            "feasible": risk.get("deadline_feasible"),
            "calculation_trace": [],
        }

    @staticmethod
    def _feasibility(confidence_days: int, deadline_days: int | None) -> str:
        if deadline_days is None:
            return "unknown_without_deadline"
        if confidence_days <= deadline_days:
            return "feasible"
        if confidence_days <= deadline_days + 5:
            return "tight"
        return "not_feasible_without_fallback"


def calculate_leadtime_for_requirement(
    requirement,
    supplier_reply=None,
    supplier_id: str | None = None,
    candidate_id: str | None = None,
) -> LeadTimeEstimate:
    """Module-level helper kept for caller compatibility; routes through GLTG API."""
    return GLTGClient().estimate_for_requirement(
        requirement, supplier_reply=supplier_reply, supplier_id=supplier_id, candidate_id=candidate_id
    )
