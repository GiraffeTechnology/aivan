"""Authenticated request context for every AIVAN business entry point.

The API key authenticates the caller, while the tenant is bound either to the
deployment (``AIVAN_TENANT_ID``) or to a tenant-specific key configured through
``AIVAN_TENANT_API_KEYS``.  Tenant and role values in request bodies are never
treated as trusted identity sources in production.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Request


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")


@dataclass(frozen=True)
class RequestContext:
    tenant_id: str
    trace_id: str
    idempotency_key: str
    actor_id: str
    role_context: str
    channel_account_id: str
    production: bool


def _header(request: Request, name: str) -> str:
    return request.headers.get(name, "").strip()


def _safe_identifier(value: str, *, field: str, required: bool = False) -> str:
    value = (value or "").strip()
    if not value:
        if required:
            raise HTTPException(
                status_code=400,
                detail={"error": f"{field.upper()}_REQUIRED", "field": field},
            )
        return ""
    if not _SAFE_ID.fullmatch(value):
        raise HTTPException(
            status_code=400,
            detail={"error": f"INVALID_{field.upper()}", "field": field},
        )
    return value


def _tenant_key_map() -> dict[str, str]:
    raw = os.environ.get("AIVAN_TENANT_API_KEYS", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "TENANT_AUTH_MISCONFIGURED", "message": str(exc)},
        ) from exc
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(value, str) and key.strip() and value.strip()
        for key, value in parsed.items()
    ):
        raise HTTPException(
            status_code=503,
            detail={"error": "TENANT_AUTH_MISCONFIGURED"},
        )
    return {key.strip(): value.strip() for key, value in parsed.items()}


def resolve_request_context(request: Request) -> RequestContext:
    """Authenticate the caller and resolve trusted tenant/trace identity."""

    environment = os.environ.get("AIVAN_ENV", "local").strip().lower()
    production = environment == "production"
    api_key = os.environ.get("AIVAN_API_KEY", "").strip()
    auth_secret = os.environ.get("AIVAN_AUTH_SECRET", "").strip()
    deployment_tenant = os.environ.get("AIVAN_TENANT_ID", "").strip()
    tenant_keys = _tenant_key_map()

    requested_tenant = _header(request, "X-AIVAN-Tenant-ID") or _header(
        request, "X-Tenant-ID"
    )
    if deployment_tenant and requested_tenant and requested_tenant != deployment_tenant:
        raise HTTPException(
            status_code=403,
            detail={"error": "TENANT_MISMATCH"},
        )
    tenant_id = requested_tenant or deployment_tenant

    configured = bool(api_key or auth_secret or tenant_keys)
    if production and not configured:
        raise HTTPException(
            status_code=503,
            detail={"error": "AUTH_MISCONFIGURED"},
        )
    if production and not tenant_keys and not deployment_tenant:
        raise HTTPException(
            status_code=503,
            detail={"error": "TENANT_AUTH_MISCONFIGURED"},
        )

    provided = _header(request, "X-AIVAN-API-Key")
    if not provided:
        authorization = _header(request, "Authorization")
        if authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()

    if configured:
        if not provided:
            raise HTTPException(
                status_code=401,
                detail={"error": "AUTH_REQUIRED", "message": "Missing X-AIVAN-API-Key header"},
            )
        if tenant_keys:
            if not tenant_id:
                raise HTTPException(
                    status_code=400,
                    detail={"error": "TENANT_REQUIRED", "field": "tenant_id"},
                )
            expected = tenant_keys.get(tenant_id, "")
            if not expected or not secrets.compare_digest(provided, expected):
                raise HTTPException(status_code=403, detail={"error": "INVALID_API_KEY"})
        elif not (
            (api_key and secrets.compare_digest(provided, api_key))
            or (auth_secret and secrets.compare_digest(provided, auth_secret))
        ):
            raise HTTPException(status_code=403, detail={"error": "INVALID_API_KEY"})

    if not tenant_id and not production and os.environ.get("AIVAN_TEST_MODE", "").lower() == "true":
        tenant_id = os.environ.get("AIVAN_TEST_TENANT_ID", "").strip()
    if not tenant_id and not production:
        # Existing local databases predate tenant columns and are backfilled to
        # this explicit compatibility scope by the Stage 1 migration.
        tenant_id = "legacy"
    tenant_id = _safe_identifier(tenant_id, field="tenant_id", required=True)

    trace_id = _safe_identifier(
        _header(request, "X-AIVAN-Trace-ID") or f"trace_{uuid.uuid4().hex}",
        field="trace_id",
        required=True,
    )
    idempotency_key = _safe_identifier(
        _header(request, "Idempotency-Key"), field="idempotency_key"
    )
    context = RequestContext(
        tenant_id=tenant_id,
        trace_id=trace_id,
        idempotency_key=idempotency_key,
        actor_id=_safe_identifier(_header(request, "X-AIVAN-Actor-ID"), field="actor_id"),
        role_context=_safe_identifier(
            _header(request, "X-AIVAN-Role-Context"), field="role_context"
        ),
        channel_account_id=_safe_identifier(
            _header(request, "X-AIVAN-Channel-Account-ID"), field="channel_account_id"
        ),
        production=production,
    )
    request.state.aivan_context = context
    return context


def apply_trusted_identity(event_data: dict, context: RequestContext) -> dict:
    """Attach trusted request identity and reject production body impersonation."""

    event = dict(event_data)
    body_tenant = str(event.pop("tenant_id", "") or "").strip()
    if body_tenant and body_tenant != context.tenant_id:
        raise HTTPException(status_code=403, detail={"error": "TENANT_MISMATCH"})

    body_role = str(event.get("role_context", "") or "").strip()
    if context.production and body_role and not context.role_context:
        raise HTTPException(status_code=403, detail={"error": "UNTRUSTED_ROLE_CONTEXT"})
    if context.role_context:
        event["role_context"] = context.role_context

    body_account = str(event.get("channel_account_id", "") or "").strip()
    if context.production and body_account and not context.channel_account_id:
        raise HTTPException(status_code=403, detail={"error": "UNTRUSTED_CHANNEL_ACCOUNT"})
    if context.channel_account_id:
        event["channel_account_id"] = context.channel_account_id
    if context.actor_id:
        event["actor_id"] = context.actor_id

    event["tenant_id"] = context.tenant_id
    event["source_trace_id"] = context.trace_id
    if context.idempotency_key:
        event["idempotency_key"] = context.idempotency_key
    return event
