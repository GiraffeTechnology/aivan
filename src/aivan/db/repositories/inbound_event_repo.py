"""Idempotency ledger repository for inbound events.

Provides get-or-record semantics so a duplicated/retried inbound event replays
its original result instead of re-running side effects (drafts, RFQs, events).
"""
from __future__ import annotations

import hashlib

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aivan.db.models.execution import ProcessedInboundEvent
from aivan.utils.ids import new_id


def build_inbound_idempotency_key(
    *,
    source: str,
    channel: str,
    channel_account_id: str,
    conversation_id: str,
    message_id: str,
) -> str | None:
    """Build a stable idempotency key for an inbound event.

    Returns ``None`` when the event lacks the identity needed to safely
    deduplicate (no message id and no conversation id) — such events are
    processed without idempotency rather than being wrongly collapsed together.
    """
    if not (message_id or "").strip() and not (conversation_id or "").strip():
        return None
    raw = "|".join(
        [
            (source or "").strip(),
            (channel or "").strip(),
            (channel_account_id or "").strip(),
            (conversation_id or "").strip(),
            (message_id or "").strip(),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]
    return f"inb_{digest}"


class InboundEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, idempotency_key: str) -> ProcessedInboundEvent | None:
        return (
            self.db.query(ProcessedInboundEvent)
            .filter(ProcessedInboundEvent.idempotency_key == idempotency_key)
            .first()
        )

    def record(
        self,
        idempotency_key: str,
        *,
        project_id: str,
        event_type: str,
        result_json: dict,
    ) -> ProcessedInboundEvent:
        """Record the first successful processing of an event.

        If a row already exists (concurrent duplicate), return the existing one
        without creating a duplicate.
        """
        existing = self.get(idempotency_key)
        if existing is not None:
            return existing
        record = ProcessedInboundEvent(
            id=f"pie_{new_id()}",
            idempotency_key=idempotency_key,
            project_id=project_id or "",
            event_type=event_type or "",
            result_json=result_json or {},
        )
        self.db.add(record)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            return self.get(idempotency_key)
        return record
