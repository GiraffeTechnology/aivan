from sqlalchemy.orm import Session
from aiven.db.models.account import OpenClawAccountRecord

class AccountRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, account_connection_id: str, data: dict) -> OpenClawAccountRecord:
        existing = self.db.query(OpenClawAccountRecord).filter(
            OpenClawAccountRecord.account_connection_id == account_connection_id
        ).first()
        if existing:
            for k, v in data.items():
                if hasattr(existing, k) and k != "account_connection_id":
                    setattr(existing, k, v)
            self.db.flush()
            return existing
        record = OpenClawAccountRecord(account_connection_id=account_connection_id, **{k: v for k, v in data.items() if hasattr(OpenClawAccountRecord, k) and k != "account_connection_id"})
        self.db.add(record)
        self.db.flush()
        return record

    def get(self, account_connection_id: str) -> OpenClawAccountRecord | None:
        return self.db.query(OpenClawAccountRecord).filter(
            OpenClawAccountRecord.account_connection_id == account_connection_id
        ).first()

    def list_active(self) -> list[OpenClawAccountRecord]:
        return self.db.query(OpenClawAccountRecord).filter(
            OpenClawAccountRecord.status.in_(["connected", "expired"])
        ).all()

    def revoke(self, account_connection_id: str) -> OpenClawAccountRecord | None:
        a = self.get(account_connection_id)
        if a:
            a.status = "revoked"
            self.db.flush()
        return a
