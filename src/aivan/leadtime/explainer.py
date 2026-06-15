from __future__ import annotations
from aivan.leadtime.models import LeadTimeEstimate

def explain_leadtime(estimate: LeadTimeEstimate) -> str:
    lines = [
        f"=== LEAD TIME ESTIMATE ===",
        f"Category: {estimate.category}",
        f"Quantity: {estimate.quantity} pcs",
        f"Destination: {estimate.destination}",
        f"",
        f"TIMELINE (days from now):",
        f"  Earliest possible:  {estimate.earliest_possible_days} days",
        f"  Expected (P50):     {estimate.p50_days} days",
        f"  Conservative (P80): {estimate.p80_days} days",
        f"  High-safety (P90):  {estimate.p90_days} days",
        f"  Risk buffer:        {estimate.risk_buffer_days} days",
        f"",
    ]
    if estimate.deadline_days:
        feasible_str = "YES" if estimate.deadline_feasible else ("UNCERTAIN" if estimate.deadline_feasible is None else "NO")
        lines += [
            f"DEADLINE: {estimate.deadline_days} days",
            f"FEASIBLE: {feasible_str} (risk: {estimate.deadline_risk_level.upper()})",
            "",
        ]
    lines.append("BREAKDOWN:")
    for comp in estimate.components:
        lines.append(f"  {comp.name}: {comp.days} days ({comp.source})")
    lines.append("")
    lines.append(f"CRITICAL PATH: {' → '.join(estimate.critical_path)}")
    if estimate.supplier_questions:
        lines.append("")
        lines.append("QUESTIONS FOR SUPPLIER:")
        for q in estimate.supplier_questions:
            lines.append(f"  ? {q}")
    lines.append("")
    lines.append(estimate.explanation)
    return "\n".join(lines)
