from pydantic import BaseModel, Field

RISK_FLAGS = [
    "identity_unverified",
    "company_name_inconsistent",
    "address_inconsistent",
    "contact_info_inconsistent",
    "storefront_new_or_low_history",
    "product_category_mismatch",
    "insufficient_public_presence",
    "negative_public_complaints",
    "litigation_or_enforcement_signal",
    "sanctions_or_restriction_signal",
    "unusual_payment_terms",
    "off_platform_payment_pressure",
    "price_too_low_vs_market",
    "lead_time_too_aggressive",
    "capacity_claim_unverified",
    "certificate_unverified",
    "high_refund_or_quality_complaint_signal",
    "unable_to_verify_factory",
    "platform_not_whitelisted",
    "platform_blocked",
]

RECOMMENDED_ACTIONS = [
    "safe_to_contact",
    "contact_but_verify",
    "request_business_license",
    "request_factory_video",
    "request_trade_references",
    "request_sample_first",
    "avoid_until_verified",
    "do_not_contact",
    "manual_review_required",
    "review_platform_before_contacting_supplier",
]

class SupplierRiskSearchPlan(BaseModel):
    supplier_name_queries: list[str] = Field(default_factory=list)
    platform_store_queries: list[str] = Field(default_factory=list)
    complaint_queries: list[str] = Field(default_factory=list)
    litigation_queries: list[str] = Field(default_factory=list)
    certification_queries: list[str] = Field(default_factory=list)
    product_category_queries: list[str] = Field(default_factory=list)
    address_contact_queries: list[str] = Field(default_factory=list)
    sanctions_or_restriction_queries: list[str] = Field(default_factory=list)
    reason: str = ""

class SearchResult(BaseModel):
    query: str
    url: str = ""
    title: str = ""
    snippet: str = ""
    publisher: str = ""
    published_date: str = ""
    source_type: str = "web"

class FetchedPage(BaseModel):
    url: str
    title: str = ""
    content: str = ""
    status_code: int = 200
    fetched_at: str = ""
    error: str | None = None

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
