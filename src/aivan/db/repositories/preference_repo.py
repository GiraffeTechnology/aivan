from __future__ import annotations

from sqlalchemy.orm import Session

from aivan.db.models.preference import UserPreferenceRecord
from aivan.utils.ids import new_id


class UserPreferenceRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(
        self,
        user_id: str,
        preference_type: str,
        value: dict,
        source: str = "",
        confidence: float = 0.5,
    ) -> UserPreferenceRecord:
        record = (
            self.db.query(UserPreferenceRecord)
            .filter(
                UserPreferenceRecord.user_id == user_id,
                UserPreferenceRecord.preference_type == preference_type,
            )
            .order_by(UserPreferenceRecord.updated_at.desc())
            .first()
        )
        if record is None:
            record = UserPreferenceRecord(
                preference_id=f"pref_{new_id()}",
                user_id=user_id,
                preference_type=preference_type,
            )
            self.db.add(record)
        record.value_json = value
        record.source = source
        record.confidence = confidence
        self.db.flush()
        return record

    def list_for_user(self, user_id: str) -> list[UserPreferenceRecord]:
        return (
            self.db.query(UserPreferenceRecord)
            .filter(UserPreferenceRecord.user_id == user_id)
            .order_by(UserPreferenceRecord.updated_at.desc())
            .all()
        )

    def list_all(self) -> list[UserPreferenceRecord]:
        return self.db.query(UserPreferenceRecord).order_by(UserPreferenceRecord.updated_at.desc()).all()
