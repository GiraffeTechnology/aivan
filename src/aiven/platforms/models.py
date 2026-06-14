from pydantic import BaseModel, Field

class TrustedPlatform(BaseModel):
    platform_id: str
    display_name: str
    status: str = "pending_review"
    domain_patterns: list[str] = Field(default_factory=list)
    supported_channels: list[str] = Field(default_factory=list)
    supported_connectors: list[str] = Field(default_factory=list)
    allow_marketplace_search: bool = True
    allow_openclaw_account_management: bool = False
    allow_seller_im: bool = False
    risk_weight_modifier: float = 1.0
    added_by: str | None = None
    user_confirmed: bool = False
    built_in: bool = False
    created_at: str = ""
    updated_at: str = ""
    notes: str | None = None

class PlatformSuggestion(BaseModel):
    suggestion_id: str
    platform_id: str
    display_name: str
    domain: str
    reason: str
    status: str = "pending_review"
    created_at: str = ""
