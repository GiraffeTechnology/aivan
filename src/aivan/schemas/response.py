from pydantic import BaseModel, Field

class SupplierReply(BaseModel):
    project_id: str
    supplier_id: str = ""
    candidate_id: str = ""
    raw_text: str
    channel: str = ""
    unit_price: float | None = None
    currency: str = "USD"
    moq: int | None = None
    capacity_per_day: int | None = None
    capacity_per_month: int | None = None
    lead_time_days: int | None = None
    material_availability: str = ""
    qc_commitment: str = ""
    logistics_note: str = ""
    incoterms: str = ""
    payment_terms: str = ""
    risks: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    raw_payload: dict = Field(default_factory=dict)
    received_at: str = ""
