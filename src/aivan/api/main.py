from __future__ import annotations
import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from aivan.db.session import get_db, init_db
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.platform_repo import PlatformRepository
from aivan.db.repositories.account_repo import AccountRepository
from aivan.gpm.router import router as _gpm_router
from aivan.api.authorization import authorize_draft_action as _authorize_draft_action
from aivan.api.relay_routes import router as _relay_router
from aivan.api.session_routes import router as _session_router
from aivan.api.security_headers import add_security_headers
from aivan.api.workbench_routes import router as _workbench_router
from aivan.api.serializers import (
    serialize_draft as _serialize_draft,
    serialize_preference as _serialize_preference,
)
from aivan.api.request_context import (
    RequestContext,
    actor_identity_from_context,
    apply_trusted_identity,
    resolve_request_context,
)
from aivan.observability.safe_logging import log_exception_safely
from aivan.observability.metrics import record_request_metrics, router as _metrics_router
from aivan.observability.readiness import router as _readiness_router

logger = logging.getLogger("aivan.api")


def _require_api_key(request: Request) -> RequestContext:
    """Authenticate and return the shared tenant/trace request context."""

    return resolve_request_context(request)

def _load_supplier_registry_on_startup() -> int:
    from aivan.db.session import db_session
    from aivan.sourcing.supplier_registry import load_from_db

    with db_session() as db:
        return load_from_db(db, tenant_id=None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Load persisted suppliers into the in-memory registry so RFQ supplier
    # routing has candidates on a fresh process. Fail-soft: a load error must
    # not prevent the app from starting.
    try:
        loaded_suppliers = _load_supplier_registry_on_startup()
        logger.info("Loaded %s suppliers into the in-memory registry", loaded_suppliers)
    except Exception as exc:
        log_exception_safely(
            logger,
            "Failed to load supplier registry from the local database",
            exc=exc,
        )
    from aivan.platforms.platform_registry import _ensure_init
    _ensure_init()
    from aivan.gpm.router import _init_store as _gpm_init_store, get_db_client
    _gpm_init_store()
    app.state.giraffe_db_client = get_db_client()
    yield

app = FastAPI(title="AIVAN - AI Trade Salesperson", version="0.3.0", lifespan=lifespan)


def _cors_origins() -> list[str]:
    """Return an explicit CORS allowlist; production defaults to no origins."""

    configured = os.environ.get("AIVAN_CORS_ORIGINS", "")
    origins = [value.strip() for value in configured.split(",") if value.strip()]
    if "*" in origins:
        raise RuntimeError("AIVAN_CORS_ORIGINS must not contain '*' ")
    if origins:
        return origins
    if os.environ.get("AIVAN_ENV", "local").strip().lower() == "production":
        return []
    return [
        "http://127.0.0.1:8765",
        "http://localhost:8765",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "X-AIVAN-API-Key",
        "X-AIVAN-CSRF",
        "X-AIVAN-Actor-ID",
        "X-AIVAN-Channel-Account-ID",
        "X-AIVAN-Conversation-Role",
        "X-AIVAN-Execution-Mode",
        "X-AIVAN-Participant-Conversation-Role",
        "X-AIVAN-Participant-ID",
        "X-AIVAN-Participant-Role",
        "X-AIVAN-Role-Context",
        "X-AIVAN-Tenant-ID",
        "X-AIVAN-Trace-ID",
    ],
)

app.include_router(_gpm_router, prefix="/api/gpm", tags=["gpm"])
app.include_router(_relay_router, tags=["relay"])
app.include_router(_session_router)
app.include_router(_workbench_router)
app.include_router(_metrics_router)
app.include_router(_readiness_router)


app.middleware("http")(add_security_headers)
app.middleware("http")(record_request_metrics)


# OpenClaw-facing skill routes: an exception here must fail soft, never raw 500.
SKILL_INVOKE_PATHS = frozenset(
    {
        "/invoke",
        "/api/openclaw/events",
        "/api/skill/invoke",
        "/api/rfq/create-from-event",
        "/api/relay/inbound",
    }
)

