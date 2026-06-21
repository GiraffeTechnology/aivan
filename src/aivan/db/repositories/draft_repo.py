from datetime import datetime, timezone
from sqlalchemy.orm import Session
from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.utils.ids import new_draft_id


class DraftRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, project_id: str, data: dict) -> InquiryDraftRecord:
        safe_data = {
            k: v
            for k, v in data.items()
            if k not in ("draft_id", "project_id") and hasattr(InquiryDraftRecord, k)
        }
        record = InquiryDraftRecord(draft_id=new_draft_id(), project_id=project_id, **safe_data)
        self.db.add(record)
        self.db.flush()
        return record

    def get(self, draft_id: str) -> InquiryDraftRecord | None:
        return (
            self.db.query(InquiryDraftRecord)
            .filter(InquiryDraftRecord.draft_id == draft_id)
            .first()
        )

    def list_pending(self, project_id: str) -> list[InquiryDraftRecord]:
        return (
            self.db.query(InquiryDraftRecord)
            .filter(
                InquiryDraftRecord.project_id == project_id,
                InquiryDraftRecord.status == "pending_approval",
            )
            .order_by(InquiryDraftRecord.created_at.asc())
            .all()
        )

    def list_all_pending(self) -> list[InquiryDraftRecord]:
        return (
            self.db.query(InquiryDraftRecord)
            .filter(InquiryDraftRecord.status == "pending_approval")
            .order_by(InquiryDraftRecord.created_at.asc())
            .all()
        )

    def list_awaiting_relay(self) -> list[InquiryDraftRecord]:
        return (
            self.db.query(InquiryDraftRecord)
            .filter(InquiryDraftRecord.status == "awaiting_relay")
            .order_by(InquiryDraftRecord.created_at.asc())
            .all()
        )

    def list_derived_from(self, event_id: str) -> list[InquiryDraftRecord]:
        """Return drafts that were generated from a specific inbound event."""
        return (
            self.db.query(InquiryDraftRecord)
            .filter(InquiryDraftRecord.derived_from_event_id == event_id)
            .all()
        )

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def approve(self, draft_id: str, approved_by: str = "user") -> InquiryDraftRecord | None:
        d = self.get(draft_id)
        if d is None:
            return None
        if d.status == "pending_approval":
            d.status = "approved"
            d.approved_by = approved_by
            d.approved_at = datetime.now(timezone.utc)
            self.db.flush()
        return d

    def reject(self, draft_id: str) -> InquiryDraftRecord | None:
        d = self.get(draft_id)
        if d is None:
            return None
        if d.status == "pending_approval":
            d.status = "rejected"
            self.db.flush()
        return d

    def mark_sent(
        self, draft_id: str, receipt: dict | None = None
    ) -> InquiryDraftRecord | None:
        d = self.get(draft_id)
        if d:
            d.status = "sent"
            d.sent_at = datetime.now(timezone.utc)
            if receipt:
                d.sent_receipt_json = receipt
            self.db.flush()
        return d

    def mark_awaiting_relay(self, draft_id: str) -> InquiryDraftRecord | None:
        d = self.get(draft_id)
        if d:
            d.status = "awaiting_relay"
            self.db.flush()
        return d

    def mark_relayed(
        self, draft_id: str, confirmed_by: str = "user"
    ) -> InquiryDraftRecord | None:
        d = self.get(draft_id)
        if d and d.status == "awaiting_relay":
            d.status = "relayed"
            d.relay_confirmed_by = confirmed_by
            d.relay_confirmed_at = datetime.now(timezone.utc)
            d.sent_at = datetime.now(timezone.utc)
            self.db.flush()
        return d

    def mark_send_failed(
        self, draft_id: str, error: str = ""
    ) -> InquiryDraftRecord | None:
        d = self.get(draft_id)
        if d:
            d.status = "send_failed"
            d.send_error = error
            self.db.flush()
        return d

    def invalidate_derived(self, event_id: str) -> list[str]:
        """Mark drafts derived from *event_id* as invalidated. Returns affected draft_ids."""
        affected = self.list_derived_from(event_id)
        ids = []
        for d in affected:
            if d.status not in ("sent", "relayed"):
                d.status = "invalidated"
                self.db.flush()
            ids.append(d.draft_id)
        return ids
