from datetime import datetime, timezone
from sqlalchemy.orm import Session
from aiven.db.models.inquiry import InquiryDraftRecord
from aiven.utils.ids import new_draft_id

class DraftRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, project_id: str, data: dict) -> InquiryDraftRecord:
        safe_data = {k: v for k, v in data.items() if k not in ("draft_id", "project_id") and hasattr(InquiryDraftRecord, k)}
        record = InquiryDraftRecord(draft_id=new_draft_id(), project_id=project_id, **safe_data)
        self.db.add(record)
        self.db.flush()
        return record

    def get(self, draft_id: str) -> InquiryDraftRecord | None:
        return self.db.query(InquiryDraftRecord).filter(InquiryDraftRecord.draft_id == draft_id).first()

    def list_pending(self, project_id: str) -> list[InquiryDraftRecord]:
        return self.db.query(InquiryDraftRecord).filter(
            InquiryDraftRecord.project_id == project_id,
            InquiryDraftRecord.status == "pending"
        ).order_by(InquiryDraftRecord.created_at.asc()).all()

    def list_all_pending(self) -> list[InquiryDraftRecord]:
        return self.db.query(InquiryDraftRecord).filter(InquiryDraftRecord.status == "pending").order_by(InquiryDraftRecord.created_at.asc()).all()

    def approve(self, draft_id: str, approved_by: str = "user") -> InquiryDraftRecord | None:
        d = self.get(draft_id)
        if d and d.status == "pending":
            d.status = "approved"
            d.approved_by = approved_by
            d.approved_at = datetime.now(timezone.utc)
            self.db.flush()
        return d

    def reject(self, draft_id: str) -> InquiryDraftRecord | None:
        d = self.get(draft_id)
        if d and d.status == "pending":
            d.status = "rejected"
            self.db.flush()
        return d

    def mark_sent(self, draft_id: str) -> InquiryDraftRecord | None:
        d = self.get(draft_id)
        if d:
            d.status = "sent"
            d.sent_at = datetime.now(timezone.utc)
            self.db.flush()
        return d
