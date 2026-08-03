from sqlalchemy import or_
from sqlalchemy.orm import Session
from aivan.db.models.supplier import SupplierRecord, supplier_storage_key

class SupplierRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, supplier_id: str, data: dict, *, tenant_id: str = "legacy") -> SupplierRecord:
        existing = self.db.query(SupplierRecord).filter(
            SupplierRecord.tenant_id == tenant_id,
            or_(SupplierRecord.supplier_id == supplier_id, SupplierRecord.storage_key == supplier_id),
        ).first()
        if existing:
            for k, v in data.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
            self.db.flush()
            return existing
        record = SupplierRecord(storage_key=supplier_storage_key(tenant_id, supplier_id), supplier_id=supplier_id, tenant_id=tenant_id, **{k: v for k, v in data.items() if hasattr(SupplierRecord, k) and k not in {"supplier_id", "storage_key", "tenant_id"}})
        self.db.add(record)
        self.db.flush()
        return record

    def get(self, supplier_id: str, *, tenant_id: str = "legacy") -> SupplierRecord | None:
        return self.db.query(SupplierRecord).filter(
            SupplierRecord.tenant_id == tenant_id,
            or_(SupplierRecord.supplier_id == supplier_id, SupplierRecord.storage_key == supplier_id),
        ).first()

    def list_active(self, *, tenant_id: str = "legacy") -> list[SupplierRecord]:
        return self.db.query(SupplierRecord).filter(SupplierRecord.tenant_id == tenant_id, SupplierRecord.active == True).all()

    def search_by_category(self, category: str, *, tenant_id: str = "legacy") -> list[SupplierRecord]:
        return [s for s in self.list_active(tenant_id=tenant_id) if any(category.lower() in c.lower() for c in (s.categories_json or []))]

    def count(self, *, tenant_id: str = "legacy") -> int:
        return self.db.query(SupplierRecord).filter(SupplierRecord.tenant_id == tenant_id).count()

    def list_active_all_tenants(self) -> list[SupplierRecord]:
        return self.db.query(SupplierRecord).filter(SupplierRecord.active == True).all()

