import uuid
import time

def new_id(prefix: str = "") -> str:
    uid = str(uuid.uuid4()).replace("-", "")[:16]
    return f"{prefix}{uid}" if prefix else uid

def new_project_id() -> str:
    return f"proj_{new_id()}"

def new_supplier_id() -> str:
    return f"sup_{new_id()}"

def new_draft_id() -> str:
    return f"draft_{new_id()}"

def new_candidate_id() -> str:
    return f"cand_{new_id()}"

def new_estimate_id() -> str:
    return f"est_{new_id()}"

def new_evidence_id() -> str:
    return f"ev_{new_id()}"

def new_risk_report_id() -> str:
    return f"risk_{new_id()}"

def new_account_id() -> str:
    return f"oc_acc_{new_id()}"

def new_suggestion_id() -> str:
    return f"sug_{new_id()}"

def new_execution_id() -> str:
    return f"exec_{new_id()}"

def new_order_id() -> str:
    return f"ord_{new_id()}"

def timestamp_ms() -> int:
    return int(time.time() * 1000)
