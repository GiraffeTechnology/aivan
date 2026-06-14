from sqlalchemy.orm import Session
from aiven.db.models.platform import PlatformRecord

class PlatformRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, platform_id: str, data: dict) -> PlatformRecord:
        existing = self.db.query(PlatformRecord).filter(PlatformRecord.platform_id == platform_id).first()
        if existing:
            if existing.built_in:
                return existing
            for k, v in data.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
            self.db.flush()
            return existing
        record = PlatformRecord(platform_id=platform_id, **{k: v for k, v in data.items() if hasattr(PlatformRecord, k) and k != "platform_id"})
        self.db.add(record)
        self.db.flush()
        return record

    def get(self, platform_id: str) -> PlatformRecord | None:
        return self.db.query(PlatformRecord).filter(PlatformRecord.platform_id == platform_id).first()

    def list_all(self) -> list[PlatformRecord]:
        return self.db.query(PlatformRecord).order_by(PlatformRecord.created_at.asc()).all()

    def list_trusted(self) -> list[PlatformRecord]:
        return self.db.query(PlatformRecord).filter(
            PlatformRecord.status.in_(["built_in", "trusted"])
        ).all()

    def list_suggestions(self) -> list[PlatformRecord]:
        return self.db.query(PlatformRecord).filter(PlatformRecord.status == "pending_review").all()

    def update_status(self, platform_id: str, status: str) -> PlatformRecord | None:
        p = self.get(platform_id)
        if p and not p.built_in:
            p.status = status
            self.db.flush()
        return p
