"""Idempotency ledger repository for inbound events.

Claims the existing unique ledger identity before workflow side effects. A
completed receipt can be replayed; an unfinished claim cannot be re-executed.
"""
from __future__ import annotations

import hashlib

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aivan.db.models.execution import ProcessedInboundEvent
from aivan.utils.ids import new_id


def build_inbound_idempotency_key(
    *,
    tenant_id: str = "legacy",
    source: str,
    channel: str,
    channel_account_id: str,
    conversation_id: str,
    message_id: str,
    explicit_idempotency_key: str = "",
) -> str | None:
    """Build a stable idempotency key for an inbound event.

    Returns ``None`` when the event lacks the identity needed to safely
    deduplicate (no message id and no conversation id) — such events are
    processed without idempotency rather than being wrongly collapsed together.
    """
    if explicit_idempotency_key.strip():
        raw = f"{tenant_id.strip()}|explicit|{explicit_idempotency_key.strip()}"
        return f"inb_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:48]}"
    if not (message_id or "").strip() and not (conversation_id or "").strip():
        return None
    raw = "|".join(
        [
            (tenant_id or "legacy").strip(),
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
    PROCESSING = "inbound_processing"

    def __init__(self, db: Session):
        self.db = db

    def get(self, idempotency_key: str) -> ProcessedInboundEvent | None:
        return (
            self.db.query(ProcessedInboundEvent)
            .filter(ProcessedInboundEvent.idempotency_key == idempotency_key)
            .first()
        )

    def claim(self, idempotency_key: str, *, tenant_id: str) -> tuple[ProcessedInboundEvent, bool]:
        """Insert and commit a unique claim, even after a stale absent SELECT.

        The database constraint, not a process-local lock or caller's prior
        read, selects the owner. No lease expires into automatic re-execution:
        a crash after any intermediate workflow commit must remain uncertain.
        """
        claim = ProcessedInboundEvent(
            id=f"pie_{new_id()}", tenant_id=tenant_id,
            idempotency_key=idempotency_key, project_id="",
            event_type=self.PROCESSING, result_json={},
        )
        self.db.add(claim)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.get(idempotency_key)
            if existing is None:
                raise  # A different integrity failure is not a replay.
            return existing, False
        return claim, True

    def complete(self, claim: ProcessedInboundEvent, *, project_id: str,
                 event_type: str, result_json: dict) -> None:
        """Only the original claim identity may publish the completed result."""
        changed = self.db.query(ProcessedInboundEvent).filter(
            ProcessedInboundEvent.id == claim.id,
            ProcessedInboundEvent.idempotency_key == claim.idempotency_key,
            ProcessedInboundEvent.event_type == self.PROCESSING,
        ).update({
            "project_id": project_id, "event_type": event_type,
            "result_json": result_json,
        }, synchronize_session=False)
        if changed != 1:
            self.db.rollback()
            raise RuntimeError("Inbound receipt ownership could not be confirmed")
        self.db.commit()

    def record(
        self,
        idempotency_key: str,
        *,
        tenant_id: str = "legacy",
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
            tenant_id=tenant_id or "legacy",
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
