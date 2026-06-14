from sqlalchemy.orm import Session
from aiven.db.models.execution import ExecutionEventRecord
from aiven.utils.ids import new_id

class ExecutionEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def append(self, project_id: str, event_type: str, summary: str, payload: dict = None, actor: str = "system") -> ExecutionEventRecord:
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

    def list_for_project(self, project_id: str, limit: int = 100) -> list[ExecutionEventRecord]:
        return self.db.query(ExecutionEventRecord).filter(
            ExecutionEventRecord.project_id == project_id
        ).order_by(ExecutionEventRecord.created_at.asc()).limit(limit).all()
