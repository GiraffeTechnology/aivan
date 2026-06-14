from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from aiven.db.models import Base

class OpenClawAccountRecord(Base):
    __tablename__ = "openclaw_accounts"

    account_connection_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    platform: Mapped[str] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(64), default="")
    channel_account_id: Mapped[str] = mapped_column(String(256), default="")
    owner_user_id: Mapped[str] = mapped_column(String(128), default="")
    display_name: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(32), default="connected", index=True)
    permissions_json: Mapped[list] = mapped_column(JSON, default=list)
    allowed_actions_json: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[str] = mapped_column(String(64), default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
