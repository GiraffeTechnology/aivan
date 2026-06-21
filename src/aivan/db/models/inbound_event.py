from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from aivan.db.models import Base


class InboundRelayEvent(Base):
    """Pasted inbound messages submitted through the Giraffe guided-relay UI."""

    __tablename__ = "inbound_relay_events"

    inbound_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # thread_id corresponds to the conversation_id used in the pipeline
    thread_id: Mapped[str] = mapped_column(String(128), index=True)
    counterparty_id: Mapped[str] = mapped_column(String(256), default="")
    channel: Mapped[str] = mapped_column(String(64), default="")
    pasted_text: Mapped[str] = mapped_column(Text, default="")
    # execution_events row created to represent this inbound in the pipeline
    linked_execution_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # True once a reversal event has superseded this inbound
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
