from __future__ import annotations
from aivan.schemas.execution import OrderExecution, MilestoneStatus
from aivan.execution.order_execution import create_order_execution, update_milestone
from aivan.execution.event_log import append_event
from aivan.utils.time_utils import utcnow_iso

def start_order_execution(
    db_session,
    project_id: str,
    selected_option,
    supplier_id: str = "",
    candidate_id: str = "",
) -> OrderExecution:
    execution = create_order_execution(
        project_id=project_id,
        selected_option_id=getattr(selected_option, "option_id", ""),
        supplier_id=supplier_id,
        candidate_id=candidate_id,
    )
    append_event(db_session, project_id, "ORDER_CONFIRMED", f"Order confirmed. Execution started.", actor="trade_salesperson_agent")
    return execution

def process_production_update(db_session, project_id: str, execution: OrderExecution, update_text: str) -> OrderExecution:
    append_event(db_session, project_id, "PRODUCTION_UPDATE_RECEIVED", f"Production update: {update_text[:100]}", actor="supplier")
    if "started" in update_text.lower():
        execution = update_milestone(execution, "production_started", "completed")
    elif "50%" in update_text or "halfway" in update_text.lower():
        execution = update_milestone(execution, "production_50pct", "completed")
    return execution

def process_qc_update(db_session, project_id: str, execution: OrderExecution, update_text: str) -> OrderExecution:
    append_event(db_session, project_id, "QC_UPDATE_RECEIVED", f"QC update: {update_text[:100]}", actor="supplier")
    if "inline" in update_text.lower() and "pass" in update_text.lower():
        execution = update_milestone(execution, "inline_qc", "completed")
    if "final" in update_text.lower() and "pass" in update_text.lower():
        execution = update_milestone(execution, "final_qc", "completed")
    return execution

def process_logistics_update(db_session, project_id: str, execution: OrderExecution, update_text: str) -> OrderExecution:
    append_event(db_session, project_id, "LOGISTICS_UPDATE_RECEIVED", f"Logistics: {update_text[:100]}", actor="logistics")
    if "handover" in update_text.lower() or "shipped" in update_text.lower():
        execution = update_milestone(execution, "logistics_handover", "completed")
    return execution
