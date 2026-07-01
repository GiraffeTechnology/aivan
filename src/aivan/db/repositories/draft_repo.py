from datetime import datetime, timezone
from sqlalchemy.orm import Session
from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.utils.ids import new_draft_id

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
            InquiryDraftRecord.status == "pending_approval",
        ).order_by(InquiryDraftRecord.created_at.asc()).all()

    def list_for_project(self, project_id: str) -> list[InquiryDraftRecord]:
        return self.db.query(InquiryDraftRecord).filter(
            InquiryDraftRecord.project_id == project_id,
        ).order_by(InquiryDraftRecord.created_at.asc()).all()

    def list_all_pending(self) -> list[InquiryDraftRecord]:
        return self.db.query(InquiryDraftRecord).filter(
            InquiryDraftRecord.status == "pending_approval"
        ).order_by(InquiryDraftRecord.created_at.asc()).all()

    def approve(self, draft_id: str, approved_by: str = "user") -> InquiryDraftRecord | None:
        """Transition draft to 'approved'. Returns None if not found.
        If the draft exists but is not in 'pending_approval' state, returns it
        unchanged (caller checks .status to detect the conflict).
        """
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
        """Transition draft to 'rejected'. Returns None if not found.
        If the draft exists but is not in 'pending_approval' state, returns it
        unchanged (caller checks .status to detect the conflict).
        """
        d = self.get(draft_id)
        if d is None:
            return None
        if d.status == "pending_approval":
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

    def mark_approved_pending_send(self, draft_id: str, approved_by: str = "user") -> InquiryDraftRecord | None:
        """Transition a pending_approval draft to approved_pending_send.

        Used by the send-aware approval state machine so an approved-but-not-yet-
        sent draft is distinguishable from a fully sent one. No-op if not pending.
        """
        d = self.get(draft_id)
        if d is None:
            return None
        if d.status == "pending_approval":
            d.status = "approved_pending_send"
            d.approved_by = approved_by
            d.approved_at = datetime.now(timezone.utc)
            self.db.flush()
        return d

    def mark_send_failed(self, draft_id: str, reason: str = "") -> InquiryDraftRecord | None:
        """Record a recoverable send failure; never leave a failed send 'approved'."""
        d = self.get(draft_id)
        if d is None:
            return None
        d.status = "send_failed"
        if reason:
            existing = (d.notes or "").strip()
            note = f"send_failed_reason={reason}"
            d.notes = f"{existing} {note}".strip() if existing else note
        self.db.flush()
        return d

    def supersede_customer_quote_drafts(self, project_id: str) -> list[str]:
        """Mark all pending_approval customer_quote_email drafts for the project as superseded.

        Called before creating a new customer quote draft so that stale drafts cannot
        be approved or sent after a newer supplier reply regenerates buyer options.
        Returns the list of draft_ids that were superseded.
        """
        stale = self.db.query(InquiryDraftRecord).filter(
            InquiryDraftRecord.project_id == project_id,
            InquiryDraftRecord.status == "pending_approval",
            InquiryDraftRecord.notes.contains("draft_type=customer_quote_email"),
        ).all()
        superseded_ids = []
        for d in stale:
            d.status = "superseded"
            superseded_ids.append(d.draft_id)
        if superseded_ids:
            self.db.flush()
        return superseded_ids
