from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from aivan.db.models import Base


class SchemaMigrationRecord(Base):
    __tablename__ = "aivan_schema_migrations"

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidate_sha: Mapped[str] = mapped_column(String(40), index=True)
    authorization_digest: Mapped[str] = mapped_column(String(64))
    backup_digest: Mapped[str] = mapped_column(String(64))
    evidence_digest: Mapped[str] = mapped_column(String(64))
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
