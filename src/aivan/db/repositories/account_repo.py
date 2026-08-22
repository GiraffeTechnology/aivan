from sqlalchemy import or_
from sqlalchemy.orm import Session
from aivan.db.models.account import OpenClawAccountRecord, account_storage_key

class AccountRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, account_connection_id: str, data: dict, *, tenant_id: str = "legacy") -> OpenClawAccountRecord:
        existing = self.db.query(OpenClawAccountRecord).filter(
            OpenClawAccountRecord.tenant_id == tenant_id,
            or_(
                OpenClawAccountRecord.account_connection_id == account_connection_id,
                OpenClawAccountRecord.storage_key == account_connection_id,
            ),
        ).first()
        if existing:
            for k, v in data.items():
                if hasattr(existing, k) and k != "account_connection_id":
                    setattr(existing, k, v)
            self.db.flush()
            return existing
        record = OpenClawAccountRecord(storage_key=account_storage_key(tenant_id, account_connection_id), account_connection_id=account_connection_id, tenant_id=tenant_id, **{k: v for k, v in data.items() if hasattr(OpenClawAccountRecord, k) and k not in {"account_connection_id", "storage_key", "tenant_id"}})
        self.db.add(record)
        self.db.flush()
        return record

    def get(self, account_connection_id: str, *, tenant_id: str = "legacy") -> OpenClawAccountRecord | None:
        return self.db.query(OpenClawAccountRecord).filter(
            OpenClawAccountRecord.tenant_id == tenant_id,
            or_(
                OpenClawAccountRecord.account_connection_id == account_connection_id,
                OpenClawAccountRecord.storage_key == account_connection_id,
            ),
        ).first()

    def list_active(self, *, tenant_id: str = "legacy") -> list[OpenClawAccountRecord]:
        return self.db.query(OpenClawAccountRecord).filter(
            OpenClawAccountRecord.tenant_id == tenant_id,
            OpenClawAccountRecord.status.in_(["connected", "expired"])
        ).all()

    def revoke(self, account_connection_id: str, *, tenant_id: str = "legacy") -> OpenClawAccountRecord | None:
        a = self.get(account_connection_id, tenant_id=tenant_id)
        if a:
            a.status = "revoked"
            self.db.flush()
        return a

