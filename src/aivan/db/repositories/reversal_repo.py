from __future__ import annotations

import hashlib

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aivan.db.models.execution import EventReversalRecord
from aivan.utils.ids import new_id


def reversal_idempotency_key(tenant_id: str, supplied_key: str) -> str:
    raw = f"{tenant_id.strip()}|event-reversal|{supplied_key.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class EventReversalRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_for_source(
        self, source_event_id: str, *, tenant_id: str
    ) -> EventReversalRecord | None:
        return (
            self.db.query(EventReversalRecord)
            .filter(
                EventReversalRecord.tenant_id == tenant_id,
                EventReversalRecord.source_event_id == source_event_id,
            )
            .first()
        )

    def get_for_idempotency_key(
        self, idempotency_key: str, *, tenant_id: str
    ) -> EventReversalRecord | None:
        return (
            self.db.query(EventReversalRecord)
            .filter(
                EventReversalRecord.tenant_id == tenant_id,
                EventReversalRecord.idempotency_key == idempotency_key,
            )
            .first()
        )

    def create_or_get(self, **data) -> tuple[EventReversalRecord, bool]:
        record = EventReversalRecord(
            reversal_id=f"reversal_{new_id()}", **data
        )
        self.db.add(record)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            existing = self.get_for_source(
                data["source_event_id"], tenant_id=data["tenant_id"]
            ) or self.get_for_idempotency_key(
                data["idempotency_key"], tenant_id=data["tenant_id"]
            )
            if existing is None:
                raise
            return existing, False
        return record, True
