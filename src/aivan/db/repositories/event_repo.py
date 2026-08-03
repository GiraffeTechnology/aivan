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
        payload: dict = None,
        actor: str = "system",
        *,
        tenant_id: str = "legacy",
        source_trace_id: str = "",
        actor_id: str = "",
        actor_role: str = "",
        conversation_role: str = "",
        authorization_basis: str = "",
        before: dict | None = None,
        after: dict | None = None,
        rejection_reason: str = "",
    ) -> ExecutionEventRecord:
        record = ExecutionEventRecord(
            event_id=f"ev_{new_id()}",
            tenant_id=tenant_id,
            project_id=project_id,
            source_trace_id=source_trace_id,
            event_type=event_type,
            actor=actor,
            actor_id=actor_id,
            actor_role=actor_role,
            conversation_role=conversation_role,
            authorization_basis=authorization_basis,
            before_json=before or {},
            after_json=after or {},
            rejection_reason=rejection_reason,
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
