from __future__ import annotations

import os
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from aivan.api.request_context import (
    RequestContext,
    configured_tenant_ids,
    resolve_request_context,
)
from aivan.api.session_auth import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    configured_ui_identity,
    consume_test_login_ticket,
    issue_ui_session,
    read_ui_session,
    test_session_ttl_seconds,
    validate_test_ticket_configuration,
)
from aivan.db.models import (
    ApprovalRecord,
    AuditLogRecord,
    CaseConversationRecord,
    CaseMessageRecord,
    CaseParticipantRecord,
    ExecutionEventRecord,
    InquiryDraftRecord,
    Project,
    RelayReceiptRecord,
)
from aivan.db.session import get_db


router = APIRouter(prefix="/api/session", tags=["session"])
_SIGNED_SESSION_COOKIE = re.compile(r"^[A-Za-z0-9_-]{1,8192}\.[A-Za-z0-9_-]{43}$")
_CSRF_COOKIE_VALUE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


def _cookie_secure() -> bool:
    return os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"


def _configured_ui_tenant() -> str:
    tenant_id = os.environ.get("AIVAN_TENANT_ID", "").strip()
    if tenant_id:
        return tenant_id
    if _cookie_secure():
        raise HTTPException(
            status_code=503,
            detail={"error": "UI_TENANT_MISCONFIGURED"},
        )
    return "legacy"


def _test_account_enabled() -> bool:
    return os.environ.get("AIVAN_UI_TEST_ACCOUNT_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _configured_test_identity() -> tuple[str, str, tuple[str, ...], str]:
    if not _test_account_enabled():
        raise HTTPException(status_code=404, detail={"error": "TEST_ACCOUNT_DISABLED"})
    tenant_id = os.environ.get("AIVAN_UI_TEST_TENANT_ID", "").strip()
    actor_id = os.environ.get("AIVAN_UI_TEST_ACTOR_ID", "").strip()
    roles = tuple(
        item.strip().lower()
        for item in os.environ.get("AIVAN_UI_TEST_ALLOWED_ROLES", "auditor").split(",")
        if item.strip()
    )
    default_role = os.environ.get("AIVAN_UI_TEST_DEFAULT_ROLE", "auditor").strip().lower()
    if (
        not tenant_id
        or tenant_id in configured_tenant_ids()
        or not actor_id
        or roles != ("auditor",)
        or default_role != "auditor"
    ):
        raise HTTPException(
            status_code=503,
            detail={"error": "TEST_ACCOUNT_MISCONFIGURED"},
        )
    try:
        validate_test_ticket_configuration()
    except ValueError as exc:
        raise HTTPException(
            status_code=503, detail={"error": "TEST_ACCOUNT_MISCONFIGURED"}
        ) from exc
    return tenant_id, actor_id, roles, default_role


def _set_session_cookie(response: Response, token: str, csrf_token: str, expires_at: int) -> None:
    if not _SIGNED_SESSION_COOKIE.fullmatch(token):
        raise RuntimeError("refusing to set an invalid signed session cookie")
    if not _CSRF_COOKIE_VALUE.fullmatch(csrf_token):
        raise RuntimeError("refusing to set an invalid CSRF cookie")
    max_age = max(0, int(expires_at - time.time()))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )


@router.post("/login")
def login(request: Request, response: Response, body: dict | None = None):
    """Exchange the deployment credential for a short-lived HttpOnly UI session."""

    context = resolve_request_context(request, allow_ui_session=False)
    tenant_id = _configured_ui_tenant()
    if context.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail={"error": "TENANT_MISMATCH"})
    requested_role = str((body or {}).get("role") or "")
    actor_id, allowed_roles, role = configured_ui_identity(requested_role)
    token, csrf_token, expires_at = issue_ui_session(
        tenant_id=tenant_id,
        actor_id=actor_id,
        role=role,
        allowed_roles=allowed_roles,
    )
    _set_session_cookie(response, token, csrf_token, expires_at)
    return {
        "actor_id": actor_id,
        "role": role,
        "allowed_roles": allowed_roles,
        "tenant_id": tenant_id,
        "csrf_token": csrf_token,
        "expires_at": expires_at,
        "test_account": False,
    }


