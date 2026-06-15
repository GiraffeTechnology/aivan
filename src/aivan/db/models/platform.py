from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, JSON, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column
from aivan.db.models import Base

class PlatformRecord(Base):
    __tablename__ = "platforms"

    platform_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), default="pending_review", index=True)
    domain_patterns_json: Mapped[list] = mapped_column(JSON, default=list)
    supported_channels_json: Mapped[list] = mapped_column(JSON, default=list)
    supported_connectors_json: Mapped[list] = mapped_column(JSON, default=list)
    allow_marketplace_search: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_openclaw_account_management: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_seller_im: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_weight_modifier: Mapped[float] = mapped_column(Float, default=1.0)
    added_by: Mapped[str] = mapped_column(String(128), default="")
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    built_in: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
