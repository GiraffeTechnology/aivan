from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aivan.db.models import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CaseConversationRecord(Base):
    """A role-specific external conversation attached to one canonical Case."""

    __tablename__ = "case_conversations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "case_id",
            "external_conversation_id",
            "conversation_role",
            "channel",
            "channel_account_id",
            name="uq_case_conversation_binding",
        ),
    )

    conversation_record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    external_conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    conversation_role: Mapped[str] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(64), default="")
    channel_account_id: Mapped[str] = mapped_column(String(128), default="")
    thread_key: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class CaseParticipantRecord(Base):
    """A business actor's membership in a role-specific Case thread."""

    __tablename__ = "case_participants"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "case_id",
            "actor_id",
            "business_role",
            "conversation_record_id",
            name="uq_case_participant_membership",
        ),
    )

    participant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_record_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), index=True)
    business_role: Mapped[str] = mapped_column(String(64), index=True)
    conversation_role: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class CaseMessageRecord(Base):
    """Idempotent inbound message evidence within a bound Case conversation."""

    __tablename__ = "case_messages"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "case_id",
            "conversation_record_id",
            "source_message_id",
            name="uq_case_message_source",
        ),
    )

    message_record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_record_id: Mapped[str] = mapped_column(String(64), index=True)
    participant_id: Mapped[str] = mapped_column(String(64), index=True)
    source_message_id: Mapped[str] = mapped_column(String(255), index=True)
    source_trace_id: Mapped[str] = mapped_column(String(255), default="", index=True)
    actor_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_role: Mapped[str] = mapped_column(String(64), index=True)
    asserted_by_actor_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    asserted_by_actor_role: Mapped[str] = mapped_column(String(64), default="", index=True)
    conversation_role: Mapped[str] = mapped_column(String(64), index=True)
    message_type: Mapped[str] = mapped_column(String(64), default="text")
    payload_digest: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ApprovalRecord(Base):
    """Authorization evidence for an outbound draft decision."""

    __tablename__ = "approvals"

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    draft_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    requested_by_actor_id: Mapped[str] = mapped_column(String(128), default="")
    requested_by_actor_role: Mapped[str] = mapped_column(String(64), default="")
    approver_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    approver_role: Mapped[str] = mapped_column(String(64), default="", index=True)
    source_trace_id: Mapped[str] = mapped_column(String(255), default="", index=True)
    authorization_basis: Mapped[str] = mapped_column(Text, default="")
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLogRecord(Base):
    """Append-only authorization and state-transition evidence."""

    __tablename__ = "audit_logs"

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    case_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    source_trace_id: Mapped[str] = mapped_column(String(255), default="", index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    actor_role: Mapped[str] = mapped_column(String(64), default="", index=True)
    conversation_role: Mapped[str] = mapped_column(String(64), default="")
    authorization_basis: Mapped[str] = mapped_column(Text, default="")
    before_json: Mapped[dict] = mapped_column(JSON, default=dict)
    after_json: Mapped[dict] = mapped_column(JSON, default=dict)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

