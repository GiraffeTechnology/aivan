from sqlalchemy import or_
from sqlalchemy.orm import Session
from aivan.db.models.platform import PlatformRecord, platform_storage_key

class PlatformRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, platform_id: str, data: dict, *, tenant_id: str = "legacy") -> PlatformRecord:
        existing = self.db.query(PlatformRecord).filter(
            PlatformRecord.tenant_id == tenant_id,
            or_(PlatformRecord.platform_id == platform_id, PlatformRecord.storage_key == platform_id),
        ).first()
        if existing:
            if existing.built_in:
                return existing
            for k, v in data.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
            self.db.flush()
            return existing
        record = PlatformRecord(storage_key=platform_storage_key(tenant_id, platform_id), platform_id=platform_id, tenant_id=tenant_id, **{k: v for k, v in data.items() if hasattr(PlatformRecord, k) and k not in {"platform_id", "storage_key", "tenant_id"}})
        self.db.add(record)
        self.db.flush()
        return record

    def get(self, platform_id: str, *, tenant_id: str = "legacy") -> PlatformRecord | None:
        return self.db.query(PlatformRecord).filter(
            PlatformRecord.tenant_id == tenant_id,
            or_(PlatformRecord.platform_id == platform_id, PlatformRecord.storage_key == platform_id),
        ).first()

    def list_all(self, *, tenant_id: str = "legacy") -> list[PlatformRecord]:
        return self.db.query(PlatformRecord).filter(PlatformRecord.tenant_id == tenant_id).order_by(PlatformRecord.created_at.asc()).all()

    def list_trusted(self, *, tenant_id: str = "legacy") -> list[PlatformRecord]:
        return self.db.query(PlatformRecord).filter(
            PlatformRecord.tenant_id == tenant_id,
            PlatformRecord.status.in_(["built_in", "trusted"])
        ).all()

    def list_suggestions(self, *, tenant_id: str = "legacy") -> list[PlatformRecord]:
        return self.db.query(PlatformRecord).filter(PlatformRecord.tenant_id == tenant_id, PlatformRecord.status == "pending_review").all()

    def update_status(self, platform_id: str, status: str, *, tenant_id: str = "legacy") -> PlatformRecord | None:
        p = self.get(platform_id, tenant_id=tenant_id)
        if p and not p.built_in:
            p.status = status
            self.db.flush()
        return p

