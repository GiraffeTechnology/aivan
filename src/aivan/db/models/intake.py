from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aivan.db.models import Base


class InquirySheet(Base):
    __tablename__ = "inquiry_sheets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(64), default="active", index=True)
    source: Mapped[str] = mapped_column(String(64), default="openclaw")
    channel: Mapped[str] = mapped_column(String(64), default="unknown", index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    sender_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    normalized_product: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    product_category: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_deadline: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quality_level: Mapped[str | None] = mapped_column(String(128), nullable=True)
    material: Mapped[str | None] = mapped_column(String(128), nullable=True)
    spec_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    match_fingerprint: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    messages: Mapped[list["InquiryMessage"]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan"
    )


class InquiryMessage(Base):
    __tablename__ = "inquiry_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sheet_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("inquiry_sheets.id"), nullable=False, index=True
    )
    raw_text: Mapped[str] = mapped_column(Text, default="")
    raw_event_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    structured_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="openclaw")
    channel: Mapped[str] = mapped_column(String(64), default="unknown")
    conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    sender_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    message_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    match_decision: Mapped[str] = mapped_column(String(64), default="new_temporary", index=True)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    sheet: Mapped[InquirySheet] = relationship(back_populates="messages")
