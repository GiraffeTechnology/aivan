from sqlalchemy.orm import Session
from aivan.db.models.execution import ExecutionEventRecord
from aivan.utils.ids import new_id


class ExecutionEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def append(
        self,
        project_id: str,
        event_type: str,
        summary: str,
        payload: dict | None = None,
        actor: str = "system",
    ) -> ExecutionEventRecord:
        record = ExecutionEventRecord(
            event_id=f"ev_{new_id()}",
            project_id=project_id,
            event_type=event_type,
            actor=actor,
            summary=summary,
            payload_json=payload or {},
        )
        self.db.add(record)
        self.db.flush()
        return record

    def get(self, event_id: str) -> ExecutionEventRecord | None:
        return (
            self.db.query(ExecutionEventRecord)
            .filter(ExecutionEventRecord.event_id == event_id)
            .first()
        )

    def list_for_project(
        self, project_id: str, limit: int = 100
    ) -> list[ExecutionEventRecord]:
        return (
            self.db.query(ExecutionEventRecord)
            .filter(ExecutionEventRecord.project_id == project_id)
            .order_by(ExecutionEventRecord.created_at.asc())
            .limit(limit)
            .all()
        )

    def append_reversal(
        self,
        project_id: str,
        original_event_id: str,
        reason: str,
        actor: str = "user",
    ) -> ExecutionEventRecord:
        """Append a reversal event and mark the original as superseded."""
        original = self.get(original_event_id)
        if original:
            original.superseded = True
            self.db.flush()

        reversal = ExecutionEventRecord(
            event_id=f"ev_{new_id()}",
            project_id=project_id,
            event_type="reversal",
            actor=actor,
            summary=f"Reversal of {original_event_id}: {reason}",
            payload_json={"references": original_event_id, "reason": reason},
            references_event_id=original_event_id,
        )
        self.db.add(reversal)
        self.db.flush()
        return reversal

    def list_derived_events(self, event_id: str) -> list[ExecutionEventRecord]:
        """Events that reference *event_id* (e.g. downstream processing events)."""
        return (
            self.db.query(ExecutionEventRecord)
            .filter(ExecutionEventRecord.references_event_id == event_id)
            .all()
        )
