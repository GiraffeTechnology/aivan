from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


EventType = Literal[
    "user_command",
    "customer_new_inquiry",
    "customer_followup",
    "customer_reply",
    "supplier_reply",
    "internal_status_request",
    "approval_response",
    "unknown",
]

StrategyPriority = Literal["speed", "price", "quality", "reliability", "balanced"]
SupplierScope = Literal[
    "known_suppliers_only",
    "known_suppliers_first",
    "public_bidding_first",
    "parallel_known_and_public",
]
PublicBiddingMode = Literal["enabled", "disabled", "fallback_only"]
LeadTimeConfidence = Literal["P50", "P80", "P90"]
Sensitivity = Literal["low", "medium", "high"]
RiskThreshold = Literal["low", "medium", "high"]


class FallbackTrigger(BaseModel):
    min_valid_supplier_replies: int = 2
    max_wait_hours: int = 24
    lead_time_risk_threshold: RiskThreshold = "medium"


class RFQStrategy(BaseModel):
    priority: StrategyPriority = "balanced"
    supplier_scope: SupplierScope = "known_suppliers_first"
    public_bidding: PublicBiddingMode = "fallback_only"
    lead_time_confidence: LeadTimeConfidence = "P80"
    price_sensitivity: Sensitivity = "medium"
    quality_sensitivity: Sensitivity = "medium"
    fallback_trigger: FallbackTrigger = Field(default_factory=FallbackTrigger)


class EventClassification(BaseModel):
    event_type: EventType = "unknown"
    confidence: float = 0.0
    reason: str = ""
    project_id: str | None = None
    validated_project_attachment: bool = False


class GiraffeContext(BaseModel):
    customers: list[dict] = Field(default_factory=list)
    customer_preferences: list[dict] = Field(default_factory=list)
    suppliers: list[dict] = Field(default_factory=list)
    supplier_relationships: list[dict] = Field(default_factory=list)
    historical_rfqs: list[dict] = Field(default_factory=list)
    historical_quotations: list[dict] = Field(default_factory=list)
    historical_lead_time_records: list[dict] = Field(default_factory=list)
    product_categories: list[dict] = Field(default_factory=list)
    user_preferences: list[dict] = Field(default_factory=list)
    approval_history: list[dict] = Field(default_factory=list)
    draft_revision_history: list[dict] = Field(default_factory=list)
    risk_flags: list[dict] = Field(default_factory=list)


class GLTGSimulation(BaseModel):
    p50_days: int
    p80_days: int
    p90_days: int
    minimum_feasible_days: int
    supplier_set_feasibility: str
    known_suppliers_first_feasibility: str
    public_bidding_time_cost_days: int
    fallback_trigger_recommendation: FallbackTrigger
    selected_confidence_days: int
    deadline_risk_level: str = "unknown"
    explanation: str = ""


class SupplierRoutingDecision(BaseModel):
    selected_supplier_ids: list[str] = Field(default_factory=list)
    skipped_supplier_ids: list[str] = Field(default_factory=list)
    public_bidding_mode: PublicBiddingMode = "fallback_only"
    rationale: str = ""


class RFQExecutionResult(BaseModel):
    project_id: str
    event_type: EventType
    action: str
    message: str
    strategy: RFQStrategy
    requirement: dict
    giraffe_context: GiraffeContext
    gltg_simulation: GLTGSimulation
    supplier_routing: SupplierRoutingDecision
    drafts_created: list[str] = Field(default_factory=list)
    user_control_message: str = ""
    errors: list[str] = Field(default_factory=list)
