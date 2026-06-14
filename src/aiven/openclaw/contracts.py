from pydantic import BaseModel, Field

class OpenClawEvent(BaseModel):
    source: str = "openclaw"
    channel: str = ""
    channel_account_id: str = ""
    conversation_id: str
    message_id: str = ""
    sender_id: str = ""
    sender_display_name: str = ""
    message_text: str = ""
    message_type: str = "text"
    attachments: list[dict] = Field(default_factory=list)
    timestamp: str = ""
    project_id: str | None = None
    actor_id: str | None = None
    role_context: str | None = None
    mode: str = "auto"

class OpenClawSendRequest(BaseModel):
    channel: str
    channel_account_id: str = ""
    conversation_id: str
    target_peer_id: str
    message_text: str
    message_type: str = "text"
    attachments: list[dict] = Field(default_factory=list)
    account_connection_id: str = ""

class OpenClawSendResponse(BaseModel):
    success: bool
    message_id: str = ""
    sent_at: str = ""
    error: str | None = None

class OpenClawManagedAccount(BaseModel):
    account_connection_id: str
    platform: str
    channel: str = ""
    channel_account_id: str = ""
    owner_user_id: str | None = None
    display_name: str | None = None
    status: str = "connected"
    permissions: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    expires_at: str | None = None
    created_at: str = ""
    updated_at: str = ""
    metadata: dict = Field(default_factory=dict)

ALLOWED_PERMISSIONS = [
    "read_messages",
    "send_approved_messages",
    "read_marketplace_search_results",
    "read_product_pages",
    "read_supplier_profiles",
    "open_seller_chat",
    "upload_approved_attachments",
    "read_order_status",
    "read_logistics_status",
]

FORBIDDEN_ACTIONS = [
    "place_order",
    "make_payment",
    "issue_refund",
    "change_password",
    "change_account_settings",
    "mass_message",
    "auto_register_account",
    "bypass_captcha",
    "bypass_platform_controls",
]
