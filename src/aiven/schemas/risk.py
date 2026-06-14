from pydantic import BaseModel, Field

class SupplierRiskEvidence(BaseModel):
    evidence_id: str
    source_type: str
    title: str
    url: str | None = None
    publisher: str | None = None
    published_date: str | None = None
    fetched_at: str = ""
    snippet: str
    relevance: str = "medium"
    reliability_score: float = 0.5
    risk_signal: str | None = None
    supports_claims: list[str] = Field(default_factory=list)
    contradicts_claims: list[str] = Field(default_factory=list)

class SupplierRiskScore(BaseModel):
    supplier_id: str | None = None
    candidate_id: str | None = None
    risk_level: str = "unknown"
    risk_score: float = 0.0
    confidence_score: float = 0.0
    positive_signals: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    missing_evidence: list[str] = Field(default_factory=list)
    recommended_action: str = "manual_review_required"

class SupplierRiskReport(BaseModel):
    report_id: str
    supplier_id: str | None = None
    candidate_id: str | None = None
    supplier_name: str
    risk_score: SupplierRiskScore
    evidence: list[SupplierRiskEvidence] = Field(default_factory=list)
    search_plan_summary: str = ""
    created_at: str = ""
    notes: str = ""
