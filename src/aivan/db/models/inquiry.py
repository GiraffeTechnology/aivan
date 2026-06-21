from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from aivan.db.models import Base


# Draft status machine:
#   pending_approval
#     -> approved -> sent           (auto channels: email, line)
#     -> approved -> awaiting_relay (guided-relay: wechat, wangwang)
#                    -> relayed
#     -> approved -> send_failed    (auto channels: delivery error)
#     -> rejected

class InquiryDraftRecord(Base):
    __tablename__ = "inquiry_drafts"

    draft_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[str] = mapped_column(String(128), default="")
    channel: Mapped[str] = mapped_column(String(64), default="")
    target_peer_id: Mapped[str] = mapped_column(String(256), default="")
    target_role: Mapped[str] = mapped_column(String(64), default="")
    message_text: Mapped[str] = mapped_column(Text, default="")
    message_type: Mapped[str] = mapped_column(String(64), default="text")
    attachments_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="pending_approval", index=True)
    created_by_agent: Mapped[str] = mapped_column(String(128), default="")
    approved_by: Mapped[str] = mapped_column(String(128), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    # Auto-channel send receipt (message_id, sent_at from adapter)
    sent_receipt_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Guided-relay confirmation
    relay_confirmed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    relay_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Delivery failure reason
    send_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Tracks which inbound event caused this draft (for reversal cascade)
    derived_from_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
