from __future__ import annotations

import hashlib

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aivan.db.models.relay import RelayReceiptRecord
from aivan.utils.ids import new_id


def relay_idempotency_key(tenant_id: str, supplied_key: str) -> str:
    raw = f"{tenant_id.strip()}|relay-confirm|{supplied_key.strip()}"
    return f"relay_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:48]}"


class RelayReceiptRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_for_draft(
        self, draft_id: str, *, tenant_id: str
    ) -> RelayReceiptRecord | None:
        return (
            self.db.query(RelayReceiptRecord)
            .filter(
                RelayReceiptRecord.tenant_id == tenant_id,
                RelayReceiptRecord.draft_id == draft_id,
            )
            .first()
        )

    def get_for_idempotency_key(
        self, idempotency_key: str, *, tenant_id: str
    ) -> RelayReceiptRecord | None:
        return (
            self.db.query(RelayReceiptRecord)
            .filter(
                RelayReceiptRecord.tenant_id == tenant_id,
                RelayReceiptRecord.idempotency_key == idempotency_key,
            )
            .first()
        )

    def create_or_get(self, **data) -> tuple[RelayReceiptRecord, bool]:
        """Create one receipt, replaying the winner of a concurrent insert."""

        record = RelayReceiptRecord(receipt_id=f"receipt_{new_id()}", **data)
        self.db.add(record)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            existing = self.get_for_draft(
                data["draft_id"], tenant_id=data["tenant_id"]
            ) or self.get_for_idempotency_key(
                data["idempotency_key"], tenant_id=data["tenant_id"]
            )
            if existing is None:
                raise
            return existing, False
        return record, True
