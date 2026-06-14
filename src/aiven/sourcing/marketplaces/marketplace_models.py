from pydantic import BaseModel, Field

class MarketplaceSupplierCandidate(BaseModel):
    candidate_id: str
    platform: str
    platform_supplier_id: str | None = None
    supplier_name: str
    product_title: str | None = None
    product_url: str | None = None
    storefront_url: str | None = None
    categories: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    moq: int | None = None
    price_min: float | None = None
    price_max: float | None = None
    currency: str | None = None
    region: str | None = None
    country: str | None = None
    years_on_platform: int | None = None
    verification_badges: list[str] = Field(default_factory=list)
    transaction_signals: dict = Field(default_factory=dict)
    rating_signals: dict = Field(default_factory=dict)
    delivery_signals: dict = Field(default_factory=dict)
    contact_channels: dict = Field(default_factory=dict)
    openclaw_peer_id: str | None = None
    wangwang_id: str | None = None
    source: str = "unknown"
    source_url: str | None = None
    confidence_score: float = 0.0
    risk_flags: list[str] = Field(default_factory=list)
    raw_payload: dict = Field(default_factory=dict)

class SearchResult(BaseModel):
    query: str
    platform: str
    candidates: list[MarketplaceSupplierCandidate] = Field(default_factory=list)
    total_found: int = 0
    connector_mode: str = "mock"
    error: str | None = None
