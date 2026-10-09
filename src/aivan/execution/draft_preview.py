"""Transient commercial rendering with durable English-only preview fingerprints.

Translated text exists only in memory and API responses. Existing append-only
case audits retain identity/language/digests, never a localized body or subject.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.orm import Session

from aivan.db.models.domain import AuditLogRecord
from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.integrations.outbound_translation import TranslationUnavailable, translate_authoritative_english

PREVIEW_EVENT = "DRAFT_CONTENT_PREVIEWED"
APPROVAL_EVENT = "DRAFT_CONTENT_APPROVED"


class PreviewError(ValueError):
    def __init__(self, code: str, status_code: int = 409):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sender_identity(draft: InquiryDraftRecord, manual: bool = False) -> str:
    if manual:
        return draft.channel_account_id or "Manual sender (account not recorded)"
    if draft.channel in {"email", "smtp"}:
        return os.getenv("AIVAN_PRESET_MAILBOX") or os.getenv("AIVAN_SMTP_USERNAME", "") or draft.channel_account_id or "configured-email-account"
    return draft.channel_account_id or "configured-channel-account"


def source_fingerprint(draft: InquiryDraftRecord, target: str, manual: bool = False) -> str:
    value = {name: getattr(draft, name) for name in (
        "draft_id", "tenant_id", "project_id", "conversation_id", "channel",
        "channel_account_id", "target_peer_id", "target_role", "message_text",
        "message_type", "attachments_json",
    )}
    value["subject"] = next((line.split(":", 1)[1].strip() for line in (draft.notes or "").splitlines()
                             if line.lower().startswith("subject:")), "")
    value.update(target_language=target, sender=sender_identity(draft, manual), manual_delivery=manual)
    return digest(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")))


@dataclass(frozen=True)
class RenderedDraft:
    target_language: str
    message_text: str
    source_sha256: str
    rendered_sha256: str
    manual_delivery: bool = False

    def fingerprints(self) -> dict:
        return {"target_language": self.target_language, "source_sha256": self.source_sha256,
                "rendered_sha256": self.rendered_sha256, "manual_delivery": self.manual_delivery}


def render_draft(draft: InquiryDraftRecord, target: str, manual: bool = False) -> RenderedDraft:
    target = target.strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}", target):
        raise PreviewError("INVALID_TARGET_LANGUAGE", 422)
    source = draft.message_text or ""
    if target == "en":
        rendered = source
    else:
        try:
            translated = translate_authoritative_english(
                source, target, target_channel=draft.channel,
                message_type="commercial_draft", business_refs={"draft_id": draft.draft_id},
            )
            rendered = translated.text
        except (TranslationUnavailable, ValueError):
            raise PreviewError("DRAFT_TRANSLATION_UNAVAILABLE", 503) from None
    if not rendered.strip():
        raise PreviewError("DRAFT_RENDER_EMPTY", 503)
    return RenderedDraft(target, rendered, source_fingerprint(draft, target, manual), digest(rendered), manual)


def _audit(db: Session, draft: InquiryDraftRecord, event: str, metadata: dict,
           *, identity=None, trace_id: str = "") -> AuditLogRecord:
    row = AuditLogRecord(
        audit_id="render_" + uuid4().hex, tenant_id=draft.tenant_id,
        case_id=draft.project_id, source_trace_id=trace_id, event_type=event,
        actor_id=identity.actor_id if identity else draft.approved_by or "user",
        actor_role=identity.business_role.value if identity else "approver",
        conversation_role=identity.conversation_role.value if identity else "approval_thread",
        authorization_basis=identity.authorization_basis if identity else "draft_approval",
        before_json={}, after_json={"draft_id": draft.draft_id, **metadata},
    )
    db.add(row)
    db.flush()
    return row


def latest_preview(db: Session, draft: InquiryDraftRecord) -> AuditLogRecord | None:
    return db.query(AuditLogRecord).filter(
        AuditLogRecord.tenant_id == draft.tenant_id,
        AuditLogRecord.case_id == draft.project_id,
        AuditLogRecord.event_type == PREVIEW_EVENT,
        AuditLogRecord.after_json["draft_id"].as_string() == draft.draft_id,
    ).order_by(AuditLogRecord.created_at.desc(), AuditLogRecord.audit_id.desc()).first()


def create_preview(db: Session, draft: InquiryDraftRecord, target: str, *, identity=None,
                   trace_id: str = "", manual: bool = False) -> tuple[AuditLogRecord, RenderedDraft]:
    if draft.status not in {"pending_approval", "send_failed"}:
        raise PreviewError("DRAFT_PREVIEW_REQUIRES_PENDING_REVIEW")
    rendered = render_draft(draft, target, manual)
    row = _audit(db, draft, PREVIEW_EVENT, rendered.fingerprints(), identity=identity, trace_id=trace_id)
    return row, rendered


def verify_preview(db: Session, draft: InquiryDraftRecord, preview_id: str | None,
                   *, identity=None, trace_id: str = "") -> tuple[AuditLogRecord, RenderedDraft]:
    if preview_id is not None and (not isinstance(preview_id, str)
                                   or not re.fullmatch(r"render_[a-f0-9]{32}", preview_id)):
        raise PreviewError("INVALID_DRAFT_PREVIEW_ID", 422)
    if preview_id:
        row = db.get(AuditLogRecord, preview_id)
        if (row is None or row.event_type != PREVIEW_EVENT or row.tenant_id != draft.tenant_id
                or row.case_id != draft.project_id or row.after_json.get("draft_id") != draft.draft_id):
            raise PreviewError("DRAFT_PREVIEW_NOT_FOUND", 404)
    else:
        row = latest_preview(db, draft)
        if row is not None and row.after_json.get("target_language") != "en":
            raise PreviewError("DRAFT_LOCALIZED_PREVIEW_REQUIRED")
        # Backwards-compatible explicit English approval still records a bound
        # English preview; the web UI always submits the reviewed preview ID.
        if row is None:
            return create_preview(db, draft, "en", identity=identity, trace_id=trace_id)
    metadata = row.after_json
    target = metadata.get("target_language", "en")
    manual = metadata.get("manual_delivery") is True
    if metadata.get("source_sha256") != source_fingerprint(draft, target, manual):
        raise PreviewError("DRAFT_PREVIEW_SOURCE_CHANGED")
    rendered = render_draft(draft, target, manual)
    if rendered.rendered_sha256 != metadata.get("rendered_sha256"):
        raise PreviewError("DRAFT_PREVIEW_TRANSLATION_CHANGED")
    return row, rendered


def bind_approval(db: Session, draft: InquiryDraftRecord, preview: AuditLogRecord,
                  *, identity=None, trace_id: str = "") -> None:
    _audit(db, draft, APPROVAL_EVENT, {
        **{key: preview.after_json[key] for key in ("target_language", "source_sha256", "rendered_sha256", "manual_delivery")},
        "preview_id": preview.audit_id, "approval_id": draft.approval_id,
    }, identity=identity, trace_id=trace_id)


def approval_binding(db: Session, draft: InquiryDraftRecord) -> AuditLogRecord:
    row = db.query(AuditLogRecord).filter(
        AuditLogRecord.tenant_id == draft.tenant_id,
        AuditLogRecord.case_id == draft.project_id,
        AuditLogRecord.event_type == APPROVAL_EVENT,
        AuditLogRecord.after_json["draft_id"].as_string() == draft.draft_id,
        AuditLogRecord.after_json["approval_id"].as_string() == (draft.approval_id or ""),
    ).order_by(AuditLogRecord.created_at.desc(), AuditLogRecord.audit_id.desc()).first()
    if row is None:
        raise PreviewError("DRAFT_APPROVAL_PREVIEW_REQUIRED")
    return row


def approved_render(db: Session, draft: InquiryDraftRecord) -> RenderedDraft:
    row = approval_binding(db, draft)
    _, rendered = verify_preview(db, draft, row.after_json.get("preview_id"))
    if any(row.after_json.get(key) != value for key, value in rendered.fingerprints().items()):
        raise PreviewError("DRAFT_APPROVAL_PREVIEW_CHANGED")
    return rendered


def invalidate_approval(db: Session, draft: InquiryDraftRecord, code: str) -> None:
    old_approval = draft.approval_id
    draft.status = "pending_approval"
    draft.approved_by = ""
    draft.approved_at = None
    draft.approval_id = ""
    _audit(db, draft, "DRAFT_APPROVAL_INVALIDATED", {
        "previous_approval_id": old_approval, "reason": code,
    })
