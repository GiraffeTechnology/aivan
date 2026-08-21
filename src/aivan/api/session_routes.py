from __future__ import annotations

import os
import re
import time

from fastapi import APIRouter, Depends, Request, Response

from aivan.api.request_context import RequestContext, resolve_request_context
from aivan.api.session_auth import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    configured_ui_identity,
    issue_ui_session,
    read_ui_session,
)


router = APIRouter(prefix="/api/session", tags=["session"])
_SIGNED_SESSION_COOKIE = re.compile(r"^[A-Za-z0-9_-]{1,8192}\.[A-Za-z0-9_-]{43}$")
_CSRF_COOKIE_VALUE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


def _cookie_secure() -> bool:
    return os.environ.get("AIVAN_ENV", "local").strip().lower() == "production"


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
    requested_role = str((body or {}).get("role") or "")
    actor_id, allowed_roles, role = configured_ui_identity(requested_role)
    token, csrf_token, expires_at = issue_ui_session(
        tenant_id=context.tenant_id,
        actor_id=actor_id,
        role=role,
        allowed_roles=allowed_roles,
    )
    _set_session_cookie(response, token, csrf_token, expires_at)
    return {
        "actor_id": actor_id,
        "role": role,
        "allowed_roles": allowed_roles,
        "tenant_id": context.tenant_id,
        "csrf_token": csrf_token,
        "expires_at": expires_at,
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
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail={"error": "UI_SESSION_REQUIRED"})
    actor_id, allowed_roles, role = configured_ui_identity(str(body.get("role") or ""))
    if actor_id != context.actor_id or role not in session.allowed_roles:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail={"error": "ROLE_SWITCH_FORBIDDEN"})
    token, csrf_token, expires_at = issue_ui_session(
        tenant_id=context.tenant_id,
        actor_id=actor_id,
        role=role,
        allowed_roles=allowed_roles,
    )
    _set_session_cookie(response, token, csrf_token, expires_at)
    return {
        "actor_id": actor_id,
        "role": role,
        "allowed_roles": allowed_roles,
        "tenant_id": context.tenant_id,
        "csrf_token": csrf_token,
        "expires_at": expires_at,
    }


@router.post("/logout")
def logout(response: Response, _: RequestContext = Depends(_require_context)):
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", samesite="strict")
    return {"status": "logged_out"}
