"""myaivan Web UI persistence: inquiry cases, messages, drafts, audit logs.

These tables back the conversation-style web UI (PRD: AIVAN Web First
Iteration). They are deliberately separate from the OpenClaw execution tables
(projects / inquiry_drafts) — the web review workflow has its own draft
lifecycle (draft → copied → email_sent / manually_sent / rejected / failed).
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from aivan.db.models import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WebCaseRecord(Base):
    __tablename__ = "web_cases"

    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    source_channel: Mapped[str] = mapped_column(String(32), default="manual")
    target_channel: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WebCaseMessageRecord(Base):
    __tablename__ = "web_case_messages"

    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16), default="user")  # user | aivan | system
    message_type: Mapped[str] = mapped_column(String(32), default="text")
    content: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WebOutboundDraftRecord(Base):
    __tablename__ = "web_outbound_drafts"

    draft_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(32), default="manual")
    recipient: Mapped[str] = mapped_column(String(256), default="")
    subject: Mapped[str] = mapped_column(String(512), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="low")
    risk_notes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WebAttachmentRecord(Base):
    __tablename__ = "web_attachments"

    attachment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="file")  # file | image
    filename: Mapped[str] = mapped_column(String(512), default="")
    content_type: Mapped[str] = mapped_column(String(128), default="")
    size_bytes: Mapped[int] = mapped_column(default=0)
    storage_path: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WebAuditLogRecord(Base):
    __tablename__ = "web_audit_logs"

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    event: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
