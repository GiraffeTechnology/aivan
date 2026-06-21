from sqlalchemy.orm import Session
from aivan.db.models.inbound_event import InboundRelayEvent
from aivan.utils.ids import new_id


class InboundRelayRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        thread_id: str,
        counterparty_id: str,
        pasted_text: str,
        channel: str = "",
        linked_execution_event_id: str | None = None,
    ) -> InboundRelayEvent:
        record = InboundRelayEvent(
            inbound_id=f"inb_{new_id()}",
            thread_id=thread_id,
            counterparty_id=counterparty_id,
            channel=channel,
            pasted_text=pasted_text,
            linked_execution_event_id=linked_execution_event_id,
        )
        self.db.add(record)
        self.db.flush()
        return record

    def get(self, inbound_id: str) -> InboundRelayEvent | None:
        return (
            self.db.query(InboundRelayEvent)
            .filter(InboundRelayEvent.inbound_id == inbound_id)
            .first()
        )

    def list_for_thread(self, thread_id: str) -> list[InboundRelayEvent]:
        return (
            self.db.query(InboundRelayEvent)
            .filter(InboundRelayEvent.thread_id == thread_id)
            .order_by(InboundRelayEvent.created_at.asc())
            .all()
        )

    def supersede(self, inbound_id: str) -> InboundRelayEvent | None:
        rec = self.get(inbound_id)
        if rec:
            rec.superseded = True
            self.db.flush()
        return rec
