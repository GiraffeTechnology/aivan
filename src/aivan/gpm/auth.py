"""GPM Multi-Tenant HMAC Auth."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

_SAFE_CONTEXT_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")


@dataclass(frozen=True)
class GPMPrincipal:
    """Tenant and operator facts resolved only from authenticated context."""

    tenant_id: str
    actor_id: str
    role: str
    authorization_basis: str
    idempotency_key: str
    correlation_id: str


class GPMDecisionAuthorizationError(PermissionError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _safe_context_value(value: str, *, code: str, required: bool = False) -> str:
    normalized = (value or "").strip()
    if not normalized:
        if required:
            raise GPMDecisionAuthorizationError(code)
        return ""
    if not _SAFE_CONTEXT_VALUE.fullmatch(normalized):
        raise GPMDecisionAuthorizationError(code)
    return normalized


def authorize_gpm_decision(principal: GPMPrincipal):
    """Require an authenticated actor with the canonical approval capability."""

    from aivan.domain.roles import (
        Capability,
        RoleAuthorizationError,
        normalize_actor_identity,
        require_capability,
    )

    actor_id = _safe_context_value(
        principal.actor_id, code="GPM_OPERATOR_ID_REQUIRED", required=True
    )
    role = _safe_context_value(
        principal.role, code="GPM_OPERATOR_ROLE_REQUIRED", required=True
    )
    _safe_context_value(
        principal.idempotency_key,
        code="GPM_IDEMPOTENCY_KEY_REQUIRED",
        required=True,
    )
    try:
        identity = normalize_actor_identity(
            actor_id=actor_id,
            business_role=role,
            execution_mode="approval",
            authorization_basis=principal.authorization_basis,
        )
        require_capability(identity, Capability.APPROVE_OUTBOUND)
    except RoleAuthorizationError as exc:
        raise GPMDecisionAuthorizationError(exc.code) from exc
    return identity


def generate_token(tenant_id: str, secret: str) -> str:
    sig = hmac.new(secret.encode(), tenant_id.encode(), hashlib.sha256).hexdigest()
    return f"{tenant_id}:{sig}"


def _verify_hmac(token: str, secret: str) -> Optional[str]:
    try:
        tenant_id, provided_sig = token.split(":", 1)
        if not tenant_id:
            return None
        expected_sig = hmac.new(
            secret.encode(), tenant_id.encode(), hashlib.sha256
        ).hexdigest()
        if hmac.compare_digest(provided_sig, expected_sig):
            return tenant_id
        return None
    except Exception:
        return None


def _is_production() -> bool:
    return os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"


def _verify_tenant_active(
    tenant_id: str,
    db_client,
    *,
    fail_closed: bool = True,
    correlation_id: str = "gpm-tenant-check",
) -> bool:
    from aivan.gpm.persistence_contract import PersistenceContractError

    try:
        tenant = db_client.get_tenant(tenant_id, correlation_id=correlation_id)
        if tenant is None:
            raise HTTPException(
                status_code=401,
                detail={"error": "unauthorized", "message": "tenant not found"},
            )
        status = tenant.get("status", "active")
        if status not in ("active", "enabled"):
            raise HTTPException(
                status_code=403,
                detail={"error": "tenant_inactive", "message": f"tenant {tenant_id} is {status}"},
            )
        logger.debug("Tenant %s verified active", tenant_id)
        return True
    except HTTPException:
        raise
    except PersistenceContractError as exc:
        if fail_closed:
            logger.error("giraffe-db unavailable for production tenant verification")
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "TENANT_VERIFICATION_UNAVAILABLE",
                    "message": "tenant verification is temporarily unavailable",
                    "correlation_id": exc.correlation_id,
                },
            ) from exc
        logger.warning("giraffe-db unavailable — local HMAC-only compatibility mode")
        return True


def make_require_auth(db_client=None):
    async def require_auth(request: Request) -> str:
        production = _is_production()
        secret = os.environ.get("AIVAN_AUTH_SECRET", "")
        try:
            request_correlation_id = _safe_context_value(
                request.headers.get("X-AIVAN-Trace-ID", "")
                or f"trace_{uuid.uuid4().hex}",
                code="GPM_INVALID_CORRELATION_ID",
                required=True,
            )
        except GPMDecisionAuthorizationError as exc:
            raise HTTPException(status_code=400, detail={"error": exc.code}) from exc
        if production and db_client is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "GPM_PERSISTENCE_MISCONFIGURED",
                    "message": "production GPM requires giraffe-db",
                },
            )

        # Production accepts the shared AIVAN request-context profiles
        # (deployment API key or tenant-key map).  HMAC remains a supported GPM
        # profile, but only with a live tenant lookup and an optional deployment
        # tenant binding.  A caller-supplied X-Tenant-ID is never trusted by
        # itself in production.
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
        hmac_tenant = _verify_hmac(token, secret) if production and secret and token else None
        if production and hmac_tenant is not None:
            deployment_tenant = os.environ.get("AIVAN_TENANT_ID", "").strip()
            requested_tenant = (
                request.headers.get("X-AIVAN-Tenant-ID", "").strip()
                or request.headers.get("X-Tenant-ID", "").strip()
            )
            if deployment_tenant and hmac_tenant != deployment_tenant:
                raise HTTPException(status_code=403, detail={"error": "TENANT_MISMATCH"})
            if requested_tenant and requested_tenant != hmac_tenant:
                raise HTTPException(status_code=403, detail={"error": "TENANT_MISMATCH"})
            _verify_tenant_active(
                hmac_tenant,
                db_client,
                fail_closed=True,
                correlation_id=request_correlation_id,
            )
            return hmac_tenant

        if production:
            from aivan.api.request_context import resolve_request_context

            context = resolve_request_context(request)
            _verify_tenant_active(
                context.tenant_id,
                db_client,
                fail_closed=True,
                correlation_id=context.trace_id,
            )
            return context.tenant_id

        if not secret:
            tenant_id = request.headers.get("X-Tenant-ID", "default")
            logger.warning("AIVAN_AUTH_SECRET not set — dev mode, tenant_id=%s", tenant_id)
            return tenant_id
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "unauthorized",
                    "message": "Missing Authorization header. Use: Bearer {tenant_id}:{signature}",
                },
            )
        token = auth_header.removeprefix("Bearer ").strip()
        tenant_id = _verify_hmac(token, secret)
        if tenant_id is None:
            raise HTTPException(
                status_code=401,
                detail={"error": "unauthorized", "message": "Invalid token signature"},
            )
        if db_client is not None:
            _verify_tenant_active(
                tenant_id,
                db_client,
                correlation_id=request_correlation_id,
            )
        else:
            logger.warning("No giraffe-db client — skipping tenant DB check for %s", tenant_id)
        return tenant_id

    return require_auth


async def require_auth(request: Request) -> str:
    """Reads db_client from app.state (set at startup) for per-request tenant verification."""
    db_client = getattr(request.app.state, "giraffe_db_client", None)
    auth_fn = make_require_auth(db_client=db_client)
    return await auth_fn(request)


async def require_principal(request: Request) -> GPMPrincipal:
    """Resolve GPM principal without trusting request bodies for identity."""

    tenant_id = await require_auth(request)
    context = getattr(request.state, "aivan_context", None)
    if context is not None:
        actor_id = context.actor_id
        role = context.role_context
        idempotency_key = context.idempotency_key
        correlation_id = context.trace_id
        authorization_basis = context.authorization_basis
    else:
        actor_id = request.headers.get("X-AIVAN-Actor-ID", "")
        role = request.headers.get("X-AIVAN-Role-Context", "")
        idempotency_key = request.headers.get("Idempotency-Key", "")
        correlation_id = request.headers.get("X-AIVAN-Trace-ID", "")
        authorization_basis = (
            "hmac" if os.environ.get("AIVAN_AUTH_SECRET", "").strip()
            else "local_compatibility"
        )
    correlation_id = _safe_context_value(
        correlation_id or f"trace_{uuid.uuid4().hex}",
        code="GPM_INVALID_CORRELATION_ID",
        required=True,
    )
    return GPMPrincipal(
        tenant_id=tenant_id,
        actor_id=_safe_context_value(actor_id, code="GPM_INVALID_OPERATOR_ID"),
        role=_safe_context_value(role, code="GPM_INVALID_OPERATOR_ROLE"),
        authorization_basis=authorization_basis,
        idempotency_key=_safe_context_value(
            idempotency_key, code="GPM_INVALID_IDEMPOTENCY_KEY"
        ),
        correlation_id=correlation_id,
    )
