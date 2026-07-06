"""Case workflow service for the myaivan Web UI.

Owns the inquiry/case lifecycle behind the conversation page: cases, message
history, generated outbound drafts, their review transitions
(draft → copied → email_sent / manually_sent / rejected / failed), audit
logging, and Markdown backup export.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from aivan.db.models.web_case import (
    WebAttachmentRecord,
    WebAuditLogRecord,
    WebCaseMessageRecord,
    WebCaseRecord,
    WebOutboundDraftRecord,
)
from aivan.utils.ids import new_id
from aivan.utils.time_utils import utcnow
from aivan.web import assistant
from aivan.web.email_outbound import EmailSendResult, send_email

DRAFT_STATUSES = {"draft", "copied", "email_sent", "manually_sent", "rejected", "failed"}


class DraftStateError(ValueError):
    """Raised when a draft action is not valid for the draft's current state."""


def _iso(dt: datetime | None) -> str:
    return dt.isoformat() if dt else ""


# ── audit ─────────────────────────────────────────────────────────────────────

def log_event(db: Session, case_id: str, event: str, detail: str, meta: dict | None = None) -> WebAuditLogRecord:
    record = WebAuditLogRecord(
        audit_id=f"audit_{new_id()}",
        case_id=case_id,
        event=event,
        detail=detail,
        meta=meta or {},
    )
    db.add(record)
    return record


def _touch(case: WebCaseRecord) -> None:
    case.updated_at = utcnow()


# ── cases ─────────────────────────────────────────────────────────────────────

def create_case(db: Session, title: str = "", source_channel: str = "manual") -> WebCaseRecord:
    case = WebCaseRecord(
        case_id=f"case_{new_id()}",
        title=title or "New inquiry",
        status="new",
        source_channel=source_channel,
    )
    db.add(case)
    log_event(db, case.case_id, "case_created", f"Case created (source: {source_channel})")
    db.commit()
    return case


def get_case(db: Session, case_id: str) -> WebCaseRecord | None:
    return db.get(WebCaseRecord, case_id)


def case_state(db: Session, case: WebCaseRecord) -> dict:
    messages = (
        db.query(WebCaseMessageRecord)
        .filter_by(case_id=case.case_id)
        .order_by(WebCaseMessageRecord.created_at)
        .all()
    )
    drafts = (
        db.query(WebOutboundDraftRecord)
        .filter_by(case_id=case.case_id)
        .order_by(WebOutboundDraftRecord.created_at)
        .all()
    )
    attachments = db.query(WebAttachmentRecord).filter_by(case_id=case.case_id).all()
    audits = (
        db.query(WebAuditLogRecord)
        .filter_by(case_id=case.case_id)
        .order_by(WebAuditLogRecord.created_at)
        .all()
    )
    return {
        "case": {
            "id": case.case_id,
            "title": case.title,
            "status": case.status,
            "sourceChannel": case.source_channel,
            "targetChannel": case.target_channel,
            "createdAt": _iso(case.created_at),
            "updatedAt": _iso(case.updated_at),
        },
        "messages": [
            {
                "id": m.message_id,
                "role": m.role,
                "type": m.message_type,
                "content": m.content,
                "metadata": m.meta,
                "createdAt": _iso(m.created_at),
            }
            for m in messages
        ],
        "outboundDrafts": [_draft_dict(d) for d in drafts],
        "attachments": [
            {
                "id": a.attachment_id,
                "kind": a.kind,
                "filename": a.filename,
                "contentType": a.content_type,
                "sizeBytes": a.size_bytes,
                "createdAt": _iso(a.created_at),
            }
            for a in attachments
        ],
        "auditLogs": [
            {
                "id": log.audit_id,
                "event": log.event,
                "detail": log.detail,
                "metadata": log.meta,
                "createdAt": _iso(log.created_at),
            }
            for log in audits
        ],
    }


