import hashlib
import json

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
        tenant_id: str | None = None,
        source_trace_id: str = "",
        actor_id: str = "",
        actor_role: str = "",
        conversation_role: str = "",
        authorization_basis: str = "",
        before: dict | None = None,
        after: dict | None = None,
        rejection_reason: str = "",
        derived_from_event_id: str = "",
        correction_status: str = "",
    ) -> ExecutionEventRecord:
        if tenant_id is None:
            from aivan.db.models.project import Project
            project = self.db.query(Project).filter(Project.project_id == project_id).first()
            tenant_id = project.tenant_id if project is not None else "legacy"
        payload = payload or {}
        before = before or {}
        after = after or {}
        digest_source = json.dumps(
            {
                "event_type": event_type,
                "summary": summary,
                "payload": payload,
                "before": before,
                "after": after,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
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
            before_json=before,
            after_json=after,
            rejection_reason=rejection_reason,
            derived_from_event_id=derived_from_event_id,
            payload_digest=hashlib.sha256(digest_source.encode("utf-8")).hexdigest(),
            correction_status=correction_status,
            summary=summary,
            payload_json=payload,
        )
        self.db.add(record)
        self.db.flush()
        return record

    def get(
        self, event_id: str, *, tenant_id: str
    ) -> ExecutionEventRecord | None:
        return (
            self.db.query(ExecutionEventRecord)
            .filter(
                ExecutionEventRecord.event_id == event_id,
                ExecutionEventRecord.tenant_id == tenant_id,
            )
            .first()
        )

    def list_after(
        self, event: ExecutionEventRecord, *, tenant_id: str
    ) -> list[ExecutionEventRecord]:
        return (
            self.db.query(ExecutionEventRecord)
            .filter(
                ExecutionEventRecord.tenant_id == tenant_id,
                ExecutionEventRecord.project_id == event.project_id,
                ExecutionEventRecord.created_at > event.created_at,
            )
            .order_by(ExecutionEventRecord.created_at.asc())
            .all()
        )

    def list_derived(
        self, event_id: str, *, tenant_id: str
    ) -> list[ExecutionEventRecord]:
        return (
            self.db.query(ExecutionEventRecord)
            .filter(
                ExecutionEventRecord.tenant_id == tenant_id,
                ExecutionEventRecord.derived_from_event_id == event_id,
            )
            .order_by(ExecutionEventRecord.created_at.asc())
            .all()
        )

    def list_for_project(self, project_id: str, limit: int = 100, *, tenant_id: str | None = None) -> list[ExecutionEventRecord]:
        query = self.db.query(ExecutionEventRecord).filter(ExecutionEventRecord.project_id == project_id)
        if tenant_id is not None:
            query = query.filter(ExecutionEventRecord.tenant_id == tenant_id)
        return query.order_by(ExecutionEventRecord.created_at.asc()).limit(limit).all()

