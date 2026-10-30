"""Resolve explicit saved TXT sources through the owning tenant data API."""
from __future__ import annotations

import hashlib
import json

from aivan.execution.attachment_reference import attachment_provider_case
from fastapi import HTTPException

from aivan.api.request_context import RequestContext, actor_identity_from_context
from aivan.domain.roles import Capability, RoleAuthorizationError, require_capability
from aivan.integrations.attachment_client import AttachmentClient, AttachmentError

SOURCE_KIND = "private_db_attachment"
RECEIPT_FIELD = "_saved_attachment_request_sha256"


def _fail(status, code, event):
    raise HTTPException(status, detail={"error": code, "trace_id": event.source_trace_id})


def authorize_saved_attachment(event, db):
    # The verified marker is server-owned; the old generic list cannot assert it.
    if any(item.get("source_type") == SOURCE_KIND for item in event.attachments):
        _fail(422, "ATTACHMENT_SOURCE_MARKER_RESERVED", event)
    if event.saved_attachment_source is None:
        return None
    if (not event.tenant_id or not event.project_id or not event.authenticated_actor_id
            or not event.authenticated_actor_role or not event.authorization_basis):
        _fail(403, "ATTACHMENT_SOURCE_TRUSTED_CONTEXT_REQUIRED", event)
    context = RequestContext(
        tenant_id=event.tenant_id, trace_id=event.source_trace_id,
        idempotency_key=event.idempotency_key, actor_id=event.authenticated_actor_id,
        role_context=event.authenticated_actor_role, conversation_role="",
        execution_mode=event.execution_mode, channel_account_id=event.channel_account_id,
        participant_actor_id=event.actor_id or event.sender_id,
        participant_role_context=event.business_role,
        participant_conversation_role=event.conversation_role,
        authorization_basis=event.authorization_basis, production=True,
    )
    try:
        require_capability(actor_identity_from_context(context), Capability.CREATE_INQUIRY)
    except RoleAuthorizationError:
        _fail(403, "ATTACHMENT_SOURCE_USE_FORBIDDEN", event)
    # Reuse the current workbench's actor/tenant/case access policy, including
    # active membership for external participants; no provider read precedes it.
    from aivan.api.workbench_routes import _get_case
    return _get_case(db, context, event.project_id)


def source_request_fingerprint(event):
    source = event.saved_attachment_source
    if source is None:
        return None
    identity = {name: getattr(event, name) for name in (
        "tenant_id", "project_id", "source", "channel", "channel_account_id",
        "conversation_id", "sender_id", "actor_id", "authenticated_actor_id",
        "authenticated_actor_role", "business_role", "conversation_role", "execution_mode",
    )}
    identity["saved_attachment_source"] = source.model_dump()
    identity["message_sha256"] = hashlib.sha256(event.message_text.encode("utf-8")).hexdigest()
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def validate_source_replay(receipt, fingerprint, event):
    previous = (receipt.result_json or {}).get(RECEIPT_FIELD)
    if previous != fingerprint:
        _fail(409, "ATTACHMENT_SOURCE_REQUEST_CONFLICT", event)


def resolve_saved_attachment(event, project):
    source = event.saved_attachment_source
    if source is None:
        return event
    provider_case = attachment_provider_case(project)
    if not isinstance(provider_case, str) or not provider_case:
        _fail(409, "ATTACHMENT_PERSISTED_CASE_REQUIRED", event)
    try:
        client = AttachmentClient(event.tenant_id, event.source_trace_id)
        metadata = client.metadata(source.attachment_id, provider_case)
        if metadata.get("sha256") != source.sha256:
            _fail(409, "ATTACHMENT_SOURCE_CHANGED", event)
        size = metadata.get("size_bytes")
        if (metadata.get("content_type") != "text/plain" or type(size) is not int
                or not 0 < size <= 64 * 1024):
            _fail(422, "ATTACHMENT_SOURCE_TEXT_REQUIRED", event)
        current, content = client.content(source.attachment_id, provider_case)
    except AttachmentError as exc:
        _fail(exc.status, exc.code, event)
    if (current.get("sha256") != source.sha256 or current.get("content_type") != "text/plain"
            or len(content) > 64 * 1024 or hashlib.sha256(content).hexdigest() != source.sha256):
        _fail(409, "ATTACHMENT_SOURCE_CHANGED", event)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        _fail(422, "ATTACHMENT_SOURCE_UTF8_REQUIRED", event)
    if not text.strip() or "\x00" in text:
        _fail(422, "ATTACHMENT_SOURCE_TEXT_INVALID", event)
    reference = {
        "source_type": SOURCE_KIND, "attachment_id": source.attachment_id,
        "sha256": source.sha256, "procurement_case_id": provider_case,
        "content_type": "text/plain", "size_bytes": len(content),
        "verification": "provider_content_readback",
    }
    message = f"User instructions:\n{event.message_text}\n\nSaved attachment content:\n{text}"
    return event.model_copy(update={
        "message_text": message, "attachments": [*event.attachments, reference],
    })
