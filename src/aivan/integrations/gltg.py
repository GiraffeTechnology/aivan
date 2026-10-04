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
import math
from typing import Any

from aivan.integrations.gltg_client import GLTGClient as GLTGHttpClient
from aivan.schemas.leadtime import LeadTimeComponent, LeadTimeEstimate
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.rfq import FallbackTrigger, GLTGSimulation, RFQStrategy
from aivan.utils.ids import new_estimate_id
from aivan.utils.tenant import resolve_service_tenant


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
        supplier_id: str | None = None,
        tenant_id: str | None = None,
    ) -> GLTGSimulation:
        data = self._estimate(
            product_type=requirement.product_type or requirement.category or "unspecified",
            quantity=requirement.quantity or 1000,
            quantity_unit=requirement.quantity_unit or "pcs",
            destination=requirement.destination,
            logistics_preference=requirement.logistics_preference or "sea",
            deadline_days=requirement.delivery_days,
            capacity_per_day=None,
            lead_time_confidence=strategy.lead_time_confidence,
            supplier_id=supplier_id,
            tenant_id=tenant_id,
            evidence_context=requirement.extra,
        )

        p50 = float(data["p50_days"])
        p80 = float(data["p80_days"])
        p90 = float(data["p90_days"])
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
            minimum_feasible_days=(
                float(data["minimum_feasible_days"])
                if data.get("minimum_feasible_days") is not None
                else None
            ),
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
            assessment_scope=(
                "supplier_candidate" if supplier_id else "requirement_baseline"
            ),
            supplier_ids=[supplier_id] if supplier_id else [],
            source_observation_ids=data.get("source_observation_ids") or [],
            persistence=data.get("persistence") or {},
            explanation_json=data.get("explanation_json") or {},
            warnings=data.get("warnings") or [],
        )

    # ------------------------------------------------------------------ #
    def estimate_for_requirement(
        self,
        requirement: BuyerRequirement,
        supplier_reply=None,
        supplier_id: str | None = None,
        candidate_id: str | None = None,
        tenant_id: str | None = None,
    ) -> LeadTimeEstimate:
        capacity = getattr(supplier_reply, "capacity_per_day", None) if supplier_reply else None
        declared = getattr(supplier_reply, "lead_time_days", None) if supplier_reply else None
        quantity = getattr(requirement, "quantity", None) or 1000
        destination = getattr(requirement, "destination", "")
        deadline_days = getattr(requirement, "delivery_days", None)

        supplier_anchor = (
            supplier_id
            or (getattr(supplier_reply, "supplier_id", None) if supplier_reply else None)
            or candidate_id
        )
        data = self._estimate(
            product_type=(
                getattr(requirement, "product_type", None)
                or getattr(requirement, "category", None)
                or "unspecified"
            ),
            quantity=quantity,
            quantity_unit=getattr(requirement, "quantity_unit", None) or "pcs",
            destination=destination,
            logistics_preference=getattr(requirement, "logistics_preference", "sea") or "sea",
            deadline_days=deadline_days,
            capacity_per_day=capacity,
            lead_time_confidence="P80",
            supplier_id=supplier_anchor,
            tenant_id=tenant_id,
            evidence_context=requirement.extra,
            supplier_stated_lead_time_days=declared,
        )

        p50 = float(data["p50_days"])
        p80 = float(data["p80_days"])
        p90 = float(data["p90_days"])
        calculated = float(data["estimated_lead_time_days"])
        earliest = (
            float(data["minimum_feasible_days"])
            if data.get("minimum_feasible_days") is not None
            else None
        )
        risk = data.get("risk_level", "unknown")

        trace_rows = data.get("calculation_trace") or []
        trace = trace_rows[0] if trace_rows and isinstance(trace_rows[0], dict) else {}
        components: list[LeadTimeComponent] = []
        for name, value in (data.get("components") or {}).items():
            if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                components.append(LeadTimeComponent(name=name, days=value, source="gltg", confidence=None))
        component_fields = (
            ("material_ready", "material_ready_days"),
            ("production", "capacity_adjusted_production_days"),
            ("qc", "qc_days"),
            ("logistics", "logistics_days"),
        )
        for component_name, field_name in component_fields:
            value = trace.get(field_name)
            if value is None:
                continue
            components.append(
                LeadTimeComponent(
                    name=component_name,
                    days=float(value),
                    source="gltg",
                    notes=f"qty={quantity}" if component_name == "production" else None,
                )
            )

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
            category=(
                getattr(requirement, "category", None)
                or getattr(requirement, "product_type", None)
                or "unspecified"
            ),
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
            critical_path=list(data.get("critical_path") or []),
            components=components,
            missing_inputs=missing_inputs,
            supplier_questions=supplier_questions,
            explanation=(
                f"GLTG estimate via standalone service for {quantity} pcs to "
                f"{destination or 'destination'}: calculated={calculated}d, p80={p80}d, risk={risk}."
            ),
            gltg_run_id=data.get("gltg_run_id"),
            source_api_version=data.get("source_api_version", "v1"),
            source_observation_ids=data.get("source_observation_ids") or [],
            persistence=data.get("persistence") or {},
            explanation_json=data.get("explanation_json") or {},
            warnings=data.get("warnings") or [],
        )

    # ------------------------------------------------------------------ #
    def _estimate(
        self,
        product_type: str,
        quantity: int,
        quantity_unit: str,
        destination: str | None,
        logistics_preference: str,
        deadline_days: int | None,
        capacity_per_day: int | None,
        lead_time_confidence: str = "P80",
        supplier_id: str | None = None,
        tenant_id: str | None = None,
        evidence_context: dict | None = None,
        supplier_stated_lead_time_days: float | None = None,
    ) -> dict:
        order = {
            "product_type": product_type,
            "quantity": quantity,
            "quantity_unit": quantity_unit,
            "destination": destination,
            "logistics_mode": logistics_preference,
            "deadline_days": deadline_days,
        }
        # A single requirement-level supplier (no stage data) -> GLTG applies its
        # own baseline stage estimates. AIVAN never computes stages locally.
        supplier: dict[str, Any] = {
            "supplier_id": supplier_id or "requirement-baseline",
            "capacity_per_day": capacity_per_day,
        }
        api_version = os.environ.get("GLTG_API_VERSION", "v2").strip().lower()
        if api_version not in {"v1", "v2"}:
            raise GLTGUnavailableError("GLTG_API_VERSION_UNSUPPORTED")
        if api_version == "v2":
            context = evidence_context or {}
            factors = context.get("trade_processing_factors", {})
            observations = context.get("source_observation_ids", [])
            if (not isinstance(factors, dict) or not isinstance(observations, list)
                or any(not isinstance(item, str) or not item.strip() for item in observations)):
                raise GLTGUnavailableError("GLTG_INPUT_EVIDENCE_INVALID")
            if supplier_stated_lead_time_days is not None:
                supplier["supplier_stated_lead_time_days"] = supplier_stated_lead_time_days
            evidence = {"use_giraffe_db": True} if supplier_id else None
            result = self._http.simulate_lead_time_v2(
                {
                    "request_id": new_estimate_id(),
                    "tenant_id": tenant_id
                    or resolve_service_tenant(context="gltg_v2_simulation"),
                    "source_system": "aivan",
                    "source_trace_id": new_estimate_id(),
                    "case_context": {
                        "assessment_scope": (
                            "supplier_candidate" if supplier_id else "requirement_baseline"
                        ),
                        **({"supplier_id": supplier_id} if supplier_id else {}),
                    },
                    "order": {
                        "product_type": order["product_type"],
                        "quantity": quantity,
                        "quantity_unit": quantity_unit,
                        "destination": destination,
                        "logistics_mode": logistics_preference,
                        "deadline_days": deadline_days,
                    },
                    "supplier": supplier,
                    "trade_processing_factors": factors,
                    "source_observation_ids": observations,
                    **({"evidence": evidence} if evidence is not None else {}),
                    "constraints": {"lead_time_confidence": lead_time_confidence},
                }
            )
            if not result.ok or result.data is None:
                raise GLTGUnavailableError(result.error or "GLTG v2 returned no data")
            if not isinstance(result.data, dict):
                raise GLTGUnavailableError("GLTG_RESPONSE_INVALID")
            if supplier_id:
                warning_codes = {
                    str(item.get("code") or "")
                    for item in (result.data.get("warnings") or [])
                    if isinstance(item, dict)
                }
                if "EVIDENCE_NOT_FOUND" in warning_codes:
                    raise GLTGUnavailableError("GLTG_EVIDENCE_NOT_FOUND")
            return self._normalize_v2_result(result.data)

        result = self._http.estimate_lead_time(order=order, suppliers=[supplier], constraints={})
        if not result.ok or result.data is None:
            raise GLTGUnavailableError(result.error or "GLTG returned no data")
        return result.data

    @staticmethod
    def _normalize_v2_result(data: dict) -> dict:
        if not isinstance(data, dict) or data.get("ok") is False:
            raise GLTGUnavailableError("GLTG_RESPONSE_INVALID")
        quantiles = data.get("quantiles") or {}
        risk = data.get("risk") or {}
        if not isinstance(quantiles, dict) or not isinstance(risk, dict):
            raise GLTGUnavailableError("GLTG_RESPONSE_INVALID")
        for field in ("components", "persistence", "explanation_json"):
            if data.get(field) is not None and not isinstance(data[field], dict):
                raise GLTGUnavailableError("GLTG_RESPONSE_INVALID")
        for field in ("warnings", "source_observation_ids"):
            if data.get(field) is not None and not isinstance(data[field], list):
                raise GLTGUnavailableError("GLTG_RESPONSE_INVALID")
        p50 = quantiles.get("p50_days")
        p80 = quantiles.get("p80_days")
        p90 = quantiles.get("p90_days")
        selected = risk.get("selected_confidence_days")
        if selected is None:
            selected = p80
        p50, p80, p90, selected = (
            GLTGClient._canonical_days(value) for value in (p50, p80, p90, selected)
        )
        if not p50 <= p80 <= p90:
            raise GLTGUnavailableError("GLTG_RESPONSE_QUANTILES_INVALID")
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
            "minimum_feasible_days": None,
            "risk_level": risk.get("deadline_risk_level", "unknown"),
            "feasible": risk.get("deadline_feasible"),
            "calculation_trace": [],
            "components": data.get("components") or {},
            "source_observation_ids": data.get("source_observation_ids") or [],
            "persistence": data.get("persistence") or {},
            "explanation_json": data.get("explanation_json") or {},
            "warnings": data.get("warnings") or [],
        }

    @staticmethod
    def _canonical_days(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GLTGUnavailableError("GLTG_RESPONSE_QUANTILES_INVALID")
        if not math.isfinite(value) or value < 0:
            raise GLTGUnavailableError("GLTG_RESPONSE_QUANTILES_INVALID")
        return float(value)

    @staticmethod
    def _feasibility(confidence_days: float, deadline_days: int | None) -> str:
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
    tenant_id: str | None = None,
) -> LeadTimeEstimate:
    """Module-level helper kept for caller compatibility; routes through GLTG API."""
    return GLTGClient().estimate_for_requirement(
        requirement,
        supplier_reply=supplier_reply,
        supplier_id=supplier_id,
        candidate_id=candidate_id,
        tenant_id=tenant_id,
    )
