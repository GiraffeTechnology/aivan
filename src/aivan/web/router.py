"""HTTP surface for the myaivan Web UI.

Pages:  GET /myaivan (welcome), GET /myaivan/work (conversation).
API:    /api/myaivan/... JSON endpoints used by the conversation page.

All endpoints fail with structured errors; draft-state violations return 409.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy.orm import Session

from aivan.db.session import get_db
from aivan.utils.ids import new_id
from aivan.web import service
from aivan.web.email_outbound import email_status

router = APIRouter()

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _upload_dir() -> str:
    return os.environ.get("AIVAN_WEB_UPLOAD_DIR", os.path.join("data", "web_uploads"))

_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def _require_case(db: Session, case_id: str):
    case = service.get_case(db, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return case


def _require_draft(db: Session, case_id: str, draft_id: str):
    draft = service.get_draft(db, draft_id)
    if draft is None or draft.case_id != case_id:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found in case {case_id}")
    return draft


# ── API ───────────────────────────────────────────────────────────────────────

@router.post("/api/myaivan/cases")
def create_case(body: dict | None = None, db: Session = Depends(get_db)):
    body = body or {}
    case = service.create_case(
        db,
        title=str(body.get("title") or ""),
        source_channel=str(body.get("sourceChannel") or "manual"),
    )
    return service.case_state(db, case)


@router.get("/api/myaivan/cases/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db)):
    case = _require_case(db, case_id)
    return service.case_state(db, case)


@router.post("/api/myaivan/cases/{case_id}/messages")
def post_message(case_id: str, body: dict, db: Session = Depends(get_db)):
    case = _require_case(db, case_id)
    content = str(body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=422, detail="content is required")
    message_type = str(body.get("type") or "text")
    if message_type not in ("text", "paste"):
        raise HTTPException(status_code=422, detail=f"unsupported message type {message_type!r}")
    result = service.handle_user_message(db, case, content, message_type=message_type)
    state = service.case_state(db, case)
    state["turn"] = result
    return state


@router.post("/api/myaivan/cases/{case_id}/uploads")
async def upload(case_id: str, file: UploadFile, db: Session = Depends(get_db)):
    case = _require_case(db, case_id)
    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 10 MB)")
    kind = "image" if (file.content_type or "") in _IMAGE_TYPES else "file"
    upload_dir = _upload_dir()
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = os.path.basename(file.filename or "upload.bin")
    storage_path = os.path.join(upload_dir, f"{new_id()}_{safe_name}")
    with open(storage_path, "wb") as fh:
        fh.write(raw)
    record = service.add_attachment(
        db, case, kind=kind, filename=safe_name,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(raw), storage_path=storage_path,
    )
    state = service.case_state(db, case)
    state["attachmentId"] = record.attachment_id
    return state


@router.post("/api/myaivan/cases/{case_id}/drafts")
def create_draft(case_id: str, body: dict, db: Session = Depends(get_db)):
    """Explicit draft generation for a chosen channel (review-area regenerate)."""
    from aivan.web import assistant

    case = _require_case(db, case_id)
    channel = str(body.get("channel") or "manual").lower()
    if channel not in assistant.CHANNELS:
        raise HTTPException(status_code=422, detail=f"unsupported channel {channel!r}")
    context = str(body.get("context") or "")
    purpose = str(body.get("purpose") or "business message")
    analysis = assistant.analyze_message(context) if context else None
    draft_body = assistant.generate_draft_body(channel, purpose, context, analysis)
    draft = service.create_draft(
        db, case, channel=channel, body=draft_body, purpose=purpose,
        recipient=str(body.get("recipient") or ""),
        subject=str(body.get("subject") or ""),
    )
    db.commit()
    return service.case_state(db, case)


def _draft_action(db: Session, case_id: str, draft_id: str, action):
    case = _require_case(db, case_id)
    draft = _require_draft(db, case_id, draft_id)
    try:
        return case, action(case, draft)
    except service.DraftStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/api/myaivan/cases/{case_id}/drafts/{draft_id}/copied")
def draft_copied(case_id: str, draft_id: str, db: Session = Depends(get_db)):
    case, _ = _draft_action(db, case_id, draft_id, lambda c, d: service.mark_copied(db, d))
    return service.case_state(db, case)


@router.post("/api/myaivan/cases/{case_id}/drafts/{draft_id}/mark-sent")
def draft_mark_sent(case_id: str, draft_id: str, db: Session = Depends(get_db)):
    case, _ = _draft_action(db, case_id, draft_id, lambda c, d: service.mark_manually_sent(db, c, d))
    return service.case_state(db, case)


@router.post("/api/myaivan/cases/{case_id}/drafts/{draft_id}/reject")
def draft_reject(case_id: str, draft_id: str, db: Session = Depends(get_db)):
    case, _ = _draft_action(db, case_id, draft_id, lambda c, d: service.reject_draft(db, c, d))
    return service.case_state(db, case)


@router.post("/api/myaivan/cases/{case_id}/drafts/{draft_id}/send-email")
def draft_send_email(case_id: str, draft_id: str, body: dict | None = None, db: Session = Depends(get_db)):
    case = _require_case(db, case_id)
    draft = _require_draft(db, case_id, draft_id)
    recipient = str((body or {}).get("recipient") or "")
    try:
        draft, result = service.send_draft_email(db, case, draft, recipient=recipient)
    except service.DraftStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    state = service.case_state(db, case)
    state["emailResult"] = {
        "success": result.success,
        "provider": result.provider,
        "messageId": result.message_id,
        "error": result.error,
    }
    return state


@router.get("/api/myaivan/email/status")
def get_email_status():
    return {"status": email_status()}


@router.get("/api/myaivan/cases/{case_id}/backup.md", response_class=PlainTextResponse)
def backup_markdown(case_id: str, db: Session = Depends(get_db)):
    case = _require_case(db, case_id)
    return service.export_markdown(db, case)


# ── Pages ─────────────────────────────────────────────────────────────────────

def _templates():
    from aivan.api.main import templates

    return templates


@router.get("/myaivan", response_class=HTMLResponse)
def myaivan_welcome(request: Request):
    return _templates().TemplateResponse(
        request, "myaivan_welcome.html", {"title": "myaivan — AIVAN digital trade assistant"}
    )


@router.get("/myaivan/work", response_class=HTMLResponse)
def myaivan_work(request: Request):
    return _templates().TemplateResponse(
        request,
        "myaivan_work.html",
        {"title": "myaivan — workspace", "email_status": email_status()},
    )
