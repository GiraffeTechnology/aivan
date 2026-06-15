from __future__ import annotations
from aivan.schemas.execution import OrderExecution, MilestoneStatus
from aivan.utils.ids import new_execution_id
from aivan.utils.time_utils import utcnow_iso

APPAREL_MILESTONES = [
    "supplier_acceptance",
    "material_ready",
    "production_started",
    "production_50pct",
    "inline_qc",
    "final_qc",
    "packaging",
    "logistics_handover",
    "tracking_update",
    "buyer_signoff",
]

def create_order_execution(
    project_id: str,
    selected_option_id: str = "",
    supplier_id: str = "",
    candidate_id: str = "",
    category: str = "apparel",
) -> OrderExecution:
    milestones = [MilestoneStatus(name=m) for m in APPAREL_MILESTONES]
    return OrderExecution(
        execution_id=new_execution_id(),
        project_id=project_id,
        selected_option_id=selected_option_id,
        supplier_id=supplier_id,
        candidate_id=candidate_id,
        status="pending_acceptance",
        milestones=milestones,
        created_at=utcnow_iso(),
        updated_at=utcnow_iso(),
    )

def update_milestone(execution: OrderExecution, milestone_name: str, status: str, notes: str = "") -> OrderExecution:
    for m in execution.milestones:
        if m.name == milestone_name:
            m.status = status
            m.actual_date = utcnow_iso() if status == "completed" else None
            m.notes = notes
    execution.updated_at = utcnow_iso()
    return execution
