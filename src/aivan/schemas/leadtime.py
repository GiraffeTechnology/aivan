"""Lead-time DTOs.

These are data containers only -- no calculation lives here. All lead-time
computation is owned by the standalone GLTG service and reached via
``aivan.integrations.gltg``. (Previously these models lived in the now-removed local calculation package.)
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LeadTimeComponent(BaseModel):
    name: str
    days: float = Field(ge=0, allow_inf_nan=False)
    source: str = "estimated"
    confidence: float = 0.7
    notes: str | None = None


class LeadTimeEstimate(BaseModel):
    estimate_id: str
    project_id: str
    supplier_id: str | None = None
    candidate_id: str | None = None
    category: str
    quantity: int | None = None
    destination: str | None = None
    declared_lead_time_days: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    calculated_lead_time_days: float = Field(ge=0, allow_inf_nan=False)
    earliest_possible_days: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    expected_days: float = Field(ge=0, allow_inf_nan=False)
    conservative_days: float = Field(ge=0, allow_inf_nan=False)
    p50_days: float = Field(ge=0, allow_inf_nan=False)
    p80_days: float = Field(ge=0, allow_inf_nan=False)
    p90_days: float = Field(ge=0, allow_inf_nan=False)
    risk_buffer_days: float = Field(ge=0, allow_inf_nan=False)
    deadline_days: int | None = None
    deadline_feasible: bool | None = None
    deadline_risk_level: str = "unknown"
    critical_path: list[str] = Field(default_factory=list)
    components: list[LeadTimeComponent] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    supplier_questions: list[str] = Field(default_factory=list)
    explanation: str = ""


__all__ = ["LeadTimeComponent", "LeadTimeEstimate"]
