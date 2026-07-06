"""HTTP surface for the myaivan Web UI.

Pages:  GET /myaivan (welcome), GET /myaivan/work (conversation).
API:    /api/myaivan/... JSON endpoints used by the conversation page.

All endpoints fail with structured errors; draft-state violations return 409.
"""

from __future__ import annotations

import os
import struct

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from sqlalchemy.orm import Session

from aivan.db.session import get_db
from aivan.utils.ids import new_id
from aivan.web import auth as web_auth
from aivan.web import service
from aivan.web.email_outbound import email_status

router = APIRouter()

# Auth guard applied to every case/draft/upload endpoint. The i18n catalog
# stays public: it serves UI strings only, never user/case data.
_PROTECTED = [Depends(web_auth.require_web_api)]

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _upload_dir() -> str:
    return os.environ.get("AIVAN_WEB_UPLOAD_DIR", os.path.join("data", "web_uploads"))

_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def _png_dimensions(raw: bytes) -> tuple[int, int] | None:
    if len(raw) >= 24 and raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return struct.unpack(">II", raw[16:24])
    return None


def _gif_dimensions(raw: bytes) -> tuple[int, int] | None:
    if len(raw) >= 10 and raw[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", raw[6:10])
    return None


def _jpeg_dimensions(raw: bytes) -> tuple[int, int] | None:
    if len(raw) < 4 or not raw.startswith(b"\xff\xd8"):
        return None
    pos = 2
    while pos + 9 < len(raw):
        if raw[pos] != 0xFF:
            pos += 1
            continue
        marker = raw[pos + 1]
        pos += 2
        if marker in (0xD8, 0xD9):
            continue
        if pos + 2 > len(raw):
            return None
        length = struct.unpack(">H", raw[pos:pos + 2])[0]
        if length < 2 or pos + length > len(raw):
            return None
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB):
            if length >= 7:
                height, width = struct.unpack(">HH", raw[pos + 3:pos + 7])
                return width, height
            return None
        pos += length
    return None


def _image_dimensions(raw: bytes) -> tuple[int, int] | None:
    return _png_dimensions(raw) or _gif_dimensions(raw) or _jpeg_dimensions(raw)


def _text_preview(raw: bytes, content_type: str, filename: str) -> str:
    lower_name = filename.lower()
    looks_text = (
        content_type.startswith("text/")
        or content_type in {"application/json", "application/xml", "application/csv"}
        or lower_name.endswith((".txt", ".csv", ".md", ".json", ".xml", ".html", ".htm"))
    )
    if not looks_text:
        return ""
    try:
        text = raw[:4096].decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw[:4096].decode("gb18030")
        except UnicodeDecodeError:
            return ""
    text = " ".join(text.split())
    return text[:500]


def _upload_understanding(kind: str, filename: str, content_type: str, size_bytes: int, raw: bytes) -> dict:
    if kind == "image":
        dims = _image_dimensions(raw)
        summary = f"Image uploaded: {filename} ({content_type}, {size_bytes} bytes)."
        if dims:
            summary = (
                f"Image uploaded: {filename} ({content_type}, {dims[0]}x{dims[1]}, "
                f"{size_bytes} bytes)."
            )
        return {"summary": summary, "dimensions": dims}

    preview = _text_preview(raw, content_type, filename)
    if preview:
        return {
            "summary": (
                f"File uploaded: {filename} ({content_type}, {size_bytes} bytes). "
                f"Text preview: {preview}"
            ),
            "textPreview": preview,
        }
    return {
        "summary": f"File uploaded: {filename} ({content_type}, {size_bytes} bytes).",
    }


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

@router.post("/api/myaivan/cases", dependencies=_PROTECTED)
def create_case(body: dict | None = None, db: Session = Depends(get_db)):
    body = body or {}
    case = service.create_case(
        db,
        title=str(body.get("title") or ""),
        source_channel=str(body.get("sourceChannel") or "manual"),
    )
    return service.case_state(db, case)


@router.get("/api/myaivan/cases/{case_id}", dependencies=_PROTECTED)
def get_case(case_id: str, db: Session = Depends(get_db)):
    case = _require_case(db, case_id)
    return service.case_state(db, case)


@router.post("/api/myaivan/cases/{case_id}/messages", dependencies=_PROTECTED)
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


@router.post("/api/myaivan/cases/{case_id}/uploads", dependencies=_PROTECTED)
async def upload(case_id: str, file: UploadFile, db: Session = Depends(get_db)):
    case = _require_case(db, case_id)
    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 10 MB)")
    kind = "image" if (file.content_type or "") in _IMAGE_TYPES else "file"
    upload_dir = _upload_dir()
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = os.path.basename(file.filename or "upload.bin")
    content_type = file.content_type or "application/octet-stream"
    understanding = _upload_understanding(kind, safe_name, content_type, len(raw), raw)
    storage_path = os.path.join(upload_dir, f"{new_id()}_{safe_name}")
    with open(storage_path, "wb") as fh:
        fh.write(raw)
    record = service.add_attachment(
        db, case, kind=kind, filename=safe_name,
        content_type=content_type,
        size_bytes=len(raw), storage_path=storage_path,
        understanding=understanding,
    )
    state = service.case_state(db, case)
    state["attachmentId"] = record.attachment_id
    return state


@router.post("/api/myaivan/cases/{case_id}/drafts", dependencies=_PROTECTED)
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


