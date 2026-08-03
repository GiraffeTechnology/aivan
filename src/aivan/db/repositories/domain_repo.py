from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from aivan.db.models.domain import (
    ApprovalRecord,
    AuditLogRecord,
    CaseConversationRecord,
    CaseMessageRecord,
    CaseParticipantRecord,
)
from aivan.domain.roles import (
    ActorIdentity,
    CaseState,
    TransitionDecision,
    authorize_transition,
    normalize_actor_identity,
)
from aivan.openclaw.contracts import OpenClawEvent
from aivan.utils.ids import new_id


class CaseDomainRepository:
    """Persists canonical Case membership, message, approval, and audit evidence."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def identity_for_event(event: OpenClawEvent) -> ActorIdentity:
        return normalize_actor_identity(
            actor_id=event.actor_id or event.sender_id or "system",
            business_role=event.business_role or event.role_context,
            conversation_role=event.conversation_role or None,
            execution_mode=event.execution_mode or event.mode,
            authorization_basis=event.authorization_basis or "event_boundary",
        )

    @staticmethod
    def _message_source_id(event: OpenClawEvent) -> str:
        if event.message_id:
            return event.message_id
        if event.source_trace_id:
            return f"trace:{event.source_trace_id}"
        raw = "\x1f".join(
            [
                event.source,
                event.channel,
                event.channel_account_id,
                event.conversation_id,
                event.sender_id,
                event.timestamp,
                event.message_text,
            ]
        )
        return f"digest:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    def bind_inbound_event(
        self, case_id: str, event: OpenClawEvent
    ) -> tuple[CaseConversationRecord, CaseParticipantRecord, CaseMessageRecord, bool]:
        """Bind an inbound event to one Case thread and store its message once."""

        identity = self.identity_for_event(event)
        tenant_id = event.tenant_id or "legacy"
        conversation = (
            self.db.query(CaseConversationRecord)
            .filter(
                CaseConversationRecord.tenant_id == tenant_id,
                CaseConversationRecord.case_id == case_id,
                CaseConversationRecord.external_conversation_id == event.conversation_id,
                CaseConversationRecord.conversation_role == identity.conversation_role.value,
                CaseConversationRecord.channel == event.channel,
                CaseConversationRecord.channel_account_id == event.channel_account_id,
            )
            .first()
        )
        if conversation is None:
            conversation = CaseConversationRecord(
                conversation_record_id=f"conv_{new_id()}",
                tenant_id=tenant_id,
                case_id=case_id,
                external_conversation_id=event.conversation_id,
                conversation_role=identity.conversation_role.value,
                channel=event.channel,
                channel_account_id=event.channel_account_id,
                thread_key="|".join(
                    [
                        tenant_id,
                        case_id,
                        identity.conversation_role.value,
                        event.channel,
                        event.channel_account_id,
                        event.conversation_id,
                    ]
                ),
            )
            self.db.add(conversation)
            self.db.flush()

        participant = (
            self.db.query(CaseParticipantRecord)
            .filter(
                CaseParticipantRecord.tenant_id == tenant_id,
                CaseParticipantRecord.case_id == case_id,
                CaseParticipantRecord.actor_id == identity.actor_id,
                CaseParticipantRecord.business_role == identity.business_role.value,
                CaseParticipantRecord.conversation_record_id
                == conversation.conversation_record_id,
            )
            .first()
        )
        if participant is None:
            participant = CaseParticipantRecord(
                participant_id=f"part_{new_id()}",
                tenant_id=tenant_id,
                case_id=case_id,
                conversation_record_id=conversation.conversation_record_id,
                actor_id=identity.actor_id,
                business_role=identity.business_role.value,
                conversation_role=identity.conversation_role.value,
                display_name=event.sender_display_name,
            )
            self.db.add(participant)
            self.db.flush()

        source_message_id = self._message_source_id(event)
        message = (
            self.db.query(CaseMessageRecord)
            .filter(
                CaseMessageRecord.tenant_id == tenant_id,
                CaseMessageRecord.case_id == case_id,
                CaseMessageRecord.conversation_record_id
                == conversation.conversation_record_id,
                CaseMessageRecord.source_message_id == source_message_id,
            )
            .first()
        )
        created = message is None
        if message is None:
            message = CaseMessageRecord(
                message_record_id=f"msg_{new_id()}",
                tenant_id=tenant_id,
                case_id=case_id,
                conversation_record_id=conversation.conversation_record_id,
                participant_id=participant.participant_id,
                source_message_id=source_message_id,
                source_trace_id=event.source_trace_id,
                actor_id=identity.actor_id,
                actor_role=identity.business_role.value,
                asserted_by_actor_id=event.authenticated_actor_id or "",
                asserted_by_actor_role=event.authenticated_actor_role or "",
                conversation_role=identity.conversation_role.value,
                message_type=event.message_type,
                payload_digest=hashlib.sha256(
                    event.message_text.encode("utf-8")
                ).hexdigest(),
            )
            self.db.add(message)
            self.db.flush()
        return conversation, participant, message, created

    def resolve_case_id_for_conversation(
        self,
        *,
        tenant_id: str,
        external_conversation_id: str,
        channel: str = "",
        channel_account_id: str = "",
    ) -> str | None:
        query = self.db.query(CaseConversationRecord).filter(
            CaseConversationRecord.tenant_id == (tenant_id or "legacy"),
            CaseConversationRecord.external_conversation_id == external_conversation_id,
        )
        if channel:
            query = query.filter(CaseConversationRecord.channel == channel)
        if channel_account_id:
            query = query.filter(
                CaseConversationRecord.channel_account_id == channel_account_id
            )
        record = query.order_by(CaseConversationRecord.created_at.desc()).first()
        return record.case_id if record else None

    def record_audit(
        self,
        *,
        tenant_id: str,
        case_id: str,
        event_type: str,
        identity: ActorIdentity | None = None,
        source_trace_id: str = "",
        before: dict | None = None,
        after: dict | None = None,
        rejection_reason: str = "",
    ) -> AuditLogRecord:
        record = AuditLogRecord(
            audit_id=f"audit_{new_id()}",
            tenant_id=tenant_id or "legacy",
            case_id=case_id,
            source_trace_id=source_trace_id,
            event_type=event_type,
            actor_id=identity.actor_id if identity else "",
            actor_role=identity.business_role.value if identity else "",
            conversation_role=identity.conversation_role.value if identity else "",
            authorization_basis=identity.authorization_basis if identity else "",
            before_json=before or {},
            after_json=after or {},
            rejection_reason=rejection_reason,
        )
        self.db.add(record)
        self.db.flush()
        return record

    def record_approval(
        self,
        *,
        tenant_id: str,
        case_id: str,
        draft_id: str,
        identity: ActorIdentity,
        source_trace_id: str,
        status: str,
        requested_by_actor_id: str = "",
        requested_by_actor_role: str = "",
        rejection_reason: str = "",
    ) -> ApprovalRecord:
        record = ApprovalRecord(
            approval_id=f"approval_{new_id()}",
            tenant_id=tenant_id or "legacy",
            case_id=case_id,
            draft_id=draft_id,
            status=status,
            requested_by_actor_id=requested_by_actor_id,
            requested_by_actor_role=requested_by_actor_role,
            approver_id=identity.actor_id,
            approver_role=identity.business_role.value,
            source_trace_id=source_trace_id,
            authorization_basis=identity.authorization_basis,
            rejection_reason=rejection_reason,
            decided_at=datetime.now(timezone.utc),
        )
        self.db.add(record)
        self.db.flush()
        return record

    def transition_case(
        self,
        *,
        project,
        after: CaseState | str,
        identity: ActorIdentity,
        source_trace_id: str,
    ) -> TransitionDecision:
        """Authorize, apply, and audit one Case state transition atomically."""

        before = CaseState(project.case_state or CaseState.INQUIRY)
        try:
            decision = authorize_transition(before, after, identity)
        except Exception as exc:
            self.record_audit(
                tenant_id=project.tenant_id,
                case_id=project.project_id,
                event_type="CASE_STATE_TRANSITION_REJECTED",
                identity=identity,
                source_trace_id=source_trace_id,
                before={"case_state": before.value},
                after={"case_state": str(after)},
                rejection_reason=getattr(exc, "reason", str(exc)),
            )
            raise
        project.case_state = decision.after.value
        project.source_trace_id = source_trace_id or project.source_trace_id
        self.record_audit(
            tenant_id=project.tenant_id,
            case_id=project.project_id,
            event_type="CASE_STATE_TRANSITION",
            identity=identity,
            source_trace_id=source_trace_id,
            before={"case_state": decision.before.value},
            after={"case_state": decision.after.value},
        )
        self.db.flush()
        return decision

