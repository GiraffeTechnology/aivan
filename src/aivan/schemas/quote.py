from __future__ import annotations
from pydantic import BaseModel, Field

class QuoteCalculation(BaseModel):
    supplier_id: str = ""
    candidate_id: str = ""
    unit_price: float = 0.0
    quantity: int = 0
    moq: int = 0
    sample_fee: float = 0.0
    tooling_fee: float = 0.0
    packaging_fee: float = 0.0
    domestic_logistics_fee: float = 0.0
    international_logistics_fee: float = 0.0
    qc_fee: float = 0.0
    margin_rate: float = 0.15
    fixed_margin: float = 0.0
    currency: str = "USD"
    supplier_total: float = 0.0
    buyer_unit_price: float = 0.0
    buyer_total: float = 0.0
    margin_amount: float = 0.0
    effective_margin_rate: float = 0.0
    calculation_trace: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

class BuyerOption(BaseModel):
    option_id: str
    project_id: str
    option_label: str
    option_type: str
    supplier_id: str = ""
    candidate_id: str = ""
    supplier_display_name: str = ""
    lead_time_estimate: LeadTimeEstimate | None = None
    quote: QuoteCalculation | None = None
    risk_level: str = "unknown"
    deadline_feasible: bool | None = None
    deadline_risk_level: str = "unknown"
    reasoning: str = ""
    warnings: list[str] = Field(default_factory=list)
    status: str = "draft"

from aivan.schemas.leadtime import LeadTimeEstimate
BuyerOption.model_rebuild()
