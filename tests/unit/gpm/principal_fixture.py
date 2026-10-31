"""Explicit synthetic principals for router-only tests, not authentication evidence."""
from fastapi import HTTPException, Request
from aivan.gpm.auth import GPMDecisionAuthorizationError, GPMPrincipal, _safe_context_value


def principal_for_tenant(tenant_id):
    async def principal(request: Request):
        try:
            correlation_id = _safe_context_value(
                request.headers.get("X-AIVAN-Trace-ID", "") or "synthetic-router-fixture",
                code="GPM_INVALID_CORRELATION_ID", required=True,
            )
        except GPMDecisionAuthorizationError as exc:
            raise HTTPException(status_code=400, detail={"error": exc.code}) from exc
        return GPMPrincipal(
            tenant_id=tenant_id,
            actor_id=request.headers.get("X-AIVAN-Actor-ID", ""),
            role=request.headers.get("X-AIVAN-Role-Context", "") or request.headers.get("X-AIVAN-Role", ""),
            authorization_basis="tenant_api_key",
            idempotency_key=request.headers.get("Idempotency-Key", ""),
            correlation_id=correlation_id,
        )
    return principal

