from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from aivan.db.models import Base

class ExecutionEventRecord(Base):
    __tablename__ = "execution_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), default="legacy", index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    source_trace_id: Mapped[str] = mapped_column(String(255), default="", index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    actor: Mapped[str] = mapped_column(String(128), default="system")
    actor_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    actor_role: Mapped[str] = mapped_column(String(64), default="")
    conversation_role: Mapped[str] = mapped_column(String(64), default="")
    authorization_basis: Mapped[str] = mapped_column(Text, default="")
    before_json: Mapped[dict] = mapped_column(JSON, default=dict)
    after_json: Mapped[dict] = mapped_column(JSON, default=dict)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    derived_from_event_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    payload_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    correction_status: Mapped[str] = mapped_column(String(32), default="", index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class EventReversalRecord(Base):
    """Append-only evidence for one reversal or compensating event."""

    __tablename__ = "event_reversals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_event_id", name="uq_event_reversal_source"),
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_event_reversal_idempotency"
        ),
    )

    reversal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    source_event_id: Mapped[str] = mapped_column(String(64), index=True)
    correction_event_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    actor_role: Mapped[str] = mapped_column(String(64), default="")
    source_trace_id: Mapped[str] = mapped_column(String(255), default="", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    source_payload_digest: Mapped[str] = mapped_column(String(64), default="")
    impact_digest: Mapped[str] = mapped_column(String(64), default="")
    before_ref_json: Mapped[dict] = mapped_column(JSON, default=dict)
    after_ref_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


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
    tenant_id: Mapped[str] = mapped_column(String(128), default="legacy", index=True)
    # Unique so a concurrent duplicate also collides at the DB level.
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    event_type: Mapped[str] = mapped_column(String(128), default="")
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
