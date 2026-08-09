"""GPM Multi-Tenant HMAC Auth."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Optional

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


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
    tenant_id: str, db_client, *, fail_closed: bool = False
) -> bool:
    from aivan.gpm.giraffe_db_client import GiraffeDBClientError

    try:
        tenant = db_client.get_tenant(tenant_id)
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
    except GiraffeDBClientError as exc:
        if fail_closed:
            logger.error("giraffe-db unavailable for production tenant verification")
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "TENANT_VERIFICATION_UNAVAILABLE",
                    "message": "tenant verification is temporarily unavailable",
                },
            ) from exc
        logger.warning("giraffe-db unavailable — local HMAC-only compatibility mode")
        return True


def make_require_auth(db_client=None):
    async def require_auth(request: Request) -> str:
        production = _is_production()
        secret = os.environ.get("AIVAN_AUTH_SECRET", "")
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
            _verify_tenant_active(hmac_tenant, db_client, fail_closed=True)
            return hmac_tenant

        if production:
            from aivan.api.request_context import resolve_request_context

            context = resolve_request_context(request)
            _verify_tenant_active(context.tenant_id, db_client, fail_closed=True)
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
            _verify_tenant_active(tenant_id, db_client)
        else:
            logger.warning("No giraffe-db client — skipping tenant DB check for %s", tenant_id)
        return tenant_id

    return require_auth


async def require_auth(request: Request) -> str:
    """Reads db_client from app.state (set at startup) for per-request tenant verification."""
    db_client = getattr(request.app.state, "giraffe_db_client", None)
    auth_fn = make_require_auth(db_client=db_client)
    return await auth_fn(request)