def _draft_dict(d: WebOutboundDraftRecord) -> dict:
    return {
        "id": d.draft_id,
        "caseId": d.case_id,
        "channel": d.channel,
        "recipient": d.recipient,
        "subject": d.subject,
        "body": d.body,
        "status": d.status,
        "riskLevel": d.risk_level,
        "riskNotes": d.risk_notes,
        "createdAt": _iso(d.created_at),
        "updatedAt": _iso(d.updated_at),
    }


# ── messages / assistant turn ─────────────────────────────────────────────────

def add_message(
    db: Session,
    case: WebCaseRecord,
    role: str,
    content: str,
    message_type: str = "text",
    meta: dict | None = None,
) -> WebCaseMessageRecord:
    record = WebCaseMessageRecord(
        message_id=f"msg_{new_id()}",
        case_id=case.case_id,
        role=role,
        message_type=message_type,
        content=content,
        meta=meta or {},
    )
    db.add(record)
    _touch(case)
    return record


_REPLY_COMMAND = ("reply", "draft", "generate", "回复", "生成", "草稿")


def _wants_reply(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in _REPLY_COMMAND)


def _channel_from_text(text: str) -> str:
    lowered = text.lower()
    for channel in ("email", "whatsapp", "wechat", "line", "wangwang"):
        if channel in lowered or (channel == "wechat" and "微信" in text) or (
            channel == "email" and "邮件" in text
        ):
            return channel
    return ""


def handle_user_message(
    db: Session,
    case: WebCaseRecord,
    content: str,
    message_type: str = "text",
) -> dict:
    """Ingest a user text/paste turn, produce the AIVAN response, and (when
    asked) generate an outbound draft for the review area."""
    add_message(db, case, "user", content, message_type=message_type)
    log_event(db, case.case_id, "message_received", f"{message_type} message received")

    analysis = assistant.analyze_message(content)
    draft = None

    wants_reply = _wants_reply(content)
    channel = _channel_from_text(content) or case.target_channel or ""

    if wants_reply:
        draft_channel = channel or "manual"
        purpose = {
            "buyer_inquiry": "buyer inquiry",
            "supplier_quote": "supplier quote",
            "follow_up": "follow-up",
        }.get(analysis.message_kind, "business message")
        body = assistant.generate_draft_body(draft_channel, purpose, content, analysis)
        draft = create_draft(db, case, channel=draft_channel, body=body, purpose=purpose)
        reply_text = (
            f"I prepared a {draft_channel} draft for your review in the outbound area below. "
            "Copy it for manual paste, send it by email, mark it as sent, or reject it."
        )
        add_message(db, case, "aivan", reply_text, message_type="draft_notice",
                    meta={"draftId": draft.draft_id})
    else:
        add_message(db, case, "aivan", analysis.summary, message_type="structured_summary",
                    meta={"kind": analysis.message_kind, "extracted": analysis.extracted,
                          "missing": analysis.missing,
                          "needsCanonicalization": analysis.needs_canonicalization})

    if case.status == "new":
        case.status = "in_progress"
    if channel:
        case.target_channel = channel
    _touch(case)
    db.commit()

    return {
        "analysis": {
            "kind": analysis.message_kind,
            "language": analysis.language,
            "summary": analysis.summary,
            "extracted": analysis.extracted,
            "missing": analysis.missing,
        },
        "draft": _draft_dict(draft) if draft else None,
    }


# ── attachments ───────────────────────────────────────────────────────────────

