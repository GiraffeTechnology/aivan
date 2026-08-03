from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from aivan.db.models import Base
import hashlib
import uuid

def account_storage_key(tenant_id: str, account_connection_id: str) -> str:
    raw = f"{tenant_id}\x1f{account_connection_id}".encode("utf-8")
    return f"acc_{hashlib.sha256(raw).hexdigest()[:48]}"

def _default_account_storage_key() -> str:
    return f"acc_{uuid.uuid4().hex}"

class OpenClawAccountRecord(Base):
    __tablename__ = "openclaw_accounts"

    storage_key: Mapped[str] = mapped_column("account_connection_id", String(128), primary_key=True, default=_default_account_storage_key)
    account_connection_id: Mapped[str] = mapped_column("logical_account_connection_id", String(128), default="", index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), default="legacy", index=True)
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

