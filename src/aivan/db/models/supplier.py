from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, JSON, Float, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from aivan.db.models import Base

class SupplierRecord(Base):
    __tablename__ = "suppliers"

    supplier_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    company_type: Mapped[str] = mapped_column(String(128), default="")
    categories_json: Mapped[list] = mapped_column(JSON, default=list)
    capabilities_json: Mapped[list] = mapped_column(JSON, default=list)
    materials_json: Mapped[list] = mapped_column(JSON, default=list)
    moq_min: Mapped[int] = mapped_column(Integer, default=0)
    moq_max: Mapped[int] = mapped_column(Integer, default=0)
    daily_capacity: Mapped[int] = mapped_column(Integer, default=0)
    monthly_capacity: Mapped[int] = mapped_column(Integer, default=0)
    region: Mapped[str] = mapped_column(String(128), default="")
    country: Mapped[str] = mapped_column(String(64), default="")
    languages_json: Mapped[list] = mapped_column(JSON, default=list)
    channels_json: Mapped[list] = mapped_column(JSON, default=list)
    email: Mapped[str] = mapped_column(String(256), default="")
    openclaw_peer_id: Mapped[str] = mapped_column(String(256), default="")
    payment_terms: Mapped[str] = mapped_column(String(256), default="")
    incoterms_json: Mapped[list] = mapped_column(JSON, default=list)
    logistics_modes_json: Mapped[list] = mapped_column(JSON, default=list)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    delivery_score: Mapped[float] = mapped_column(Float, default=0.0)
    price_score: Mapped[float] = mapped_column(Float, default=0.0)
    past_performance_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_tags_json: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
