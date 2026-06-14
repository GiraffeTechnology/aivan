from __future__ import annotations
from pydantic import BaseModel, Field
from dataclasses import dataclass, field

class SupplierProfile(BaseModel):
    supplier_id: str
    name: str
    company_type: str = ""
    categories: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    moq_min: int = 0
    moq_max: int = 0
    daily_capacity: int = 0
    monthly_capacity: int = 0
    region: str = ""
    country: str = ""
    languages: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    email: str = ""
    openclaw_peer_id: str = ""
    payment_terms: str = ""
    incoterms_supported: list[str] = Field(default_factory=list)
    logistics_modes: list[str] = Field(default_factory=list)
    quality_score: float = 0.0
    delivery_score: float = 0.0
    price_score: float = 0.0
    past_performance_score: float = 0.0
    risk_tags: list[str] = Field(default_factory=list)
    notes: str = ""
    active: bool = True

class SupplierMatch(BaseModel):
    supplier: SupplierProfile
    match_score: float = 0.0
    category_fit: float = 0.0
    capability_fit: float = 0.0
    material_fit: float = 0.0
    moq_fit: float = 0.0
    capacity_fit: float = 0.0
    leadtime_score: float = 0.0
    price_score: float = 0.0
    quality_score: float = 0.0
    risk_penalty: float = 0.0
    match_reason: str = ""
