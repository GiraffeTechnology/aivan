from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from aiven.db.models import Base

class Project(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    channel: Mapped[str] = mapped_column(String(64), default="")
    channel_account_id: Mapped[str] = mapped_column(String(128), default="")
    customer_id: Mapped[str] = mapped_column(String(128), index=True)
    customer_display_name: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(64), default="active", index=True)
    category: Mapped[str] = mapped_column(String(128), default="")
    requirement_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    selected_option_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
