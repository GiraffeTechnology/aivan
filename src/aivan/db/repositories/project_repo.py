from datetime import datetime, timezone
from sqlalchemy.orm import Session
from aivan.db.models.project import Project
from aivan.utils.ids import new_project_id
from aivan.utils.tenant import tenant_for_new_record

class ProjectRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, conversation_id: str, customer_id: str, channel: str = "", channel_account_id: str = "", customer_display_name: str = "", tenant_id: str = "legacy") -> Project:
        p = Project(
            project_id=new_project_id(),
            tenant_id=tenant_for_new_record(tenant_id if tenant_id != "legacy" else None),
            conversation_id=conversation_id,
            customer_id=customer_id,
            channel=channel,
            channel_account_id=channel_account_id,
            customer_display_name=customer_display_name,
        )
        self.db.add(p)
        self.db.flush()
        return p

    def get(self, project_id: str, tenant_id: str | None = None) -> Project | None:
        query = self.db.query(Project).filter(Project.project_id == project_id)
        if tenant_id is not None:
            query = query.filter(Project.tenant_id == tenant_id)
        return query.first()

    def get_by_conversation(self, conversation_id: str, tenant_id: str | None = None) -> Project | None:
        query = self.db.query(Project).filter(Project.conversation_id == conversation_id)
        if tenant_id is not None:
            query = query.filter(Project.tenant_id == tenant_id)
        return query.order_by(Project.created_at.desc()).first()

    def list_all(self, limit: int = 50, tenant_id: str | None = None) -> list[Project]:
        query = self.db.query(Project)
        if tenant_id is not None:
            query = query.filter(Project.tenant_id == tenant_id)
        return query.order_by(Project.created_at.desc()).limit(limit).all()

    def update_requirement(self, project_id: str, requirement_json: dict) -> Project | None:
        p = self.get(project_id)
        if p:
            p.requirement_json = requirement_json
            self.db.flush()
        return p

    def update_status(self, project_id: str, status: str) -> Project | None:
        p = self.get(project_id)
        if p:
            p.status = status
            self.db.flush()
        return p

    def update_selected_option(self, project_id: str, option_json: dict) -> Project | None:
        p = self.get(project_id)
        if p:
            p.selected_option_json = option_json
            self.db.flush()
        return p
