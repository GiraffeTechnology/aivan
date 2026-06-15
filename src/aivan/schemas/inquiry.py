from pydantic import BaseModel, Field
from enum import Enum

class DraftStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    sent = "sent"
    failed = "failed"

class InquiryDraft(BaseModel):
    draft_id: str
    project_id: str
    conversation_id: str = ""
    channel: str = ""
    target_peer_id: str = ""
    target_role: str = ""
    message_text: str
    message_type: str = "text"
    attachments: list[dict] = Field(default_factory=list)
    status: DraftStatus = DraftStatus.pending
    created_by_agent: str = ""
    approved_by: str = ""
    notes: str = ""
    created_at: str = ""
    approved_at: str | None = None
    sent_at: str | None = None