def add_attachment(
    db: Session,
    case: WebCaseRecord,
    kind: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    storage_path: str,
    understanding: dict | None = None,
) -> WebAttachmentRecord:
    understanding = understanding or {}
    record = WebAttachmentRecord(
        attachment_id=f"att_{new_id()}",
        case_id=case.case_id,
        kind=kind,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        storage_path=storage_path,
    )
    db.add(record)
    add_message(db, case, "user", filename, message_type=kind,
                meta={"attachmentId": record.attachment_id, "sizeBytes": size_bytes,
                      "contentType": content_type})
    summary = understanding.get("summary") or (
        f"Received {kind} “{filename}” ({size_bytes} bytes)."
    )
    add_message(
        db, case, "aivan",
        f"{summary} Tell me what to do with it: summarize it, extract trade facts, "
        "or draft a reply/inquiry based on it.",
        message_type="structured_summary",
        meta={"attachmentId": record.attachment_id, "understanding": understanding},
    )
    log_event(db, case.case_id, f"{kind}_uploaded", filename,
              meta={"attachmentId": record.attachment_id, "understanding": understanding})
    _touch(case)
    db.commit()
    return record


# ── drafts ────────────────────────────────────────────────────────────────────

def create_draft(
    db: Session,
    case: WebCaseRecord,
    channel: str,
    body: str,
    purpose: str = "",
    recipient: str = "",
    subject: str = "",
) -> WebOutboundDraftRecord:
    risk_level, risk_notes = assistant.assess_risk(body)
    draft = WebOutboundDraftRecord(
        draft_id=f"wdraft_{new_id()}",
        case_id=case.case_id,
        channel=channel,
        recipient=recipient,
        subject=subject or (f"Re: {purpose}" if purpose else ""),
        body=body,
        status="draft",
        risk_level=risk_level,
        risk_notes=risk_notes,
    )
    db.add(draft)
    case.status = "draft_ready"
    log_event(db, case.case_id, "draft_generated",
              f"{channel} draft generated ({purpose or 'outbound'}), risk={risk_level}",
              meta={"draftId": draft.draft_id})
    _touch(case)
    return draft


def get_draft(db: Session, draft_id: str) -> WebOutboundDraftRecord | None:
    return db.get(WebOutboundDraftRecord, draft_id)


def mark_copied(db: Session, draft: WebOutboundDraftRecord) -> WebOutboundDraftRecord:
    if draft.status in ("rejected",):
        raise DraftStateError(f"draft {draft.draft_id} is rejected; regenerate it instead")
    if draft.status == "draft":
        draft.status = "copied"
    draft.updated_at = utcnow()
    log_event(db, draft.case_id, "draft_copied", "Draft copied for manual paste",
              meta={"draftId": draft.draft_id})
    db.commit()
    return draft


def mark_manually_sent(db: Session, case: WebCaseRecord, draft: WebOutboundDraftRecord) -> WebOutboundDraftRecord:
    if draft.status in ("rejected", "email_sent"):
        raise DraftStateError(f"draft {draft.draft_id} cannot be marked sent from status {draft.status!r}")
    draft.status = "manually_sent"
    draft.updated_at = utcnow()
    case.status = "sent"
    add_message(db, case, "system",
                "Draft confirmed as manually pasted and sent through an external channel.",
                message_type="audit_event", meta={"draftId": draft.draft_id})
    log_event(db, draft.case_id, "manual_send_confirmed",
              "User confirmed manual copy/paste send", meta={"draftId": draft.draft_id})
    _touch(case)
    db.commit()
    return draft


def reject_draft(db: Session, case: WebCaseRecord, draft: WebOutboundDraftRecord) -> WebOutboundDraftRecord:
    if draft.status in ("email_sent", "manually_sent"):
        raise DraftStateError(f"draft {draft.draft_id} was already sent; it cannot be rejected")
    draft.status = "rejected"
    draft.updated_at = utcnow()
    case.status = "rejected"
    add_message(db, case, "aivan",
                "Understood — the draft is rejected. What should I change? "
                "Tell me the revision (tone, terms, missing details) and I will regenerate it.",
                message_type="text", meta={"draftId": draft.draft_id})
    log_event(db, draft.case_id, "draft_rejected", "Draft rejected by user",
              meta={"draftId": draft.draft_id})
    _touch(case)
    db.commit()
    return draft