# WeChat-visible degraded reply when the backend pipeline fails. Must be
# human-readable and must never leak a traceback or raw exception text.
ERROR_REPLY_TEXT = "AIVAN 处理请求时遇到后端依赖错误，请稍后再试。"


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fail soft for OpenClaw skill routes; keep normal HTTP semantics elsewhere.

    OpenClaw treats an HTTP 500 from a skill as "skill broken" and disables it,
    whereas an HTTP 200 carrying {"status": "error"} is a recoverable
    "skill returned error" the WeChat user can see and retry. So an uncaught
    exception on a skill-invocation route is logged and converted to a 200 error
    envelope carrying both `output` and `reply_text` (the plugin sends
    `reply_text` to WeChat). Non-skill routes (dashboard/CRUD) keep standard 500
    semantics. Explicit HTTPException (401/403/404/409/...) is handled by
    FastAPI's own handler and keeps its status code.
    """
    log_exception_safely(
        logger,
        "Unhandled API exception",
        exc=exc,
        context={"method": request.method, "path": request.url.path},
    )
    if request.url.path not in SKILL_INVOKE_PATHS:
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
    return JSONResponse(
        status_code=200,
        content={
            "status": "error",
            "output": ERROR_REPLY_TEXT,
            "reply_text": ERROR_REPLY_TEXT,
        },
    )


def _first_non_empty(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _skill_response(result) -> dict:
    """Wrap an RFQ execution result in the OpenClaw skill envelope.

    The OpenClaw bridge plugin sends `reply_text` (not `output`) back to WeChat
    (integrations/openclaw-aivan-plugin/index.ts), so both fields must be present
    and non-empty or the user only ever sees the plugin's "已收到您的请求"
    fallback. `user_control_message` is the human-facing RFQ summary and is
    preferred over the terser internal `message`. Every existing top-level field
    (project_id, action, strategy, ...) is preserved so the plugin and existing
    callers keep working.
    """
    data = result.model_dump()
    reply_text = _first_non_empty(
        data.get("reply_text"),
        data.get("user_control_message"),
        data.get("message"),
        "已收到您的请求。",
    )
    return {**data, "status": "ok", "output": reply_text, "reply_text": reply_text}


def _run_skill_event(event_data: dict, db: Session) -> dict:
    """Single skill-execution entry point shared by every OpenClaw skill route.

    Parses the OpenClaw event and runs the RFQ pipeline, then wraps the result in
    the skill envelope. Kept as one function so /invoke, /api/openclaw/events,
    /api/skill/invoke and /api/rfq/create-from-event all run identical logic and a
    raised exception fails soft via the shared handler (these paths are in
    SKILL_INVOKE_PATHS).
    """
    from aivan.openclaw.event_adapter import parse_openclaw_event
    from aivan.execution.rfq_execution import create_rfq_from_event

    return _skill_response(create_rfq_from_event(parse_openclaw_event(event_data), db))


async def _run_skill_event_with_abort(event_data: dict, db: Session, request: Request) -> dict:
    """Run the skill pipeline with backend-side abort on client disconnect.

    This is the server's ``AbortController``: the synchronous RFQ pipeline runs
    in a worker thread carrying a :class:`CancelToken` via contextvars, while the
    event loop watches ``request.is_disconnected()``. If the frontend user
    interrupts the conversation or closes the page, the token is aborted and the
    Token Guard closes the in-flight Ollama stream so the model stops generating
    instead of finishing a request nobody is waiting for.
    """
    from aivan.llm.cancellation import CancelToken, set_cancel_token, reset_cancel_token

    token = CancelToken()
    reset = set_cancel_token(token)  # copied into the worker thread's context
    try:
        work = asyncio.create_task(asyncio.to_thread(_run_skill_event, event_data, db))
        watcher = asyncio.create_task(_watch_client_disconnect(request, token, work))
        try:
            return await work
        finally:
            watcher.cancel()
            try:
                await watcher
            except (asyncio.CancelledError, Exception):
                pass
    finally:
        reset_cancel_token(reset)


async def _watch_client_disconnect(request: Request, token, work: asyncio.Task) -> None:
    """Poll for client disconnect; abort the token so Ollama generation stops."""
    try:
        while not work.done():
            try:
                if await request.is_disconnected():
                    token.abort("client_disconnect")
                    return
            except Exception:
                # A receive-channel error is not itself a reason to abort work.
                return
            await asyncio.sleep(0.25)
    except asyncio.CancelledError:
        pass


def _normalize_invoke_payload(raw: dict) -> dict:
    """Normalize any supported /invoke body into a native OpenClaw event dict.

    Accepts three shapes and maps them onto the fields parse_openclaw_event reads,
    preserving project_id / role_context so follow-up supplier/buyer turns attach to
    the existing project instead of being misclassified as a new RFQ:
      - OpenClaw event   : {message_text, conversation_id, ...}  (native, passthrough)
      - OpenClaw standard: {session_id, user_input, context}
      - WeChat webhook   : {content, from_user, room_id, msg_type}
    """
    if not isinstance(raw, dict):
        raise ValueError("payload must be a JSON object")

    # Native OpenClaw event — already in the shape the adapter expects.
    if "message_text" in raw:
        return dict(raw)

    # OpenClaw standard skill invocation.
    if "user_input" in raw:
        context = raw.get("context")
        if not isinstance(context, dict):
            context = {}
        event = {
            "source": "openclaw",
            "channel": _first_non_empty(context.get("channel")) or "openclaw",
            "conversation_id": _first_non_empty(raw.get("session_id"), context.get("conversation_id"))
            or str(uuid.uuid4()),
            "sender_id": _first_non_empty(context.get("sender_id")) or "openclaw-user",
            "message_text": raw.get("user_input") or "",
            "message_type": "text",
            "mode": _first_non_empty(context.get("mode")) or "auto",
        }
        if _first_non_empty(context.get("project_id")):
            event["project_id"] = context["project_id"]
        if _first_non_empty(context.get("role_context")):
            event["role_context"] = context["role_context"]
        return event

    # WeChat webhook delivery.
    if "content" in raw:
        return {
            "source": "wechat",
            "channel": "wechat",
            "conversation_id": _first_non_empty(raw.get("room_id"), raw.get("from_user"))
            or str(uuid.uuid4()),
            "sender_id": _first_non_empty(raw.get("from_user")) or "wechat-user",
            "message_text": raw.get("content") or "",
            "message_type": _first_non_empty(raw.get("msg_type")) or "text",
            "mode": "auto",
        }

    raise ValueError(f"unrecognized payload keys: {sorted(raw.keys())}")


def _skill_error_response(message: str, reply_text: str, trace_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "status": "error",
            "error": {"code": "INVALID_INVOKE_PAYLOAD", "message": message},
            "output": message,
            "reply_text": reply_text,
            "artifacts": [],
            "trace_id": trace_id,
        },
    )


async def _invoke_application_service(
    request: Request,
    db: Session,
    context: RequestContext,
) -> dict | JSONResponse:
    """Single authenticated application service for all four invoke aliases."""

    try:
        raw = await request.json()
    except Exception:
        return _skill_error_response(
            "Invalid JSON body.", "Invalid JSON body.", context.trace_id
        )
    try:
        event_data = apply_trusted_identity(_normalize_invoke_payload(raw), context)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("invoke payload normalization failed: %s", exc)
        return _skill_error_response(
            "Unrecognized request format.",
            "Unable to recognize the request format. Check the message content.",
            context.trace_id,
        )

    result = await _run_skill_event_with_abort(event_data, db, request)
    if isinstance(result, dict):
        return {
            **result,
            "tenant_id": context.tenant_id,
            "trace_id": context.trace_id,
            "idempotency_key": context.idempotency_key or event_data.get("idempotency_key", ""),
        }
    return result

_templates_dir = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
_static_dir = os.path.join(os.path.dirname(__file__), "..", "app", "static")

templates = Jinja2Templates(directory=_templates_dir)

try:
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
except Exception:
    pass

@app.get("/health")
@app.get("/api/health")
@app.get("/healthz")
def health():
    return {"status": "ok", "product": "AIVAN", "version": "0.3.0"}

@app.get("/app", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def serve_app(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "AIVAN"},
    )


@app.post("/invoke")
async def invoke(
    request: Request,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    """OpenClaw / WeChat skill invocation endpoint.

    Registered directly on the root app (the real harness calls POST /invoke).
    Accepts OpenClaw-standard, WeChat-webhook, and native OpenClaw-event bodies,
    and is in SKILL_INVOKE_PATHS so it always fails soft: never 404, never 500.
    """
    return await _invoke_application_service(request, db, context)


@app.post("/api/openclaw/events")
async def openclaw_event(
    request: Request,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    return await _invoke_application_service(request, db, context)

@app.post("/api/skill/invoke")
async def skill_invoke(
    request: Request,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    return await _invoke_application_service(request, db, context)


@app.post("/api/rfq/create-from-event")
async def create_rfq_from_event_api(
    request: Request,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    return await _invoke_application_service(request, db, context)


def _do_approve_draft(
    draft_id: str, db: Session, context: RequestContext
) -> dict:
    from aivan.db.repositories.domain_repo import CaseDomainRepository
    from aivan.domain.roles import Capability

    repo = DraftRepository(db)
    draft = repo.get(draft_id, tenant_id=context.tenant_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    identity = actor_identity_from_context(context, default_mode="approval")
    _authorize_draft_action(
        draft=draft,
        identity=identity,
        capability=Capability.APPROVE_OUTBOUND,
        source_trace_id=context.trace_id,
        db=db,
    )
    if draft.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Draft {draft_id} cannot be approved: current status is '{draft.status}'",
        )
    from aivan.execution.channel_policy import DeliveryMode, get_channel_capability

    channel_capability = get_channel_capability(draft.channel)
    if channel_capability.delivery_mode == DeliveryMode.UNSUPPORTED:
        CaseDomainRepository(db).record_audit(
            tenant_id=draft.tenant_id,
            case_id=draft.project_id,
            event_type="DRAFT_APPROVAL_REJECTED_CHANNEL_UNSUPPORTED",
            identity=identity,
            source_trace_id=context.trace_id,
            before={"draft_id": draft.draft_id, "status": draft.status},
            rejection_reason=f"channel_{channel_capability.channel}_unsupported",
        )
        db.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "error": "CHANNEL_UNSUPPORTED",
                "channel": channel_capability.channel,
            },
        )
    if channel_capability.delivery_mode == DeliveryMode.GUIDED_RELAY:
        missing_binding = [
            field
            for field, value in (
                ("channel_account_id", draft.channel_account_id),
                ("conversation_id", draft.conversation_id),
                ("target_peer_id", draft.target_peer_id),
            )
            if not (value or "").strip()
        ]
        if missing_binding:
            CaseDomainRepository(db).record_audit(
                tenant_id=draft.tenant_id,
                case_id=draft.project_id,
                event_type="DRAFT_APPROVAL_REJECTED_RELAY_BINDING",
                identity=identity,
                source_trace_id=context.trace_id,
                before={"draft_id": draft.draft_id, "status": draft.status},
                rejection_reason="missing_" + "_and_".join(missing_binding),
            )
            db.commit()
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "RELAY_BINDING_INCOMPLETE",
                    "missing": missing_binding,
                },
            )
    approval = CaseDomainRepository(db).record_approval(
        tenant_id=draft.tenant_id,
        case_id=draft.project_id,
        draft_id=draft.draft_id,
        identity=identity,
        source_trace_id=context.trace_id,
        status="approved",
        requested_by_actor_id=draft.created_by_actor_id,
        requested_by_actor_role=draft.created_by_actor_role,
    )
    if channel_capability.delivery_mode == DeliveryMode.GUIDED_RELAY:
        repo.mark_approved_pending_send(draft_id, identity.actor_id)
        approved_status = "approved_pending_send"
    else:
        repo.approve(draft_id, identity.actor_id)
        approved_status = "approved"
    draft.approval_id = approval.approval_id
    draft.authorization_basis = identity.authorization_basis
    CaseDomainRepository(db).record_audit(
        tenant_id=draft.tenant_id,
        case_id=draft.project_id,
        event_type="DRAFT_APPROVED",
        identity=identity,
        source_trace_id=context.trace_id,
        before={"draft_id": draft.draft_id, "status": "pending_approval"},
        after={
            "draft_id": draft.draft_id,
            "status": approved_status,
            "delivery_mode": channel_capability.delivery_mode.value,
        },
    )
    project = ProjectRepository(db).get(
        draft.project_id, tenant_id=draft.tenant_id
    )
    if project is not None and project.case_state == "awaiting_approval":
        CaseDomainRepository(db).transition_case(
            project=project,
            after="approved",
            identity=identity,
            source_trace_id=context.trace_id,
        )
    if channel_capability.delivery_mode == DeliveryMode.GUIDED_RELAY:
        CaseDomainRepository(db).record_audit(
            tenant_id=draft.tenant_id,
            case_id=draft.project_id,
            event_type="RELAY_OUTBOX_QUEUED",
            identity=identity,
            source_trace_id=context.trace_id,
            before={"draft_id": draft.draft_id, "status": "pending_approval"},
            after={"draft_id": draft.draft_id, "status": approved_status},
        )
        db.commit()
        return {
            "draft_id": draft_id,
            "status": approved_status,
            "sent": False,
            "relay_required": True,
            "delivery_mode": channel_capability.delivery_mode.value,
            "error": None,
        }

    from aivan.openclaw.outbound_approval import send_if_approved
    response = send_if_approved(draft_id, db)
    final_draft = repo.get(draft_id, tenant_id=context.tenant_id)
    final_status = final_draft.status if final_draft is not None else "send_failed"
    CaseDomainRepository(db).record_audit(
        tenant_id=draft.tenant_id,
        case_id=draft.project_id,
        event_type="DRAFT_SENT" if response.success else "DRAFT_SEND_FAILED",
        identity=identity,
        source_trace_id=context.trace_id,
        before={"draft_id": draft.draft_id, "status": "approved"},
        after={"draft_id": draft.draft_id, "status": final_status},
        rejection_reason="" if response.success else "outbound_transport_failed",
    )
    db.commit()
    return {
        "draft_id": draft_id,
        "status": final_status,
        "sent": response.success,
        "relay_required": False,
        "delivery_mode": channel_capability.delivery_mode.value,
        "error": response.error,
    }


def _do_reject_draft(draft_id: str, db: Session, context: RequestContext) -> dict:
    from aivan.db.repositories.domain_repo import CaseDomainRepository
    from aivan.domain.roles import Capability

    repo = DraftRepository(db)
    draft = repo.get(draft_id, tenant_id=context.tenant_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    identity = actor_identity_from_context(context, default_mode="approval")
    _authorize_draft_action(
        draft=draft,
        identity=identity,
        capability=Capability.APPROVE_OUTBOUND,
        source_trace_id=context.trace_id,
        db=db,
    )
    if draft.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Draft {draft_id} cannot be rejected: current status is '{draft.status}'",
        )
    repo.reject(draft_id)
    CaseDomainRepository(db).record_approval(
        tenant_id=draft.tenant_id,
        case_id=draft.project_id,
        draft_id=draft.draft_id,
        identity=identity,
        source_trace_id=context.trace_id,
        status="rejected",
        requested_by_actor_id=draft.created_by_actor_id,
        requested_by_actor_role=draft.created_by_actor_role,
    )
    CaseDomainRepository(db).record_audit(
        tenant_id=draft.tenant_id,
        case_id=draft.project_id,
        event_type="DRAFT_REJECTED",
        identity=identity,
        source_trace_id=context.trace_id,
        before={"draft_id": draft.draft_id, "status": "pending_approval"},
        after={"draft_id": draft.draft_id, "status": "rejected"},
    )
    db.commit()
    return {"draft_id": draft_id, "status": "rejected"}


def _do_retry_draft(draft_id: str, db: Session, context: RequestContext) -> dict:
    from aivan.db.repositories.domain_repo import CaseDomainRepository
    from aivan.domain.roles import Capability

    repo = DraftRepository(db)
    draft = repo.get(draft_id, tenant_id=context.tenant_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "draft_id": draft_id},
        )
    identity = actor_identity_from_context(context, default_mode="approval")
    _authorize_draft_action(
        draft=draft,
        identity=identity,
        capability=Capability.SEND_OUTBOUND,
        source_trace_id=context.trace_id,
        db=db,
    )
    if draft.status != "send_failed":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "invalid_draft_state",
                "draft_id": draft_id,
                "status": draft.status,
                "required_status": "send_failed",
            },
        )
    from aivan.execution.approval_state import approve_and_send

    result = approve_and_send(draft_id, db, approved_by=identity.actor_id)
    CaseDomainRepository(db).record_audit(
        tenant_id=draft.tenant_id,
        case_id=draft.project_id,
        event_type="DRAFT_SEND_RETRIED",
        identity=identity,
        source_trace_id=context.trace_id,
        before={"draft_id": draft.draft_id, "status": "send_failed"},
        after={"draft_id": draft.draft_id, "status": result.status},
        rejection_reason=result.error or "",
    )
    db.commit()
    return {
        "draft_id": result.draft_id,
        "status": result.status,
        "sent": result.sent,
        "error": result.error,
        "message_id": result.message_id,
    }


@app.post("/api/openclaw/drafts/{draft_id}/approve")
def approve_draft(
    draft_id: str,
    body: dict = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    return _do_approve_draft(draft_id, db, context)


@app.post("/api/openclaw/drafts/{draft_id}/reject")
def reject_draft(
    draft_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    return _do_reject_draft(draft_id, db, context)


@app.get("/api/openclaw/drafts/{draft_id}")
def get_draft(
    draft_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    """Fetch a single draft by id.

    Returns 200 with the full draft (same shape as the ``drafts[]`` elements
    elsewhere in the API), or a structured JSON 404 when the draft is absent.
    """
    draft = DraftRepository(db).get(draft_id, tenant_id=context.tenant_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "draft_id": draft_id},
        )
    return _serialize_draft(draft)


# Short-form aliases used by the OpenClaw plugin and dashboard
@app.post("/api/drafts/{draft_id}/approve")
def approve_draft_alias(
    draft_id: str,
    body: dict = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    return _do_approve_draft(draft_id, db, context)


@app.post("/api/drafts/{draft_id}/reject")
def reject_draft_alias(
    draft_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    return _do_reject_draft(draft_id, db, context)


@app.get("/api/drafts/{draft_id}")
def get_draft_alias(
    draft_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    draft = DraftRepository(db).get(draft_id, tenant_id=context.tenant_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "draft_id": draft_id},
        )
    return _serialize_draft(draft)


@app.post("/api/drafts/{draft_id}/retry")
def retry_draft_alias(
    draft_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    return _do_retry_draft(draft_id, db, context)


@app.get("/api/drafts")
def list_all_drafts(
    project_id: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    repo = DraftRepository(db)
    if project_id:
        drafts = repo.list_pending(project_id, tenant_id=context.tenant_id)
    else:
        drafts = repo.list_all_pending(tenant_id=context.tenant_id)
    return {"drafts": [
        {
            "draft_id": d.draft_id,
            "project_id": d.project_id,
            "channel": d.channel,
            "target_role": d.target_role,
            "message_text": d.message_text[:200],
            "created_by_agent": d.created_by_agent,
            "status": d.status,
            "created_at": str(d.created_at),
        }
        for d in drafts
    ]}


@app.get("/api/channels/capabilities")
def get_channel_capability_registry(
    context: RequestContext = Depends(_require_api_key),
):
    from aivan.execution.channel_policy import list_channel_capabilities

    return {
        "tenant_id": context.tenant_id,
        "capabilities": list_channel_capabilities(),
    }


@app.get("/api/openclaw/projects/{project_id}/pending-drafts")
def get_pending_drafts(
    project_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    repo = DraftRepository(db)
    drafts = repo.list_pending(project_id, tenant_id=context.tenant_id)
    return {"project_id": project_id, "drafts": [
        {"draft_id": d.draft_id, "target_role": d.target_role, "message_text": d.message_text[:200], "created_by_agent": d.created_by_agent, "status": d.status}
        for d in drafts
    ]}

@app.get("/api/openclaw/projects/{project_id}/state")
def get_project_state(project_id: str, db: Session = Depends(get_db), context: RequestContext = Depends(_require_api_key)):
    repo = ProjectRepository(db)
    project = repo.get(project_id, tenant_id=context.tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    draft_repo = DraftRepository(db)
    pending = draft_repo.list_pending(project_id, tenant_id=context.tenant_id)
    return {
        "project_id": project_id,
        "status": project.status,
        "requirement": project.requirement_json,
        "pending_drafts": len(pending),
    }

@app.post("/api/suppliers/import")
def import_suppliers(body: dict, db: Session = Depends(get_db), context: RequestContext = Depends(_require_api_key)):
    csv_content = body.get("csv_content", "")
    if not csv_content:
        raise HTTPException(status_code=400, detail="csv_content required")
    from aivan.sourcing.supplier_importer import import_from_csv
    count, errors = import_from_csv(csv_content, db, tenant_id=context.tenant_id)
    db.commit()
    return {"imported": count, "errors": errors}

@app.get("/api/suppliers")
def list_suppliers(db: Session = Depends(get_db), context: RequestContext = Depends(_require_api_key)):
    from aivan.sourcing.supplier_registry import list_active
    suppliers = list_active(tenant_id=context.tenant_id)
    return {"suppliers": [s.model_dump() for s in suppliers], "total": len(suppliers)}

@app.post("/api/suppliers/match")
def match_suppliers(body: dict, db: Session = Depends(get_db), context: RequestContext = Depends(_require_api_key)):
    from aivan.schemas.requirement import BuyerRequirement
    from aivan.sourcing.supplier_matcher import match_suppliers_for_requirement
    req = BuyerRequirement(**body)
    matches = match_suppliers_for_requirement(req, limit=10, tenant_id=context.tenant_id)
    return {"matches": [{"supplier": m.supplier.model_dump(), "match_score": m.match_score, "match_reason": m.match_reason} for m in matches]}

@app.get("/api/platforms")
def list_platforms(context: RequestContext = Depends(_require_api_key)):
    from aivan.platforms.platform_registry import list_all_platforms
    platforms = list_all_platforms(tenant_id=context.tenant_id)
    return {"platforms": [p.model_dump() for p in platforms]}

@app.get("/api/platforms/whitelist")
def list_whitelist(context: RequestContext = Depends(_require_api_key)):
    from aivan.platforms.platform_registry import list_trusted_platforms
    platforms = list_trusted_platforms(tenant_id=context.tenant_id)
    return {"trusted_platforms": [p.model_dump() for p in platforms]}

@app.post("/api/platforms/whitelist")
def add_platform_to_whitelist(body: dict, db: Session = Depends(get_db), context: RequestContext = Depends(_require_api_key)):
    from aivan.platforms.models import TrustedPlatform
    from aivan.platforms.platform_registry import add_platform
    from aivan.utils.time_utils import utcnow_iso
    platform = TrustedPlatform(
        platform_id=body.get("platform_id", body.get("domain", "").replace(".", "_")),
        display_name=body.get("display_name", body.get("domain", "")),
        status="trusted",
        domain_patterns=[body.get("domain", "")] if body.get("domain") else body.get("domain_patterns", []),
        user_confirmed=True,
        created_at=utcnow_iso(),
        updated_at=utcnow_iso(),
    )
    add_platform(platform, tenant_id=context.tenant_id)
    return {"added": platform.model_dump()}

@app.get("/api/platforms/suggestions")
def list_platform_suggestions(context: RequestContext = Depends(_require_api_key)):
    from aivan.platforms.platform_registry import list_suggestions
    sugs = list_suggestions(tenant_id=context.tenant_id)
    return {"suggestions": [s.model_dump() for s in sugs]}

@app.post("/api/platforms/suggestions/{suggestion_id}/approve")
def approve_platform_suggestion(suggestion_id: str, context: RequestContext = Depends(_require_api_key)):
    from aivan.platforms.platform_registry import approve_suggestion
    sug = approve_suggestion(suggestion_id, tenant_id=context.tenant_id)
    if not sug:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return {"suggestion_id": suggestion_id, "status": "approved"}

@app.post("/api/platforms/suggestions/{suggestion_id}/reject")
def reject_platform_suggestion(suggestion_id: str, context: RequestContext = Depends(_require_api_key)):
    from aivan.platforms.platform_registry import reject_suggestion
    sug = reject_suggestion(suggestion_id, tenant_id=context.tenant_id)
    if not sug:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return {"suggestion_id": suggestion_id, "status": "rejected"}

@app.post("/api/platforms/suggestions/{suggestion_id}/block")
def block_platform_suggestion(suggestion_id: str, context: RequestContext = Depends(_require_api_key)):
    from aivan.platforms.platform_registry import block_suggestion
    sug = block_suggestion(suggestion_id, tenant_id=context.tenant_id)
    if not sug:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return {"suggestion_id": suggestion_id, "status": "blocked"}

@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db), context: RequestContext = Depends(_require_api_key)):
    repo = ProjectRepository(db)
    projects = repo.list_all(limit=50, tenant_id=context.tenant_id)
    return {"projects": [
        {"project_id": p.project_id, "status": p.status, "case_state": p.case_state, "category": p.category, "customer_id": p.customer_id, "created_at": str(p.created_at)}
        for p in projects
    ]}

@app.get("/api/projects/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db), context: RequestContext = Depends(_require_api_key)):
    repo = ProjectRepository(db)
    project = repo.get(project_id, tenant_id=context.tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "project_id": project.project_id,
        "status": project.status,
        "case_state": project.case_state,
        "category": project.category,
        "customer_id": project.customer_id,
        "requirement": project.requirement_json,
        "selected_option": project.selected_option_json,
        "created_at": str(project.created_at),
    }

@app.get("/api/projects/{project_id}/drafts")
def get_project_drafts(
    project_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    project = ProjectRepository(db).get(project_id, tenant_id=context.tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    drafts = DraftRepository(db).list_for_project(project_id, tenant_id=context.tenant_id)
    return {"project_id": project_id, "drafts": [_serialize_draft(d) for d in drafts]}


@app.post("/api/projects/{project_id}/strategy")
def update_project_strategy(
    project_id: str,
    body: dict,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    from aivan.schemas.rfq import RFQStrategy
    project_repo = ProjectRepository(db)
    project = project_repo.get(project_id, tenant_id=context.tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    identity = actor_identity_from_context(context, default_mode="command")
    _authorize_project_capability(
        project=project,
        identity=identity,
        capability_name="update_strategy",
        source_trace_id=context.trace_id,
        db=db,
    )
    try:
        strategy = RFQStrategy(**body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid strategy: {e}")
    requirement = dict(project.requirement_json or {})
    previous_strategy = requirement.get("strategy", {})
    requirement["strategy"] = strategy.model_dump()
    project_repo.update_requirement(project_id, requirement)
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    ExecutionEventRepository(db).append(
        project_id,
        "STRATEGY_UPDATED",
        f"Strategy updated to priority={strategy.priority}, scope={strategy.supplier_scope}",
        payload=strategy.model_dump(),
        actor="api",
        tenant_id=project.tenant_id,
        source_trace_id=context.trace_id,
        actor_id=identity.actor_id,
        actor_role=identity.business_role.value,
        conversation_role=identity.conversation_role.value,
        authorization_basis=identity.authorization_basis,
        before={"strategy": previous_strategy},
        after={"strategy": strategy.model_dump()},
    )
    db.commit()
    return {"project_id": project_id, "strategy": strategy.model_dump()}


@app.post("/api/projects/{project_id}/run-gltg")
def run_project_gltg(
    project_id: str,
    body: dict | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    from aivan.integrations.giraffe_db import GiraffeDBClient
    from aivan.integrations.gltg import GLTGClient
    from aivan.schemas.requirement import BuyerRequirement
    from aivan.schemas.rfq import RFQStrategy
    project_repo = ProjectRepository(db)
    project = project_repo.get(project_id, tenant_id=context.tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    identity = actor_identity_from_context(context, default_mode="command")
    _authorize_project_capability(
        project=project,
        identity=identity,
        capability_name="update_strategy",
        source_trace_id=context.trace_id,
        db=db,
    )
    payload = dict(project.requirement_json or {})
    try:
        requirement = BuyerRequirement(**{k: v for k, v in payload.items() if k in BuyerRequirement.model_fields})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Project requirement is not runnable by GLTG: {e}")
    strategy_payload = (body or {}).get("strategy") or payload.get("strategy") or {}
    try:
        strategy = RFQStrategy(**strategy_payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid strategy: {e}")
    giraffe = GiraffeDBClient(db, tenant_id=context.tenant_id).build_context(requirement, customer_id=project.customer_id)
    simulation = GLTGClient().simulate(requirement, strategy, supplier_count=len(giraffe.suppliers))
    payload["strategy"] = strategy.model_dump()
    payload["gltg_simulation"] = simulation.model_dump()
    project_repo.update_requirement(project_id, payload)
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    ExecutionEventRepository(db).append(
        project_id,
        "GLTG_SIMULATION_CREATED",
        f"{strategy.lead_time_confidence} lead time={simulation.selected_confidence_days} days",
        payload=simulation.model_dump(),
        actor="gltg",
        tenant_id=project.tenant_id,
        source_trace_id=context.trace_id,
        actor_id=identity.actor_id,
        actor_role=identity.business_role.value,
        conversation_role=identity.conversation_role.value,
        authorization_basis=identity.authorization_basis,
    )
    db.commit()
    return {"project_id": project_id, "gltg_simulation": simulation.model_dump()}


def _authorize_project_capability(
    *, project, identity, capability_name: str, source_trace_id: str, db: Session
) -> None:
    from aivan.db.repositories.domain_repo import CaseDomainRepository
    from aivan.domain.roles import Capability, RoleAuthorizationError, require_capability

    capability = Capability(capability_name)
    try:
        require_capability(identity, capability)
    except RoleAuthorizationError as exc:
        CaseDomainRepository(db).record_audit(
            tenant_id=project.tenant_id,
            case_id=project.project_id,
            event_type="PROJECT_ACTION_REJECTED",
            identity=identity,
            source_trace_id=source_trace_id,
            before={"case_state": project.case_state},
            rejection_reason=exc.reason,
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail={"error": exc.code, "reason": exc.reason},
        ) from exc


@app.post("/api/projects/{project_id}/transition")
def transition_project_case(
    project_id: str,
    body: dict,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    from aivan.db.repositories.domain_repo import CaseDomainRepository
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    from aivan.domain.roles import CaseState, RoleAuthorizationError

    project = ProjectRepository(db).get(project_id, tenant_id=context.tenant_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    identity = actor_identity_from_context(context, default_mode="update")
    requested_state = str((body or {}).get("case_state") or "").strip()
    try:
        after = CaseState(requested_state)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "INVALID_CASE_STATE", "case_state": requested_state},
        ) from exc
    before = project.case_state
    try:
        decision = CaseDomainRepository(db).transition_case(
            project=project,
            after=after,
            identity=identity,
            source_trace_id=context.trace_id,
        )
    except RoleAuthorizationError as exc:
        db.commit()
        raise HTTPException(
            status_code=403,
            detail={"error": exc.code, "reason": exc.reason},
        ) from exc
    ExecutionEventRepository(db).append(
        project.project_id,
        "CASE_STATE_TRANSITION",
        f"Case state changed from {decision.before.value} to {decision.after.value}",
        tenant_id=project.tenant_id,
        source_trace_id=context.trace_id,
        actor_id=identity.actor_id,
        actor_role=identity.business_role.value,
        conversation_role=identity.conversation_role.value,
        authorization_basis=identity.authorization_basis,
        before={"case_state": before},
        after={"case_state": project.case_state},
    )
    db.commit()
    return {
        "project_id": project.project_id,
        "before": decision.before.value,
        "after": decision.after.value,
        "actor_id": identity.actor_id,
        "actor_role": identity.business_role.value,
        "source_trace_id": context.trace_id,
        "authorization_basis": identity.authorization_basis,
    }


@app.post("/api/user-preferences/update")
def update_user_preferences(
    body: dict,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    from aivan.db.repositories.preference_repo import UserPreferenceRepository
    user_id = body.get("user_id")
    preference_type = body.get("preference_type")
    value = body.get("value")
    if not user_id or not preference_type or not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="user_id, preference_type, and object value are required")
    record = UserPreferenceRepository(db).upsert(
        user_id=user_id,
        preference_type=preference_type,
        value=value,
        source=body.get("source", "api"),
        confidence=float(body.get("confidence", 0.5)),
        tenant_id=context.tenant_id,
    )
    db.commit()
    return {"preference": _serialize_preference(record)}


@app.get("/api/user-preferences")
def get_user_preferences(
    user_id: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    from aivan.db.repositories.preference_repo import UserPreferenceRepository
    repo = UserPreferenceRepository(db)
    records = repo.list_for_user(user_id, tenant_id=context.tenant_id) if user_id else repo.list_all(tenant_id=context.tenant_id)
    return {"preferences": [_serialize_preference(record) for record in records]}


@app.get("/api/projects/{project_id}/events")
def get_project_events(project_id: str, db: Session = Depends(get_db), context: RequestContext = Depends(_require_api_key)):
    if ProjectRepository(db).get(project_id, tenant_id=context.tenant_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    repo = ExecutionEventRepository(db)
    events = repo.list_for_project(project_id, tenant_id=context.tenant_id)
    return {"project_id": project_id, "events": [
        {"event_id": e.event_id, "event_type": e.event_type, "summary": e.summary, "created_at": str(e.created_at)}
        for e in events
    ]}

def _authorize_event_capability(
    *, event, identity, capability, source_trace_id: str, db: Session
) -> None:
    from aivan.db.repositories.domain_repo import CaseDomainRepository
    from aivan.domain.roles import RoleAuthorizationError, require_capability

    try:
        require_capability(identity, capability)
    except RoleAuthorizationError as exc:
        CaseDomainRepository(db).record_audit(
            tenant_id=event.tenant_id,
            case_id=event.project_id,
            event_type="EVENT_CORRECTION_REJECTED",
            identity=identity,
            source_trace_id=source_trace_id,
            before={"event_id": event.event_id},
            rejection_reason=exc.reason,
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail={"error": exc.code, "reason": exc.reason},
        ) from exc


@app.get("/api/events/{event_id}/impact")
def get_event_impact(
    event_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    from aivan.domain.roles import Capability
    from aivan.execution.event_correction import build_event_impact

    event = ExecutionEventRepository(db).get(event_id, tenant_id=context.tenant_id)
    if event is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "event_id": event_id}
        )
    identity = actor_identity_from_context(context, default_mode="audit")
    _authorize_event_capability(
        event=event,
        identity=identity,
        capability=Capability.VIEW_AUDIT,
        source_trace_id=context.trace_id,
        db=db,
    )
    return build_event_impact(db, event, tenant_id=context.tenant_id)


@app.post("/api/events/{event_id}/reverse")
def reverse_execution_event(
    event_id: str,
    body: dict | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_require_api_key),
):
    from aivan.db.repositories.domain_repo import CaseDomainRepository
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    from aivan.domain.roles import Capability
    from aivan.execution.event_correction import (
        ReversalConflict,
        UnsafeAutomaticReversal,
        reverse_event,
        serialize_reversal_result,
    )

    event = ExecutionEventRepository(db).get(event_id, tenant_id=context.tenant_id)
    if event is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "event_id": event_id}
        )
    identity = actor_identity_from_context(context, default_mode="audit")
    _authorize_event_capability(
        event=event,
        identity=identity,
        capability=Capability.REVERSE_EVENT,
        source_trace_id=context.trace_id,
        db=db,
    )
    if not context.idempotency_key:
        raise HTTPException(
            status_code=400,
            detail={"error": "IDEMPOTENCY_KEY_REQUIRED", "header": "Idempotency-Key"},
        )
    payload = body or {}
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise HTTPException(
            status_code=400, detail={"error": "REVERSAL_REASON_REQUIRED"}
        )
    try:
        result = reverse_event(
            db,
            event,
            tenant_id=context.tenant_id,
            supplied_idempotency_key=context.idempotency_key,
            identity=identity,
            source_trace_id=context.trace_id,
            reason=reason,
            compensation_only=bool(payload.get("compensation_only", False)),
        )
    except UnsafeAutomaticReversal as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "AUTOMATIC_REVERSAL_UNSAFE", "impact": exc.impact},
        ) from exc
    except ReversalConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "REVERSAL_CONFLICT", "reason": str(exc)},
        ) from exc

    if not result.idempotent_replay:
        CaseDomainRepository(db).record_audit(
            tenant_id=context.tenant_id,
            case_id=event.project_id,
            event_type=(
                "EVENT_REVERSED"
                if result.record.status == "applied"
                else "EVENT_COMPENSATION_REQUIRED"
            ),
            identity=identity,
            source_trace_id=context.trace_id,
            before=event.after_json or {},
            after=(
                event.before_json or {}
                if result.record.status == "applied"
                else event.after_json or {}
            ),
        )
    db.commit()
    return serialize_reversal_result(result)

@app.get("/api/projects/{project_id}/options")
def get_project_options(project_id: str, db: Session = Depends(get_db), context: RequestContext = Depends(_require_api_key)):
    repo = ProjectRepository(db)
    project = repo.get(project_id, tenant_id=context.tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project_id": project_id, "selected_option": project.selected_option_json}

@app.post("/api/openclaw/accounts/register")
def register_account(body: dict, db: Session = Depends(get_db), context: RequestContext = Depends(_require_api_key)):
    from aivan.openclaw.account_delegation import register_account
    try:
        account = register_account(db, body, tenant_id=context.tenant_id)
        db.commit()
        return account.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/openclaw/accounts")
def list_accounts(db: Session = Depends(get_db), context: RequestContext = Depends(_require_api_key)):
    from aivan.openclaw.account_delegation import list_accounts
    accounts = list_accounts(db, tenant_id=context.tenant_id)
    return {"accounts": [a.model_dump() for a in accounts]}

@app.get("/api/openclaw/accounts/{account_connection_id}")
def get_account(account_connection_id: str, db: Session = Depends(get_db), context: RequestContext = Depends(_require_api_key)):
    from aivan.db.repositories.account_repo import AccountRepository
    repo = AccountRepository(db)
    account = repo.get(account_connection_id, tenant_id=context.tenant_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"account_connection_id": account.account_connection_id, "platform": account.platform, "status": account.status, "permissions": account.permissions_json}

@app.post("/api/openclaw/accounts/{account_connection_id}/revoke")
def revoke_account(account_connection_id: str, db: Session = Depends(get_db), context: RequestContext = Depends(_require_api_key)):
    from aivan.openclaw.account_delegation import revoke_account
    revoked = revoke_account(db, account_connection_id, tenant_id=context.tenant_id)
    db.commit()
    return {"account_connection_id": account_connection_id, "revoked": revoked}

@app.get("/api/openclaw/accounts/{account_connection_id}/permissions")
def get_account_permissions(account_connection_id: str, db: Session = Depends(get_db), context: RequestContext = Depends(_require_api_key)):
    from aivan.db.repositories.account_repo import AccountRepository
    repo = AccountRepository(db)
    account = repo.get(account_connection_id, tenant_id=context.tenant_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"account_connection_id": account_connection_id, "permissions": account.permissions_json, "allowed_actions": account.allowed_actions_json}
