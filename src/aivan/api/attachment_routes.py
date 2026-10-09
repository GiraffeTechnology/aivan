"""Safe file/image intake with durable provider readback and no local blob store."""
from __future__ import annotations

import base64
import binascii
import hashlib
import struct

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from aivan.api.request_context import RequestContext
from aivan.api.workbench_routes import _context, _get_case, _identity
from aivan.db.session import get_db
from aivan.domain.roles import BusinessRole
from aivan.integrations.attachment_client import AttachmentClient, AttachmentError
from aivan.integrations.language_skill import (
    LanguageNormalizationRequired, LanguageSkillUnavailable,
    canonicalize_rfq, canonical_english_text,
)

router = APIRouter(tags=["attachments"])
MAX_BYTES = 10 * 1024 * 1024
MEDIA = {"text/plain": "txt", "image/png": "png", "image/jpeg": "jpg"}


class Upload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_name: str = Field(min_length=1, max_length=255)
    content_type: str
    content_base64: str = Field(min_length=1, max_length=4 * ((MAX_BYTES + 2) // 3))
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _jpeg_dimensions(content):
    if not (content.startswith(b"\xff\xd8") and content.endswith(b"\xff\xd9")):
        return None
    offset = 2
    while offset + 4 <= len(content):
        if content[offset] != 255:
            return None
        while offset < len(content) and content[offset] == 255:
            offset += 1
        if offset >= len(content):
            return None
        marker = content[offset]
        offset += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(content):
            return None
        length = int.from_bytes(content[offset:offset + 2], "big")
        if length < 2 or offset + length > len(content):
            return None
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if length < 8:
                return None
            height = int.from_bytes(content[offset + 3:offset + 5], "big")
            width = int.from_bytes(content[offset + 5:offset + 7], "big")
            return width, height
        offset += length
    return None


def _case_reference(db, context, case_id):
    project = _get_case(db, context, case_id)
    reference = (project.requirement_json or {}).get("giraffe_db_graph") or {}
    provider_case = reference.get("procurement_case_id")
    if not isinstance(provider_case, str) or not provider_case:
        raise HTTPException(409, detail={"error": "ATTACHMENT_PERSISTED_CASE_REQUIRED"})
    return provider_case


def _input_content(body, context):
    if (body.content_type not in MEDIA or body.file_name in {".", ".."}
            or any(c in body.file_name for c in "/\\")
            or any(ord(c) < 32 or ord(c) == 127 for c in body.file_name)):
        raise HTTPException(422, detail={"error": "ATTACHMENT_TYPE_OR_NAME_INVALID"})
    try:
        content = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, detail={"error": "ATTACHMENT_ENCODING_INVALID"}) from exc
    if not content or len(content) > MAX_BYTES:
        raise HTTPException(413, detail={"error": "ATTACHMENT_SIZE_INVALID"})
    if hashlib.sha256(content).hexdigest() != body.sha256:
        raise HTTPException(422, detail={"error": "ATTACHMENT_HASH_MISMATCH"})
    canonical = None
    if body.content_type == "text/plain":
        if len(content) > 64 * 1024:
            raise HTTPException(413, detail={"error": "ATTACHMENT_TEXT_LIMIT", "max_bytes": 64 * 1024})
        try:
            canonical = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(422, detail={"error": "ATTACHMENT_UTF8_REQUIRED"}) from exc
        if "\x00" in canonical or not canonical.strip():
            raise HTTPException(422, detail={"error": "ATTACHMENT_TEXT_INVALID"})
        try:
            packet = canonicalize_rfq(canonical, source_channel="myaivan", tenant_id=context.tenant_id)
        except LanguageSkillUnavailable as exc:
            raise LanguageNormalizationRequired() from exc
        # A Latin script is not evidence of English. Require the same language
        # service contract as message intake, including English text attachments.
        if packet is None:
            raise LanguageNormalizationRequired()
        canonical = canonical_english_text(packet)
        content = canonical.encode("utf-8")
    elif body.content_type == "image/png":
        if (len(content) < 33 or not content.startswith(b"\x89PNG\r\n\x1a\n")
                or content[12:16] != b"IHDR"):
            raise HTTPException(422, detail={"error": "ATTACHMENT_IMAGE_INVALID"})
        width, height = struct.unpack(">II", content[16:24])
        if not width or not height or width * height > 16_000_000:
            raise HTTPException(422, detail={"error": "ATTACHMENT_IMAGE_DIMENSIONS_INVALID"})
    else:
        dimensions = _jpeg_dimensions(content)
        if not dimensions:
            raise HTTPException(422, detail={"error": "ATTACHMENT_IMAGE_INVALID"})
        width, height = dimensions
        if not width or not height or width * height > 16_000_000:
            raise HTTPException(422, detail={"error": "ATTACHMENT_IMAGE_DIMENSIONS_INVALID"})
    if len(content) > MAX_BYTES:
        raise HTTPException(413, detail={"error": "ATTACHMENT_SIZE_INVALID"})
    return content, canonical


def _raise_provider(error, context):
    raise HTTPException(error.status, detail={"error": error.code, "trace_id": context.trace_id}) from error


def export_attachment_metadata(db, context, case_id):
    project = _get_case(db, context, case_id)
    reference = (project.requirement_json or {}).get("giraffe_db_graph") or {}
    provider_case = reference.get("procurement_case_id")
    if not provider_case:
        return []
    try:
        return AttachmentClient(context.tenant_id, context.trace_id).list(provider_case)
    except AttachmentError as error:
        _raise_provider(error, context)


@router.get("/cases/{case_id}/attachments")
def list_attachments(case_id: str, db: Session = Depends(get_db),
                     context: RequestContext = Depends(_context)):
    provider_case = _case_reference(db, context, case_id)
    try:
        items = AttachmentClient(context.tenant_id, context.trace_id).list(provider_case)
    except AttachmentError as error:
        _raise_provider(error, context)
    return {"items": [
        {**item, "case_id": case_id,
         "download_path": f"/api/workbench/cases/{case_id}/attachments/{item['attachment_id']}/content"}
        for item in items
    ], "readback_verified": True}


@router.post("/cases/{case_id}/attachments")
def upload_attachment(case_id: str, body: Upload, request: Request,
                      db: Session = Depends(get_db), context: RequestContext = Depends(_context)):
    if _identity(context).business_role == BusinessRole.AUDITOR:
        raise HTTPException(403, detail={"error": "ATTACHMENT_WRITE_FORBIDDEN"})
    provider_case = _case_reference(db, context, case_id)
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key:
        raise HTTPException(400, detail={"error": "IDEMPOTENCY_KEY_REQUIRED"})
    content, canonical = _input_content(body, context)
    digest = hashlib.sha256(content).hexdigest()
    name = f"attachment-{digest[:12]}.{MEDIA[body.content_type]}"
    try:
        saved = AttachmentClient(context.tenant_id, context.trace_id).create(
            provider_case, name, body.content_type, content,
            "att_" + hashlib.sha256(f"{context.tenant_id}:{context.actor_id}:{case_id}:{key}".encode()).hexdigest(),
            source_sha256=body.sha256,
            source_name_sha256=hashlib.sha256(body.file_name.encode("utf-8")).hexdigest(),
        )
    except AttachmentError as error:
        _raise_provider(error, context)
    return {**saved, "case_id": case_id, "readback_verified": True,
            "download_path": f"/api/workbench/cases/{case_id}/attachments/{saved['attachment_id']}/content",
            "processing_status": "canonical_text_available" if canonical else "stored_image_not_parsed",
            "canonical_text": canonical, "canonical_language": "en" if canonical else None}


@router.get("/cases/{case_id}/attachments/{attachment_id}/content")
def download_attachment(case_id: str, attachment_id: str, db: Session = Depends(get_db),
                        context: RequestContext = Depends(_context)):
    provider_case = _case_reference(db, context, case_id)
    try:
        metadata, content = AttachmentClient(context.tenant_id, context.trace_id).content(attachment_id, provider_case)
    except AttachmentError as error:
        _raise_provider(error, context)
    media = metadata.get("content_type")
    if media not in MEDIA:
        raise HTTPException(422, detail={"error": "ATTACHMENT_TYPE_INVALID"})
    return Response(content, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="attachment.{MEDIA[media]}"',
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
        "X-Content-SHA256": metadata["sha256"],
    })
