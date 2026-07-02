from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from aivan.db.models import Base

class ExecutionEventRecord(Base):
    __tablename__ = "execution_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    actor: Mapped[str] = mapped_column(String(128), default="system")
    summary: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class ProcessedInboundEvent(Base):
    """Idempotency ledger for inbound OpenClaw/IM/webhook events.

    A retried or duplicated inbound event (same source+channel+account+
    conversation+message) must not create duplicate projects, RFQs, drafts, or
    execution events. The first successful processing is recorded here keyed by a
    stable idempotency key; later duplicates replay the stored result instead of
    re-running side effects.
    """

    __tablename__ = "processed_inbound_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Unique so a concurrent duplicate also collides at the DB level.
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    event_type: Mapped[str] = mapped_column(String(128), default="")
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
