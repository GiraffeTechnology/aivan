from datetime import datetime, timezone
from sqlalchemy.orm import Session
from aivan.db.models.project import Project
from aivan.utils.ids import new_project_id

class ProjectRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, conversation_id: str, customer_id: str, channel: str = "", channel_account_id: str = "", customer_display_name: str = "") -> Project:
        p = Project(
            project_id=new_project_id(),
            conversation_id=conversation_id,
            customer_id=customer_id,
            channel=channel,
            channel_account_id=channel_account_id,
            customer_display_name=customer_display_name,
        )
        self.db.add(p)
        self.db.flush()
        return p

    def get(self, project_id: str) -> Project | None:
        return self.db.query(Project).filter(Project.project_id == project_id).first()

    def get_by_conversation(self, conversation_id: str) -> Project | None:
        return self.db.query(Project).filter(Project.conversation_id == conversation_id).order_by(Project.created_at.desc()).first()

    def list_all(self, limit: int = 50) -> list[Project]:
        return self.db.query(Project).order_by(Project.created_at.desc()).limit(limit).all()

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