@router.post("/test-login")
def test_login(
    response: Response,
    body: dict | None = None,
    db: Session = Depends(get_db),
):
    """Issue an isolated test session without the ordinary login ceremony."""

    tenant_id, actor_id, allowed_roles, role = _configured_test_identity()
    tenant_models = (
        Project,
        InquiryDraftRecord,
        RelayReceiptRecord,
        ExecutionEventRecord,
        CaseConversationRecord,
        CaseParticipantRecord,
        CaseMessageRecord,
        ApprovalRecord,
        AuditLogRecord,
    )
    if any(
        db.query(model).filter(model.tenant_id == tenant_id).first() is not None
        for model in tenant_models
    ):
        raise HTTPException(status_code=503, detail={"error": "TEST_TENANT_NOT_EMPTY"})
    ticket = str((body or {}).get("ticket") or "").strip()
    try:
        ticket_digest = consume_test_login_ticket(ticket)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail={"error": "INVALID_TEST_ACCESS"}) from exc
    token, csrf_token, expires_at = issue_ui_session(
        tenant_id=tenant_id,
        actor_id=actor_id,
        role=role,
        allowed_roles=allowed_roles,
        test_account=True,
        ttl_seconds=test_session_ttl_seconds(),
        authorization_reference=ticket_digest,
    )
    _set_session_cookie(response, token, csrf_token, expires_at)
    return {
        "actor_id": actor_id,
        "role": role,
        "allowed_roles": allowed_roles,
        "tenant_id": tenant_id,
        "csrf_token": csrf_token,
        "expires_at": expires_at,
        "test_account": True,
        "ticket_digest": ticket_digest,
    }


def _require_context(request: Request) -> RequestContext:
    return resolve_request_context(request)


@router.get("")
def current_session(request: Request, context: RequestContext = Depends(_require_context)):
    session = read_ui_session(request)
    return {
        "actor_id": context.actor_id,
        "role": context.role_context,
        "tenant_id": context.tenant_id,
        "authorization_basis": context.authorization_basis,
        "allowed_roles": session.allowed_roles if session else (context.role_context,),
        "test_account": bool(session and session.test_account),
        "authorization_reference": session.authorization_reference if session else "",
    }


@router.post("/role")
def switch_role(
    request: Request,
    response: Response,
    body: dict,
    context: RequestContext = Depends(_require_context),
):
    session = read_ui_session(request)
    if session is None:
        raise HTTPException(status_code=403, detail={"error": "UI_SESSION_REQUIRED"})
    if session.test_account:
        raise HTTPException(status_code=403, detail={"error": "TEST_ACCOUNT_ROLE_FIXED"})
    actor_id, allowed_roles, role = configured_ui_identity(str(body.get("role") or ""))
    if actor_id != context.actor_id or role not in session.allowed_roles:
        raise HTTPException(status_code=403, detail={"error": "ROLE_SWITCH_FORBIDDEN"})
    tenant_id = _configured_ui_tenant()
    if tenant_id != session.tenant_id or tenant_id != context.tenant_id:
        raise HTTPException(status_code=403, detail={"error": "TENANT_MISMATCH"})
    token, csrf_token, expires_at = issue_ui_session(
        tenant_id=tenant_id,
        actor_id=actor_id,
        role=role,
        allowed_roles=allowed_roles,
    )
    _set_session_cookie(response, token, csrf_token, expires_at)
    return {
        "actor_id": actor_id,
        "role": role,
        "allowed_roles": allowed_roles,
        "tenant_id": tenant_id,
        "csrf_token": csrf_token,
        "expires_at": expires_at,
        "test_account": False,
    }


@router.post("/logout")
def logout(response: Response, _: RequestContext = Depends(_require_context)):
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", samesite="strict")
    return {"status": "logged_out"}