@router.post("/api/myaivan/cases/{case_id}/drafts/{draft_id}/copied", dependencies=_PROTECTED)
def draft_copied(case_id: str, draft_id: str, db: Session = Depends(get_db)):
    case, _ = _draft_action(db, case_id, draft_id, lambda c, d: service.mark_copied(db, d))
    return service.case_state(db, case)


@router.post("/api/myaivan/cases/{case_id}/drafts/{draft_id}/mark-sent", dependencies=_PROTECTED)
def draft_mark_sent(case_id: str, draft_id: str, db: Session = Depends(get_db)):
    case, _ = _draft_action(db, case_id, draft_id, lambda c, d: service.mark_manually_sent(db, c, d))
    return service.case_state(db, case)


@router.post("/api/myaivan/cases/{case_id}/drafts/{draft_id}/reject", dependencies=_PROTECTED)
def draft_reject(case_id: str, draft_id: str, db: Session = Depends(get_db)):
    case, _ = _draft_action(db, case_id, draft_id, lambda c, d: service.reject_draft(db, c, d))
    return service.case_state(db, case)


@router.post("/api/myaivan/cases/{case_id}/drafts/{draft_id}/send-email", dependencies=_PROTECTED)
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


@router.get("/api/myaivan/email/status", dependencies=_PROTECTED)
def get_email_status():
    return {"status": email_status()}


@router.get("/api/myaivan/i18n/{lang}")
def get_i18n_catalog(lang: str):
    """UI string catalog. en/zh are built in; other languages are translated
    through giraffe-language-skill and fail soft to English."""
    from aivan.web import i18n

    catalog = i18n.get_catalog(lang)
    catalog["languages"] = i18n.SUPPORTED_LANGUAGES
    return catalog


@router.get("/api/myaivan/cases/{case_id}/backup.md", response_class=PlainTextResponse, dependencies=_PROTECTED)
def backup_markdown(case_id: str, db: Session = Depends(get_db)):
    case = _require_case(db, case_id)
    return service.export_markdown(db, case)


# ── Auth: login / logout ──────────────────────────────────────────────────────

@router.post("/api/myaivan/login")
def login(body: dict):
    """Exchange the AIVAN access key for a session cookie.

    Fails closed in misconfigured production; 401 on a wrong key. The i18n
    catalog and this endpoint are the only unauthenticated API surface.
    """
    from fastapi.responses import JSONResponse

    mode = web_auth.auth_mode()
    if mode == "misconfigured":
        raise HTTPException(
            status_code=503,
            detail="Server auth misconfigured: production requires AIVAN_API_KEY or AIVAN_AUTH_SECRET",
        )
    if mode == "open":
        return JSONResponse({"ok": True, "mode": "open"})
    key = str((body or {}).get("key") or "")
    if not web_auth.verify_presented_key(key):
        raise HTTPException(status_code=401, detail="Invalid access key")
    response = JSONResponse({"ok": True, "mode": "session"})
    response.set_cookie(
        web_auth.SESSION_COOKIE,
        web_auth.issue_session_token(),
        max_age=web_auth.session_ttl_seconds(),
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/api/myaivan/logout")
def logout():
    from fastapi.responses import JSONResponse

    response = JSONResponse({"ok": True})
    response.delete_cookie(web_auth.SESSION_COOKIE, path="/")
    return response


# ── Pages ─────────────────────────────────────────────────────────────────────

def _templates():
    from aivan.api.main import templates

    return templates


def _page_guard(request: Request):
    """Return a response that preempts the page, or None when access is OK."""
    from fastapi.responses import PlainTextResponse, RedirectResponse

    decision = web_auth.check_access(request)
    if decision == "ok":
        return None
    if decision == "fail_closed":
        return PlainTextResponse(
            "myaivan is unavailable: production requires AIVAN_API_KEY or AIVAN_AUTH_SECRET.",
            status_code=503,
        )
    return RedirectResponse("/myaivan/login", status_code=303)


@router.get("/myaivan/login", response_class=HTMLResponse)
def myaivan_login(request: Request):
    if web_auth.auth_mode() == "open":
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/myaivan", status_code=303)
    if web_auth.auth_mode() == "misconfigured":
        return _page_guard(request)
    return _templates().TemplateResponse(
        request, "myaivan_login.html", {"title": "myaivan — sign in"}
    )


@router.head("/myaivan/login")
def myaivan_login_head(request: Request):
    guard = _page_guard(request) if web_auth.auth_mode() == "misconfigured" else None
    if guard is not None:
        return guard
    if web_auth.auth_mode() == "open":
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/myaivan", status_code=303)
    return Response(status_code=200)


@router.get("/myaivan", response_class=HTMLResponse)
def myaivan_welcome(request: Request):
    guard = _page_guard(request)
    if guard is not None:
        return guard
    return _templates().TemplateResponse(
        request, "myaivan_welcome.html", {"title": "myaivan — AIVAN digital trade assistant"}
    )


@router.head("/myaivan")
def myaivan_welcome_head(request: Request):
    guard = _page_guard(request)
    if guard is not None:
        return guard
    return Response(status_code=200)


@router.get("/myaivan/work", response_class=HTMLResponse)
def myaivan_work(request: Request):
    guard = _page_guard(request)
    if guard is not None:
        return guard
    return _templates().TemplateResponse(
        request,
        "myaivan_work.html",
        {"title": "myaivan — workspace", "email_status": email_status()},
    )


@router.head("/myaivan/work")
def myaivan_work_head(request: Request):
    guard = _page_guard(request)
    if guard is not None:
        return guard
    return Response(status_code=200)
