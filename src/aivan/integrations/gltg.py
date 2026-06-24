from __future__ import annotations

import os

from aivan.leadtime.calculator import calculate_apparel_leadtime
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.rfq import FallbackTrigger, GLTGSimulation, RFQStrategy


class GLTGClient:
    """Stable facade for the GLTG lead-time simulation model."""

    def simulate(
        self,
        requirement: BuyerRequirement,
        strategy: RFQStrategy,
        supplier_count: int,
    ) -> GLTGSimulation:
        try:
            if os.environ.get("AIVAN_GLTG_FORCE_TIMEOUT", "").lower() == "true":
                raise TimeoutError("GLTG simulation timed out")
            estimate = calculate_apparel_leadtime(
                quantity=requirement.quantity or 1000,
                destination=requirement.destination,
                logistics_preference=requirement.logistics_preference or "sea",
                project_id=requirement.project_id,
                deadline_days=requirement.delivery_days,
            )
        except TimeoutError:
            return self._timeout_fallback(requirement, strategy, supplier_count)
        confidence_days = {
            "P50": estimate.p50_days,
            "P80": estimate.p80_days,
            "P90": estimate.p90_days,
        }[strategy.lead_time_confidence]
        feasibility = self._feasibility(confidence_days, requirement.delivery_days)
        public_bidding_cost = 3 if strategy.public_bidding == "enabled" else 5
        fallback = FallbackTrigger(
            min_valid_supplier_replies=max(strategy.fallback_trigger.min_valid_supplier_replies, 2),
            max_wait_hours=strategy.fallback_trigger.max_wait_hours,
            lead_time_risk_threshold=estimate.deadline_risk_level
            if estimate.deadline_risk_level in {"low", "medium", "high"}
            else strategy.fallback_trigger.lead_time_risk_threshold,
        )
        return GLTGSimulation(
            p50_days=estimate.p50_days,
            p80_days=estimate.p80_days,
            p90_days=estimate.p90_days,
            minimum_feasible_days=estimate.earliest_possible_days,
            supplier_set_feasibility="sufficient" if supplier_count >= 2 else "thin",
            known_suppliers_first_feasibility=feasibility,
            public_bidding_time_cost_days=public_bidding_cost,
            fallback_trigger_recommendation=fallback,
            selected_confidence_days=confidence_days,
            deadline_risk_level=estimate.deadline_risk_level,
            explanation=estimate.explanation,
        )

    @staticmethod
    def _feasibility(confidence_days: int, deadline_days: int | None) -> str:
        if deadline_days is None:
            return "unknown_without_deadline"
        if confidence_days <= deadline_days:
            return "feasible"
        if confidence_days <= deadline_days + 5:
            return "tight"
        return "not_feasible_without_fallback"

    def _timeout_fallback(
        self,
        requirement: BuyerRequirement,
        strategy: RFQStrategy,
        supplier_count: int,
    ) -> GLTGSimulation:
        deadline = requirement.delivery_days or 45
        p50 = max(deadline, 30)
        p80 = p50 + 7
        p90 = p80 + 7
        selected = {"P50": p50, "P80": p80, "P90": p90}[strategy.lead_time_confidence]
        return GLTGSimulation(
            p50_days=p50,
            p80_days=p80,
            p90_days=p90,
            minimum_feasible_days=max(p50 - 10, 1),
            supplier_set_feasibility="fallback_due_to_timeout" if supplier_count else "thin",
            known_suppliers_first_feasibility="unknown_due_to_timeout",
            public_bidding_time_cost_days=5,
            fallback_trigger_recommendation=FallbackTrigger(
                min_valid_supplier_replies=max(strategy.fallback_trigger.min_valid_supplier_replies, 2),
                max_wait_hours=min(strategy.fallback_trigger.max_wait_hours, 24),
                lead_time_risk_threshold="high",
            ),
            selected_confidence_days=selected,
            deadline_risk_level="high",
            explanation="GLTG simulation timed out; returned conservative fallback estimate for approval workflow continuity.",
        )
