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
