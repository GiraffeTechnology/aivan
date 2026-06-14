from __future__ import annotations
from aiven.sourcing.supplier_models import SupplierProfile, SupplierMatch
from aiven.sourcing.supplier_registry import list_active

def _score_list_overlap(req_items: list[str], sup_items: list[str]) -> float:
    if not req_items:
        return 1.0
    if not sup_items:
        return 0.0
    req_lower = {r.lower() for r in req_items}
    sup_lower = {s.lower() for s in sup_items}
    matches = sum(1 for r in req_lower if any(r in s or s in r for s in sup_lower))
    return min(1.0, matches / len(req_lower))

def _score_moq(required_qty: int | None, moq_min: int, moq_max: int) -> float:
    if required_qty is None:
        return 0.8
    if moq_min == 0 and moq_max == 0:
        return 0.5
    if moq_max > 0 and required_qty > moq_max:
        return 0.3
    if required_qty >= moq_min:
        return 1.0
    ratio = required_qty / max(moq_min, 1)
    return max(0.0, ratio * 0.8)

def _score_capacity(required_qty: int | None, daily_cap: int, monthly_cap: int, delivery_days: int | None) -> float:
    if required_qty is None or delivery_days is None:
        return 0.5
    if monthly_cap > 0 and required_qty <= monthly_cap:
        return 1.0
    if daily_cap > 0:
        days_needed = required_qty / daily_cap
        if delivery_days and days_needed <= delivery_days * 0.7:
            return 1.0
        elif delivery_days and days_needed <= delivery_days:
            return 0.8
        else:
            return 0.3
    return 0.5

def match_suppliers_for_requirement(
    requirement,
    limit: int = 10,
) -> list[SupplierMatch]:
    suppliers = list_active()
    if not suppliers:
        return []

    categories = [requirement.category] if hasattr(requirement, "category") and requirement.category else []
    materials = []
    if hasattr(requirement, "fabric_material") and requirement.fabric_material:
        materials = [requirement.fabric_material]
    elif hasattr(requirement, "material_spec") and requirement.material_spec:
        materials = [requirement.material_spec]

    qty = getattr(requirement, "quantity", None)
    delivery_days = getattr(requirement, "delivery_days", None)

    matches = []
    for sup in suppliers:
        cat_fit = _score_list_overlap(categories, sup.categories)
        mat_fit = _score_list_overlap(materials, sup.materials) if materials else 0.8
        moq_fit = _score_moq(qty, sup.moq_min, sup.moq_max)
        cap_fit = _score_capacity(qty, sup.daily_capacity, sup.monthly_capacity, delivery_days)
        risk_pen = len(sup.risk_tags) * 0.05

        overall = (
            cat_fit * 0.30
            + mat_fit * 0.20
            + moq_fit * 0.20
            + cap_fit * 0.15
            + sup.quality_score * 0.10
            + sup.delivery_score * 0.05
            - risk_pen
        )
        overall = max(0.0, min(1.0, overall))

        reason_parts = []
        if cat_fit > 0.5:
            reason_parts.append(f"category match: {cat_fit:.0%}")
        if mat_fit > 0.5:
            reason_parts.append(f"material match: {mat_fit:.0%}")
        if moq_fit >= 1.0:
            reason_parts.append("MOQ fits")
        elif moq_fit < 0.5:
            reason_parts.append("MOQ concern")

        matches.append(SupplierMatch(
            supplier=sup,
            match_score=overall,
            category_fit=cat_fit,
            material_fit=mat_fit,
            moq_fit=moq_fit,
            capacity_fit=cap_fit,
            quality_score=sup.quality_score,
            risk_penalty=risk_pen,
            match_reason="; ".join(reason_parts) if reason_parts else "general match",
        ))

    matches.sort(key=lambda m: m.match_score, reverse=True)
    return matches[:limit]
