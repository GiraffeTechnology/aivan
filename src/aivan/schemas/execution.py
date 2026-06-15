from pydantic import BaseModel, Field

class MilestoneStatus(BaseModel):
    name: str
    status: str = "pending"
    scheduled_date: str | None = None
    actual_date: str | None = None
    notes: str = ""

class ExecutionEvent(BaseModel):
    event_id: str
    project_id: str
    event_type: str
    actor: str = "system"
    summary: str
    payload: dict = Field(default_factory=dict)
    created_at: str = ""

class OrderExecution(BaseModel):
    execution_id: str
    project_id: str
    selected_option_id: str = ""
    supplier_id: str = ""
    candidate_id: str = ""
    status: str = "pending_acceptance"
    milestones: list[MilestoneStatus] = Field(default_factory=list)
    events: list[ExecutionEvent] = Field(default_factory=list)
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
