from datetime import datetime, timezone

from sqlalchemy import DateTime, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aivan.db.models import Base


class RelayReceiptRecord(Base):
    """Immutable proof that a guided-relay draft was manually delivered."""

    __tablename__ = "relay_receipts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "draft_id", name="uq_relay_receipt_draft"),
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_relay_receipt_idempotency"
        ),
    )

    receipt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    draft_id: Mapped[str] = mapped_column(String(64), index=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(64), index=True)
    channel_account_id: Mapped[str] = mapped_column(String(128), default="")
    conversation_id: Mapped[str] = mapped_column(String(128), default="")
    external_message_id: Mapped[str] = mapped_column(String(255), default="")
    receipt_reference: Mapped[str] = mapped_column(String(255), default="")
    idempotency_key: Mapped[str] = mapped_column(String(255), index=True)
    confirmed_by: Mapped[str] = mapped_column(String(128), default="", index=True)
    source_trace_id: Mapped[str] = mapped_column(String(255), default="", index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
