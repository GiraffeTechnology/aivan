from __future__ import annotations
from aivan.schemas.execution import OrderExecution
from aivan.execution.event_log import append_event

EXCEPTION_TYPES = [
    "material_delay",
    "production_delay",
    "quality_failure",
    "logistics_delay",
    "supplier_unresponsive",
    "capacity_shortage",
    "price_dispute",
    "force_majeure",
]

def classify_exception(text: str) -> str:
    """Classify an exception from text description."""
    text_lower = text.lower()
    if any(w in text_lower for w in ["material", "fabric", "stock"]):
        return "material_delay"
    if any(w in text_lower for w in ["production", "factory", "manufacturing"]):
        return "production_delay"
    if any(w in text_lower for w in ["quality", "qc", "defect", "reject"]):
        return "quality_failure"
    if any(w in text_lower for w in ["logistics", "shipping", "port", "customs"]):
        return "logistics_delay"
    if any(w in text_lower for w in ["unresponsive", "no reply", "silent"]):
        return "supplier_unresponsive"
    return "unknown_exception"

def handle_exception(db_session, project_id: str, execution: OrderExecution, exception_text: str) -> dict:
    exception_type = classify_exception(exception_text)
    append_event(
        db_session, project_id, "EXCEPTION_DETECTED",
        f"Exception detected: {exception_type} - {exception_text[:100]}",
        payload={"exception_type": exception_type, "text": exception_text},
        actor="exception_agent",
    )

    options = []
    if exception_type == "material_delay":
        options = ["Wait for materials (update customer timeline)", "Source alternative materials", "Switch to backup supplier"]
    elif exception_type == "production_delay":
        options = ["Accept delay and update customer", "Request partial shipment", "Escalate to supplier management"]
    elif exception_type == "quality_failure":
        options = ["Request re-production", "Accept with discount", "Switch supplier"]
    elif exception_type == "logistics_delay":
        options = ["Switch to air freight", "Update customer ETA", "Request compensation"]
    else:
        options = ["Escalate to management", "Contact supplier directly", "Update customer"]

    return {
        "exception_type": exception_type,
        "project_id": project_id,
        "options": options,
        "requires_human_decision": True,
        "text": exception_text,
    }
