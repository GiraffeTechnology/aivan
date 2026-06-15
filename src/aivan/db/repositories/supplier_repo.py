from sqlalchemy.orm import Session
from aivan.db.models.supplier import SupplierRecord

class SupplierRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, supplier_id: str, data: dict) -> SupplierRecord:
        existing = self.db.query(SupplierRecord).filter(SupplierRecord.supplier_id == supplier_id).first()
        if existing:
            for k, v in data.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
            self.db.flush()
            return existing
        record = SupplierRecord(supplier_id=supplier_id, **{k: v for k, v in data.items() if hasattr(SupplierRecord, k) and k != "supplier_id"})
        self.db.add(record)
        self.db.flush()
        return record

    def get(self, supplier_id: str) -> SupplierRecord | None:
        return self.db.query(SupplierRecord).filter(SupplierRecord.supplier_id == supplier_id).first()

    def list_active(self) -> list[SupplierRecord]:
        return self.db.query(SupplierRecord).filter(SupplierRecord.active == True).all()

    def search_by_category(self, category: str) -> list[SupplierRecord]:
        return [s for s in self.list_active() if any(category.lower() in c.lower() for c in (s.categories_json or []))]

    def count(self) -> int:
        return self.db.query(SupplierRecord).count()
