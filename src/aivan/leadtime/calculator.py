from __future__ import annotations
import math
from aivan.leadtime.models import LeadTimeComponent, LeadTimeEstimate
from aivan.utils.ids import new_estimate_id

APPAREL_DEFAULTS = {
    "requirement_clarification_days": 1,
    "supplier_response_sla_days": 2,
    "material_procurement_days": 7,
    "sample_days": 5,
    "pre_production_approval_days": 2,
    "cutting_days": 2,
    "sewing_days": None,
    "finishing_days": 2,
    "inline_qc_days": 1,
    "final_qc_days": 2,
    "packaging_days": 1,
    "domestic_transport_days": 2,
    "export_customs_days": 3,
    "international_transit_days": 4,
    "import_customs_days": 3,
    "final_mile_days": 2,
    "risk_buffer_days": 5,
}

SEA_TRANSIT_DAYS = {"Vancouver": 18, "Los Angeles": 14, "New York": 28, "London": 25, "Rotterdam": 22}
AIR_TRANSIT_DAYS = {"Vancouver": 3, "Los Angeles": 2, "New York": 3, "London": 2, "Rotterdam": 2}

def _get_transit_days(destination: str, logistics_preference: str) -> int:
    dest_lower = (destination or "").lower()
    if "air" in (logistics_preference or "").lower():
        for city, days in AIR_TRANSIT_DAYS.items():
            if city.lower() in dest_lower:
                return days
        return 4
    for city, days in SEA_TRANSIT_DAYS.items():
        if city.lower() in dest_lower:
            return days
    return 20

def calculate_apparel_leadtime(
    quantity: int,
    daily_capacity: int = 500,
    destination: str = "",
    logistics_preference: str = "sea",
    declared_lead_time_days: int | None = None,
    project_id: str = "",
    supplier_id: str | None = None,
    candidate_id: str | None = None,
    deadline_days: int | None = None,
) -> LeadTimeEstimate:
    efficiency_factor = 0.85
    effective_daily_cap = max(int(daily_capacity * efficiency_factor), 1)
    sewing_days = max(math.ceil(quantity / effective_daily_cap), 1) + 2

    transit_days = _get_transit_days(destination, logistics_preference)
    is_air = "air" in (logistics_preference or "").lower()

    components = [
        LeadTimeComponent(name="requirement_clarification", days=1, source="default"),
        LeadTimeComponent(name="supplier_response_sla", days=2, source="default"),
        LeadTimeComponent(name="material_procurement", days=7, source="default"),
        LeadTimeComponent(name="sample_and_approval", days=7, source="default"),
        LeadTimeComponent(name="production_cutting_sewing_finishing", days=sewing_days, source="calculated", notes=f"qty={quantity}, daily_cap={effective_daily_cap}"),
        LeadTimeComponent(name="inline_qc", days=1, source="default"),
        LeadTimeComponent(name="final_qc", days=2, source="default"),
        LeadTimeComponent(name="packaging", days=1, source="default"),
        LeadTimeComponent(name="domestic_transport", days=2, source="default"),
        LeadTimeComponent(name="export_customs", days=3, source="default"),
        LeadTimeComponent(name="international_transit", days=transit_days, source="calculated", notes=f"{'air' if is_air else 'sea'} to {destination}"),
        LeadTimeComponent(name="import_customs", days=3, source="default"),
        LeadTimeComponent(name="final_mile", days=2, source="default"),
    ]

    base_total = sum(c.days for c in components)
    risk_buffer = 5
    risk_buffer_comp = LeadTimeComponent(name="risk_buffer", days=risk_buffer, source="default", notes="5-day buffer for schedule slippage")
    components.append(risk_buffer_comp)

    calculated_total = base_total + risk_buffer
    earliest = base_total - 3
    expected = calculated_total
    conservative = calculated_total + 5
    p50 = expected
    p80 = conservative
    p90 = conservative + 5

    warnings = []
    if declared_lead_time_days and declared_lead_time_days < base_total * 0.7:
        warnings.append("lead_time_too_aggressive")

    deadline_feasible = None
    deadline_risk_level = "unknown"
    if deadline_days is not None:
        if deadline_days >= conservative:
            deadline_feasible = True
            deadline_risk_level = "low"
        elif deadline_days >= expected:
            deadline_feasible = True
            deadline_risk_level = "medium"
        elif deadline_days >= earliest:
            deadline_feasible = None
            deadline_risk_level = "high"
        else:
            deadline_feasible = False
            deadline_risk_level = "critical"

    critical_path = ["material_procurement", "production_cutting_sewing_finishing", f"international_transit ({transit_days}d)"]

    missing_inputs = []
    supplier_questions = []
    if daily_capacity == 500:
        missing_inputs.append("actual_daily_capacity")
        supplier_questions.append("What is your actual daily production capacity for this product?")

    explanation = (
        f"Apparel production for {quantity} pcs: {sewing_days} production days at {effective_daily_cap} pcs/day. "
        f"Material procurement: 7 days. Sample/approval: 7 days. "
        f"International transit ({'air' if is_air else 'sea'}) to {destination}: {transit_days} days. "
        f"Total calculated: {calculated_total} days."
    )
    if warnings:
        explanation += f" WARNING: {', '.join(warnings)}"

    return LeadTimeEstimate(
        estimate_id=new_estimate_id(),
        project_id=project_id,
        supplier_id=supplier_id,
        candidate_id=candidate_id,
        category="apparel",
        quantity=quantity,
        destination=destination,
        declared_lead_time_days=declared_lead_time_days,
        calculated_lead_time_days=calculated_total,
        earliest_possible_days=earliest,
        expected_days=expected,
        conservative_days=conservative,
        p50_days=p50,
        p80_days=p80,
        p90_days=p90,
        risk_buffer_days=risk_buffer,
        deadline_days=deadline_days,
        deadline_feasible=deadline_feasible,
        deadline_risk_level=deadline_risk_level,
        critical_path=critical_path,
        components=components,
        missing_inputs=missing_inputs,
        supplier_questions=supplier_questions,
        explanation=explanation,
    )

def calculate_leadtime_for_requirement(
    requirement,
    supplier_reply=None,
    supplier_id: str | None = None,
    candidate_id: str | None = None,
) -> LeadTimeEstimate:
    quantity = getattr(requirement, "quantity", None) or 1000
    destination = getattr(requirement, "destination", "")
    logistics_preference = getattr(requirement, "logistics_preference", "sea")
    deadline_days = getattr(requirement, "delivery_days", None)

    daily_capacity = 500
    declared_lead_time = None
    if supplier_reply:
        daily_capacity = getattr(supplier_reply, "capacity_per_day", None) or 500
        declared_lead_time = getattr(supplier_reply, "lead_time_days", None)

    project_id = getattr(requirement, "project_id", "")
    category = getattr(requirement, "category", "apparel").lower()

    if "cnc" in category or "machining" in category:
        return calculate_apparel_leadtime(quantity, daily_capacity, destination, logistics_preference, declared_lead_time, project_id, supplier_id, candidate_id, deadline_days)

    return calculate_apparel_leadtime(
        quantity=quantity,
        daily_capacity=daily_capacity,
        destination=destination,
        logistics_preference=logistics_preference,
        declared_lead_time_days=declared_lead_time,
        project_id=project_id,
        supplier_id=supplier_id,
        candidate_id=candidate_id,
        deadline_days=deadline_days,
    )
