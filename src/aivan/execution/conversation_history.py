"""Canonical English message bodies in existing DB process history, not memory."""
from __future__ import annotations

import hashlib

from aivan.db.models import ExecutionEventRecord
from aivan.integrations.language_skill import LanguageNormalizationRequired, has_non_latin_text


def persist_canonical_message(db, *, project, event, message) -> None:
    if has_non_latin_text(event.message_text):
        raise LanguageNormalizationRequired()
    digest = hashlib.sha256(event.message_text.encode()).hexdigest()
    event_id = "msgbody_" + hashlib.sha256(message.message_record_id.encode()).hexdigest()[:48]
    existing = db.get(ExecutionEventRecord, event_id)
    if existing is not None:
        if (existing.tenant_id != project.tenant_id
                or existing.payload_json.get("content_sha256") != digest):
            raise ValueError("CANONICAL_MESSAGE_IDENTITY_CONFLICT")
        return
    db.add(ExecutionEventRecord(
        event_id=event_id, tenant_id=project.tenant_id, project_id=project.project_id,
        event_type="CANONICAL_INBOUND_MESSAGE", actor=message.actor_id,
        actor_id=message.actor_id, actor_role=message.actor_role,
        conversation_role=message.conversation_role, source_trace_id=event.source_trace_id,
        authorization_basis=event.authorization_basis, summary="Canonical English inbound message",
        payload_digest=digest, payload_json={
            "message_record_id": message.message_record_id,
            "conversation_record_id": message.conversation_record_id,
            "message_text": event.message_text, "content_sha256": digest,
            "canonical_language": "en", "attachments": event.attachments,
        },
    ))
    db.flush()


def resolve_canonical_message(message, events) -> dict:
    for record in events:
        data = record.payload_json or {}
        if (record.event_type == "CANONICAL_INBOUND_MESSAGE"
                and record.tenant_id == message.tenant_id and record.project_id == message.case_id
                and record.actor_id == message.actor_id
                and data.get("message_record_id") == message.message_record_id
                and data.get("conversation_record_id") == message.conversation_record_id):
            text = data.get("message_text")
            if (not isinstance(text, str) or has_non_latin_text(text)
                    or hashlib.sha256(text.encode()).hexdigest() != data.get("content_sha256")):
                return {"message_text": None, "body_resolution": "integrity_mismatch"}
            return {"message_text": text, "body_resolution": "resolved", "canonical_language": "en"}
    return {"message_text": None, "body_resolution": "missing_legacy_content"}
