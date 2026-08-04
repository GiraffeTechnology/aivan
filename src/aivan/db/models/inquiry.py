from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from aivan.db.models import Base

class InquiryDraftRecord(Base):
    __tablename__ = "inquiry_drafts"

    draft_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), default="legacy", index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    participant_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    source_trace_id: Mapped[str] = mapped_column(String(255), default="", index=True)
    conversation_id: Mapped[str] = mapped_column(String(128), default="")
    channel: Mapped[str] = mapped_column(String(64), default="")
    channel_account_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    target_peer_id: Mapped[str] = mapped_column(String(256), default="")
    target_role: Mapped[str] = mapped_column(String(64), default="")
    message_text: Mapped[str] = mapped_column(Text, default="")
    message_type: Mapped[str] = mapped_column(String(64), default="text")
    attachments_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="pending_approval", index=True)
    created_by_agent: Mapped[str] = mapped_column(String(128), default="")
    created_by_actor_id: Mapped[str] = mapped_column(String(128), default="")
    created_by_actor_role: Mapped[str] = mapped_column(String(64), default="")
    approved_by: Mapped[str] = mapped_column(String(128), default="")
    approval_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    authorization_basis: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