def send_draft_email(
    db: Session,
    case: WebCaseRecord,
    draft: WebOutboundDraftRecord,
    recipient: str = "",
) -> tuple[WebOutboundDraftRecord, EmailSendResult]:
    if draft.status in ("rejected", "email_sent", "manually_sent"):
        raise DraftStateError(f"draft {draft.draft_id} cannot be emailed from status {draft.status!r}")
    to = (recipient or draft.recipient or "").strip()
    log_event(db, draft.case_id, "email_send_requested", f"Email send requested to {to or '(unset)'}",
              meta={"draftId": draft.draft_id})

    if not to:
        result = EmailSendResult(success=False, provider="none", error="recipient is required")
    else:
        result = send_email(
            to=to,
            subject=draft.subject or "AIVAN outbound message",
            body=draft.body,
            case_id=case.case_id,
            draft_id=draft.draft_id,
        )

    if result.success:
        draft.status = "email_sent"
        draft.recipient = to
        case.status = "sent"
        label = "email sent via aivan-openclaw" if result.provider == "aivan-openclaw" else "MOCK email send (no real delivery)"
        add_message(db, case, "system", f"✉️ {label}: {to}", message_type="audit_event",
                    meta={"draftId": draft.draft_id, "provider": result.provider})
        log_event(db, draft.case_id, "email_sent", label,
                  meta={"draftId": draft.draft_id, "provider": result.provider,
                        "messageId": result.message_id})
    else:
        draft.status = "failed"
        log_event(db, draft.case_id, "email_failed", result.error or "email send failed",
                  meta={"draftId": draft.draft_id, "provider": result.provider})
    draft.updated_at = utcnow()
    _touch(case)
    db.commit()
    return draft, result


# ── backup ────────────────────────────────────────────────────────────────────

def export_markdown(db: Session, case: WebCaseRecord) -> str:
    state = case_state(db, case)
    lines: list[str] = []
    c = state["case"]
    lines.append(f"# AIVAN Case Backup — {c['title']}")
    lines.append("")
    lines.append(f"- Case ID: {c['id']}")
    lines.append(f"- Status: {c['status']}")
    lines.append(f"- Source channel: {c['sourceChannel'] or 'manual'}")
    lines.append(f"- Created: {c['createdAt']}")
    lines.append(f"- Updated: {c['updatedAt']}")
    lines.append("")
    lines.append("## Conversation")
    lines.append("")
    for m in state["messages"]:
        lines.append(f"**{m['role']}** ({m['type']}, {m['createdAt']}):")
        lines.append("")
        lines.append(m["content"])
        lines.append("")
    if state["attachments"]:
        lines.append("## Attachments")
        lines.append("")
        for a in state["attachments"]:
            lines.append(f"- [{a['kind']}] {a['filename']} ({a['sizeBytes']} bytes)")
        lines.append("")
    lines.append("## Outbound Drafts")
    lines.append("")
    if not state["outboundDrafts"]:
        lines.append("(none)")
        lines.append("")
    for d in state["outboundDrafts"]:
        lines.append(f"### Draft {d['id']} — {d['channel']} — status: {d['status']}")
        lines.append("")
        if d["recipient"]:
            lines.append(f"- Recipient: {d['recipient']}")
        if d["subject"]:
            lines.append(f"- Subject: {d['subject']}")
        lines.append(f"- Risk level: {d['riskLevel']}")
        for note in d["riskNotes"] or []:
            lines.append(f"- Risk note: {note}")
        lines.append("")
        lines.append("```text")
        lines.append(d["body"])
        lines.append("```")
        lines.append("")
    lines.append("## Audit Log")
    lines.append("")
    for log in state["auditLogs"]:
        lines.append(f"- {log['createdAt']} — {log['event']}: {log['detail']}")
    lines.append("")
    log_event(db, case.case_id, "backup_exported", "Markdown backup exported")
    db.commit()
    return "\n".join(lines)
