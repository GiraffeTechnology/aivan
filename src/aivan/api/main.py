from __future__ import annotations
import asyncio
import logging
import os
import traceback
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
from aivan.api.request_context import (
    RequestContext,
    actor_identity_from_context,
    apply_trusted_identity,
    resolve_request_context,
)

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
    except Exception:
        logger.exception("Failed to load supplier registry from the local database")
    from aivan.platforms.platform_registry import _ensure_init
    _ensure_init()
    from aivan.gpm.router import _init_store as _gpm_init_store, get_db_client
    _gpm_init_store()
    app.state.giraffe_db_client = get_db_client()
    yield

app = FastAPI(title="AIVAN - AI Trade Salesperson", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(_gpm_router, prefix="/api/gpm", tags=["gpm"])


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
ERROR_REPLY_TEXT = "AIVAN å¤„ç†è¯·æ±‚æ—¶é‡åˆ°åŽç«¯ä¾èµ–é”™è¯¯ï¼Œè¯·ç¨åŽå†è¯•ã€‚"


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
    logger.error(
        "Unhandled exception on %s %s: %s: %s\n%s",
        request.method,
        request.url.path,
        type(exc).__name__,
        exc,
        traceback.format_exc(),
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
    and non-empty or the user only ever sees the plugin's "å·²æ”¶åˆ°æ‚¨çš„è¯·æ±‚"
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
        "å·²æ”¶åˆ°æ‚¨çš„è¯·æ±‚ã€‚",
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

    # Native OpenClaw event â€” already in the shape the adapter expects.
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
    return templates.TemplateResponse("index.html", {"request": request, "title": "AIVAN"})


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


def _authorize_draft_action(
    *, draft, identity, capability, source_trace_id: str, db: Session
) -> None:
    from aivan.db.repositories.domain_repo import CaseDomainRepository
    from aivan.domain.roles import RoleAuthorizationError, require_capability

    try:
        require_capability(identity, capability)
    except RoleAuthorizationError as exc:
        domain_repo = CaseDomainRepository(db)
        domain_repo.record_approval(
            tenant_id=draft.tenant_id,
            case_id=draft.project_id,
            draft_id=draft.draft_id,
            identity=identity,
            source_trace_id=source_trace_id,
            status="authorization×m|ÞÚ$z{-®éÜj×’æ'W6–æW75÷&öÆRçfÇVRÀÐ¢6öçfW'6F–öå÷&öÆSÖ–FVçF—G’æ6öçfW'6F–öå÷&öÆRçfÇVRÀÐ¢WF†÷&—¦F–öåö&6—3Ö–FVçF—G’æWF†÷&—¦F–öåö&6—2ÀÐ¢Ð¢F"æ6öÖÖ—B‚Ð¢&WGW&â²'&ö¦V7Eö–B#¢&ö¦V7Eö–BÂ&vÇFu÷6–×VÆF–öâ#¢6–×VÆF–öâæÖöFVÅöGV×‚—ÐÐ Ð Ð¦FVböWF†÷&—¦U÷&ö¦V7Eö6&–Æ—G’€Ð¢¢Â&ö¦V7BÂ–FVçF—G’Â6&–Æ—G•öæÖS¢7G"Â6÷W&6U÷G&6Uö–C¢7G"ÂF#¢6W76–öàÐ¢’ÓâæöæS Ð¢g&öÒ—fâæF"ç&W÷6—F÷&–W2æFöÖ–å÷&Wò–×÷'B66TFöÖ–å&W÷6—F÷'Ð¢g&öÒ—fâæFöÖ–âç&öÆW2–×÷'B6&–Æ—G’Â&öÆTWF†÷&—¦F–öäW'&÷"Â&WV—&Uö6&–Æ—GÐ Ð¢6&–Æ—G’Ò6&–Æ—G’†6&–Æ—G•öæÖRÐ¢G'“ Ð¢&WV—&Uö6&–Æ—G’†–FVçF—G’Â6&–Æ—G’Ð¢W†6WB&öÆTWF†÷&—¦F–öäW'&÷"2W†3 Ð¢66TFöÖ–å&W÷6—F÷'’†F"’ç&V6÷&EöVF—B€Ð¢FVæçEö–C×&ö¦V7BçFVæçEö–BÀÐ¢66Uö–C×&ö¦V7Bç&ö¦V7Eö–BÀÐ¢WfVçE÷G—SÒ%$ô¤T5Eô5D”ôåõ$T¤T5DTB"ÀÐ¢–FVçF—G“Ö–FVçF—G’ÀÐ¢6÷W&6U÷G&6Uö–C×6÷W&6U÷G&6Uö–BÀÐ¢&Vf÷&S×²&66U÷7FFR#¢&ö¦V7Bæ66U÷7FFWÒÀÐ¢&V¦V7F–öå÷&V6öãÖW†2ç&V6öâÀÐ¢Ð¢F"æ6öÖÖ—B‚Ð¢&—6R…EEW†6WF–öâ€Ð¢7FGW5ö6öFSÓC2ÀÐ¢FWF–Ã×²&W'&÷"#¢W†2æ6öFRÂ'&V6öâ#¢W†2ç&V6öçÒÀÐ¢’g&öÒW†0Ð Ð Ð¤ç÷7B‚"ö’÷&ö¦V7G2÷·&ö¦V7Eö–GÒ÷G&ç6—F–öâ"Ð¦FVbG&ç6—F–öå÷&ö¦V7Eö66R€Ð¢&ö¦V7Eö–C¢7G"ÀÐ¢&öG“¢F–7BÀÐ¢F#¢6W76–öâÒFWVæG2†vWEöF"’ÀÐ¢6öçFW‡C¢&WVW7D6öçFW‡BÒFWVæG2…÷&WV—&Uö•ö¶W’’ÀÐ¢“ Ð¢g&öÒ—fâæF"ç&W÷6—F÷&–W2æFöÖ–å÷&Wò–×÷'B66TFöÖ–å&W÷6—F÷'Ð¢g&öÒ—fâæF"ç&W÷6—F÷&–W2æWfVçE÷&Wò–×÷'BW†V7WF–öäWfVçE&W÷6—F÷'Ð¢g&öÒ—fâæFöÖ–âç&öÆW2–×÷'B66U7FFRÂ&öÆTWF†÷&—¦F–öäW'&÷ Ð Ð¢&ö¦V7BÒ&ö¦V7E&W÷6—F÷'’†F"’ævWB‡&ö¦V7Eö–BÂFVæçEö–CÖ6öçFW‡BçFVæçEö–BÐ¢–b&ö¦V7B—2æöæS Ð¢&—6R…EEW†6WF–öâ‡7FGW5ö6öFSÓCBÂFWF–ÃÒ%&ö¦V7Bæ÷Bf÷VæB"Ð¢–FVçF—G’Ò7F÷%ö–FVçF—G•ög&öÕö6öçFW‡B†6öçFW‡BÂFVfVÇEöÖöFSÒ'WFFR"Ð¢&WVW7FVE÷7FFRÒ7G"‚†&öG’÷"·Ò’ævWB‚&66U÷7FFR"’÷"""’ç7G&—‚Ð¢G'“ Ð¢gFW"Ò66U7FFR‡&WVW7FVE÷7FFRÐ¢W†6WBfÇVTW'&÷"2W†3 Ð¢&—6R…EEW†6WF–öâ€Ð¢7FGW5ö6öFSÓCÀÐ¢FWF–Ã×²&W'&÷"#¢$”ådÄ”Eô44Uõ5DDR"Â&66U÷7FFR#¢&WVW7FVE÷7FFWÒÀÐ¢’g&öÒW†0Ð¢&Vf÷&RÒ&ö¦V7Bæ66U÷7FFPÐ¢G'“ Ð¢FV6—6–öâÒ66TFöÖ–å&W÷6—F÷'’†F"’çG&ç6—F–öåö66R€Ð¢&ö¦V7C×&ö¦V7BÀÐ¢gFW#ÖgFW"ÀÐ¢–FVçF—G“Ö–FVçF—G’ÀÐ¢6÷W&6U÷G&6Uö–CÖ6öçFW‡BçG&6Uö–BÀÐ¢Ð¢W†6WB&öÆTWF†÷&—¦F–öäW'&÷"2W†3 Ð¢F"æ6öÖÖ—B‚Ð¢&—6R…EEW†6WF–öâ€Ð¢7FGW5ö6öFSÓC2ÀÐ¢FWF–Ã×²&W'&÷"#¢W†2æ6öFRÂ'&V6öâ#¢W†2ç&V6öçÒÀÐ¢’g&öÒW†0Ð¢W†V7WF–öäWfVçE&W÷6—F÷'’†F"’æVæB€Ð¢&ö¦V7Bç&ö¦V7Eö–BÀÐ¢$44Uõ5DDUõE$å4•D”ôâ"ÀÐ¢b$66R7FFR6†ævVBg&öÒ¶FV6—6–öâæ&Vf÷&RçfÇVWÒFò¶FV6—6–öâægFW"çfÇVWÒ"ÀÐ¢FVæçEö–C×&ö¦V7BçFVæçEö–BÀÐ¢6÷W&6U÷G&6Uö–CÖ6öçFW‡BçG&6Uö–BÀÐ¢7F÷%ö–CÖ–FVçF—G’æ7F÷%ö–BÀÐ¢7F÷%÷&öÆSÖ–FVçF—G’æ'W6–æW75÷&öÆRçfÇVRÀÐ¢6öçfW'6F–öå÷&öÆSÖ–FVçF—G’æ6öçfW'6F–öå÷&öÆRçfÇVRÀÐ¢WF†÷&—¦F–öåö&6—3Ö–FVçF—G’æWF†÷&—¦F–öåö&6—2ÀÐ¢&Vf÷&S×²&66U÷7FFR#¢&Vf÷&WÒÀÐ¢gFW#×²&66U÷7FFR#¢&ö¦V7Bæ66U÷7FFWÒÀÐ¢Ð¢F"æ6öÖÖ—B‚Ð¢&WGW&â°Ð¢'&ö¦V7Eö–B#¢&ö¦V7Bç&ö¦V7Eö–BÀÐ¢&&Vf÷&R#¢FV6—6–öâæ&Vf÷&RçfÇVRÀÐ¢&gFW"#¢FV6—6–öâægFW"çfÇVRÀÐ¢&7F÷%ö–B#¢–FVçF—G’æ7F÷%ö–BÀÐ¢&7F÷%÷&öÆR#¢–FVçF—G’æ'W6–æW75÷&öÆRçfÇVRÀÐ¢'6÷W&6U÷G&6Uö–B#¢6öçFW‡BçG&6Uö–BÀÐ¢&WF†÷&—¦F–öåö&6—2#¢–FVçF—G’æWF†÷&—¦F–öåö&6—2ÀÐ¢ÐÐ Ð Ð¤ç÷7B‚"ö’÷W6W"×&VfW&Væ6W2÷WFFR"Ð¦FVbWFFU÷W6W%÷&VfW&Væ6W2€Ð¢&öG“¢F–7BÀÐ¢F#¢6W76–öâÒFWVæG2†vWEöF"’ÀÐ¢6öçFW‡C¢&WVW7D6öçFW‡BÒFWVæG2…÷&WV—&Uö•ö¶W’’ÀÐ¢“ Ð¢g&öÒ—fâæF"ç&W÷6—F÷&–W2ç&VfW&Væ6U÷&Wò–×÷'BW6W%&VfW&Væ6U&W÷6—F÷'Ð¢W6W%ö–BÒ&öG’ævWB‚'W6W%ö–B"Ð¢&VfW&Væ6U÷G—RÒ&öG’ævWB‚'&VfW&Væ6U÷G—R"Ð¢fÇVRÒ&öG’ævWB‚'fÇVR"Ð¢–bæ÷BW6W%ö–B÷"æ÷B&VfW&Væ6U÷G—R÷"æ÷B—6–ç7Fæ6R‡fÇVRÂF–7B“ Ð¢&—6R…EEW†6WF–öâ‡7FGW5ö6öFSÓCÂFWF–ÃÒ'W6W%ö–BÂ&VfW&Væ6U÷G—RÂæBö&¦V7BfÇVR&R&WV—&VB"Ð¢&V6÷&BÒW6W%&VfW&Væ6U&W÷6—F÷'’†F"’çW6W'B€Ð¢W6W%ö–C×W6W%ö–BÀÐ¢&VfW&Væ6U÷G—S×&VfW&Væ6U÷G—RÀÐ¢fÇVS×fÇVRÀÐ¢6÷W&6SÖ&öG’ævWB‚'6÷W&6R"Â&’"’ÀÐ¢6öæf–FVæ6SÖfÆöB†&öG’ævWB‚&6öæf–FVæ6R"ÂãR’’ÀÐ¢FVæçEö–CÖ6öçFW‡BçFVæçEö–BÀÐ¢Ð¢F"æ6öÖÖ—B‚Ð¢&WGW&â²'&VfW&Væ6R#¢÷6W&–Æ—¦U÷&VfW&Væ6R‡&V6÷&B—ÐÐ Ð Ð¤ævWB‚"ö’÷W6W"×&VfW&Væ6W2"Ð¦FVbvWE÷W6W%÷&VfW&Væ6W2€Ð¢W6W%ö–C¢7G"ÂæöæRÒæöæRÀÐ¢F#¢6W76–öâÒFWVæG2†vWEöF"’ÀÐ¢6öçFW‡C¢&WVW7D6öçFW‡BÒFWVæG2…÷&WV—&Uö•ö¶W’’ÀÐ¢“ Ð¢g&öÒ—fâæF"ç&W÷6—F÷&–W2ç&VfW&Væ6U÷&Wò–×÷'BW6W%&VfW&Væ6U&W÷6—F÷'Ð¢&WòÒW6W%&VfW&Væ6U&W÷6—F÷'’†F"Ð¢&V6÷&G2Ò&WòæÆ—7Eöf÷%÷W6W"‡W6W%ö–BÂFVæçEö–CÖ6öçFW‡BçFVæçEö–B’–bW6W%ö–BVÇ6R&WòæÆ—7EöÆÂ‡FVæçEö–CÖ6öçFW‡BçFVæçEö–BÐ¢&WGW&â²'&VfW&Væ6W2#¢µ÷6W&–Æ—¦U÷&VfW&Væ6R‡&V6÷&B’f÷"&V6÷&B–â&V6÷&G5×ÐÐ Ð Ð¤ævWB‚"ö’÷&ö¦V7G2÷·&ö¦V7Eö–GÒöWfVçG2"¦FVbvWE÷&ö¦V7EöWfVçG2‡&ö¦V7Eö–C¢7G"ÂF#¢6W76–öâÒFWVæG2†vWEöF"’Â6öçFW‡C¢&WVW7D6öçFW‡BÒFWVæG2…÷&WV—&Uö•ö¶W’’“ ¢–b&ö¦V7E&W÷6—F÷'’†F"’ævWB‡&ö¦V7Eö–BÂFVæçEö–CÖ6öçFW‡BçFVæçEö–B’—2æöæS Ð¢&—6R…EEW†6WF–öâ‡7FGW5ö6öFSÓCBÂFWF–ÃÒ%&ö¦V7Bæ÷Bf÷VæB"Ð¢g&öÒ—fâæF"ç&W÷6—F÷&–W2æWfVçE÷&Wò–×÷'BW†V7WF–öäWfVçE&W÷6—F÷'Ð¢&WòÒW†V7WF–öäWfVçE&W÷6—F÷'’†F"Ð¢WfVçG2Ò&WòæÆ—7Eöf÷%÷&ö¦V7B‡&ö¦V7Eö–BÂFVæçEö–CÖ6öçFW‡BçFVæçEö–BÐ¢&WGW&â²'&ö¦V7Eö–B#¢&ö¦V7Eö–BÂ&WfVçG2#¢°Ð¢²&WfVçEö–B#¢RæWfVçEö–BÂ&WfVçE÷G—R#¢RæWfVçE÷G—RÂ'7VÖÖ'’#¢Rç7VÖÖ'’Â&7&VFVEöB#¢7G"†Ræ7&VFVEöB—ÐÐ¢f÷"R–âWfVçG0Ð¢×Ð  ¦FVböWF†÷&—¦UöWfVçEö6&–Æ—G’€¢¢ÂWfVçBÂ–FVçF—G’Â6&–Æ—G’Â6÷W&6U÷G&6Uö–C¢7G"ÂF#¢6W76–öà¢’ÓâæöæS ¢g&öÒ—fâæF"ç&W÷6—F÷&–W2æFöÖ–å÷&Wò–×÷'B66TFöÖ–å&W÷6—F÷'¢g&öÒ—fâæFöÖ–âç&öÆW2–×÷'B&öÆTWF†÷&—¦F–öäW'&÷"Â&WV—&Uö6&–Æ—G ¢G'“ ¢&WV—&Uö6&–Æ—G’†–FVçF—G’Â6&–Æ—G’¢W†6WB&öÆTWF†÷&—¦F–öäW'&÷"2W†3 ¢66TFöÖ–å&W÷6—F÷'’†F"’ç&V6÷&EöVF—B€¢FVæçEö–CÖWfVçBçFVæçEö–BÀ¢66Uö–CÖWfVçBç&ö¦V7Eö–BÀ¢WfVçE÷G—SÒ$UdTåEô4õ%$T5D”ôåõ$T¤T5DTB"À¢–FVçF—G“Ö–FVçF—G’À¢6÷W&6U÷G&6Uö–C×6÷W&6U÷G&6Uö–BÀ¢&Vf÷&S×²&WfVçEö–B#¢WfVçBæWfVçEö–GÒÀ¢&V¦V7F–öå÷&V6öãÖW†2ç&V6öâÀ¢¢F"æ6öÖÖ—B‚¢&—6R…EEW†6WF–öâ€¢7FGW5ö6öFSÓC2À¢FWF–Ã×²&W'&÷"#¢W†2æ6öFRÂ'&V6öâ#¢W†2ç&V6öçÒÀ¢’g&öÒW†0  ¤ævWB‚"ö’öWfVçG2÷¶WfVçEö–GÒö–×7B"¦FVbvWEöWfVçEö–×7B€¢WfVçEö–C¢7G"À¢F#¢6W76–öâÒFWVæG2†vWEöF"’À¢6öçFW‡C¢&WVW7D6öçFW‡BÒFWVæG2…÷&WV—&Uö•ö¶W’’À¢“ ¢g&öÒ—fâæF"ç&W÷6—F÷&–W2æWfVçE÷&Wò–×÷'BW†V7WF–öäWfVçE&W÷6—F÷'¢g&öÒ—fâæFöÖ–âç&öÆW2–×÷'B6&–Æ—G¢g&öÒ—fâæW†V7WF–öâæWfVçEö6÷'&V7F–öâ–×÷'B'V–ÆEöWfVçEö–×7@ ¢WfVçBÒW†V7WF–öäWfVçE&W÷6—F÷'’†F"’ævWB†WfVçEö–BÂFVæçEö–CÖ6öçFW‡BçFVæçEö–B¢–bWfVçB—2æöæS ¢&—6R…EEW†6WF–öâ€¢7FGW5ö6öFSÓCBÂFWF–Ã×²&W'&÷"#¢&æ÷Eöf÷VæB"Â&WfVçEö–B#¢WfVçEö–GÐ¢¢–FVçF—G’Ò7F÷%ö–FVçF—G•ög&öÕö6öçFW‡B†6öçFW‡BÂFVfVÇEöÖöFSÒ&VF—B"¢öWF†÷&—¦UöWfVçEö6&–Æ—G’€¢WfVçCÖWfVçBÀ¢–FVçF—G“Ö–FVçF—G’À¢6&–Æ—G“Ô6&–Æ—G’åd”UuôTD•BÀ¢6÷W&6U÷G&6Uö–CÖ6öçFW‡BçG&6Uö–BÀ¢F#ÖF"À¢¢&WGW&â'V–ÆEöWfVçEö–×7B†F"ÂWfVçBÂFVæçEö–CÖ6öçFW‡BçFVæçEö–B  ¤ç÷7B‚"ö’öWfVçG2÷¶WfVçEö–GÒ÷&WfW'6R"¦FVb&WfW'6UöW†V7WF–öåöWfVçB€¢WfVçEö–C¢7G"À¢&öG“¢F–7BÂæöæRÒæöæRÀ¢F#¢6W76–öâÒFWVæG2†vWEöF"’À¢6öçFW‡C¢&WVW7D6öçFW‡BÒFWVæG2…÷&WV—&Uö•ö¶W’’À¢“ ¢g&öÒ—fâæF"ç&W÷6—F÷&–W2æFöÖ–å÷&Wò–×÷'B66TFöÖ–å&W÷6—F÷'¢g&öÒ—fâæF"ç&W÷6—F÷&–W2æWfVçE÷&Wò–×÷'BW†V7WF–öäWfVçE&W÷6—F÷'¢g&öÒ—fâæFöÖ–âç&öÆW2–×÷'B6&–Æ—G¢g&öÒ—fâæW†V7WF–öâæWfVçEö6÷'&V7F–öâ–×÷'B€¢&WfW'6Ä6öæfÆ–7BÀ¢Vç6fTWFöÖF–5&WfW'6ÂÀ¢&WfW'6UöWfVçBÀ¢6W&–Æ—¦U÷&WfW'6Å÷&W7VÇBÀ¢ ¢WfVçBÒW†V7WF–öäWfVçE&W÷6—F÷'’†F"’ævWB†WfVçEö–BÂFVæçEö–CÖ6öçFW‡BçFVæçEö–B¢–bWfVçB—2æöæS ¢&—6R…EEW†6WF–öâ€¢7FGW5ö6öFSÓCBÂFWF–Ã×²&W'&÷"#¢&æ÷Eöf÷VæB"Â&WfVçEö–B#¢WfVçEö–GÐ¢¢–FVçF—G’Ò7F÷%ö–FVçF—G•ög&öÕö6öçFW‡B†6öçFW‡BÂFVfVÇEöÖöFSÒ&VF—B"¢öWF†÷&—¦UöWfVçEö6&–Æ—G’€¢WfVçCÖWfVçBÀ¢–FVçF—G“Ö–FVçF—G’À¢6&–Æ—G“Ô6&–Æ—G’å$UdU%4UôUdTåBÀ¢6÷W&6U÷G&6Uö–CÖ6öçFW‡BçG&6Uö–BÀ¢F#ÖF"À¢¢–bæ÷B6öçFW‡Bæ–FV×÷FVæ7•ö¶W“ ¢&—6R…EEW†6WF–öâ€¢7FGW5ö6öFSÓCÀ¢FWF–Ã×²&W'&÷"#¢$”DTÕõDTä5•ô´U•õ$UT•$TB"Â&†VFW"#¢$–FV×÷FVæ7’Ô¶W’'ÒÀ¢¢–ÆöBÒ&öG’÷"·Ð¢&V6öâÒ7G"‡–ÆöBævWB‚'&V6öâ"’÷"""’ç7G&—‚¢–bæ÷B&V6öã ¢&—6R…EEW†6WF–öâ€¢7FGW5ö6öFSÓCÂFWF–Ã×²&W'&÷"#¢%$UdU%4Åõ$T4ôåõ$UT•$TB'Ð¢¢G'“ ¢&W7VÇBÒ&WfW'6UöWfVçB€¢F"À¢WfVçBÀ¢FVæçEö–CÖ6öçFW‡BçFVæçEö–BÀ¢7WÆ–VEö–FV×÷FVæ7•ö¶W“Ö6öçFW‡Bæ–FV×÷FVæ7•ö¶W’À¢–FVçF—G“Ö–FVçF—G’À¢6÷W&6U÷G&6Uö–CÖ6öçFW‡BçG&6Uö–BÀ¢&V6öã×&V6öâÀ¢6ö×Vç6F–öåööæÇ“Ö&ööÂ‡–ÆöBævWB‚&6ö×Vç6F–öåööæÇ’"ÂfÇ6R’’À¢¢W†6WBVç6fTWFöÖF–5&WfW'6Â2W†3 ¢&—6R…EEW†6WF–öâ€¢7FGW5ö6öFSÓC’À¢FWF–Ã×²&W'&÷"#¢$UDôÔD”5õ$UdU%4ÅõTå4dR"Â&–×7B#¢W†2æ–×7GÒÀ¢’g&öÒW†0¢W†6WB&WfW'6Ä6öæfÆ–7B2W†3 ¢&—6R…EEW†6WF–öâ€¢7FGW5ö6öFSÓC’À¢FWF–Ã×²&W'&÷"#¢%$UdU%4Åô4ôädÄ”5B"Â'&V6öâ#¢7G"†W†2—ÒÀ¢’g&öÒW†0 ¢–bæ÷B&W7VÇBæ–FV×÷FVçE÷&WÆ“ ¢66TFöÖ–å&W÷6—F÷'’†F"’ç&V6÷&EöVF—B€¢FVæçEö–CÖ6öçFW‡BçFVæçEö–BÀ¢66Uö–CÖWfVçBç&ö¦V7Eö–BÀ¢WfVçE÷G—SÒ€¢$UdTåEõ$UdU%4TB ¢–b&W7VÇBç&V6÷&Bç7FGW2ÓÒ&Æ–VB ¢VÇ6R$UdTåEô4ôÕTå4D”ôåõ$UT•$TB ¢’À¢–FVçF—G“Ö–FVçF—G’À¢6÷W&6U÷G&6Uö–CÖ6öçFW‡BçG&6Uö–BÀ¢&Vf÷&SÖWfVçBægFW%ö§6öâ÷"·ÒÀ¢gFW#Ò€¢WfVçBæ&Vf÷&Uö§6öâ÷"·Ð¢–b&W7VÇBç&V6÷&Bç7FGW2ÓÒ&Æ–VB ¢VÇ6RWfVçBægFW%ö§6öâ÷"·Ð¢’À¢¢F"æ6öÖÖ—B‚¢&WGW&â6W&–Æ—¦U÷&WfW'6Å÷&W7VÇB‡&W7VÇB ¤ævWB‚"ö’÷&ö¦V7G2÷·&ö¦V7Eö–GÒö÷F–öç2"¦FVbvWE÷&ö¦V7Eö÷F–öç2‡&ö¦V7Eö–C¢7G"ÂF#¢6W76–öâÒFWVæG2†vWEöF"’Â6öçFW‡C¢&WVW7D6öçFW‡BÒFWVæG2…÷&WV—&Uö•ö¶W’’“ Ð¢&WòÒ&ö¦V7E&W÷6—F÷'’†F"Ð¢&ö¦V7BÒ&WòævWB‡&ö¦V7Eö–BÂFVæçEö–CÖ6öçFW‡BçFVæçEö–BÐ¢–bæ÷B&ö¦V7C Ð¢&—6R…EEW†6WF–öâ‡7FGW5ö6öFSÓCBÂFWF–ÃÒ%&ö¦V7Bæ÷Bf÷VæB"Ð¢&WGW&â²'&ö¦V7Eö–B#¢&ö¦V7Eö–BÂ'6VÆV7FVEö÷F–öâ#¢&ö¦V7Bç6VÆV7FVEö÷F–öåö§6öçÐÐ Ð¤ç÷7B‚"ö’ö÷Væ6Ærö66÷VçG2÷&Vv—7FW""Ð¦FVb&Vv—7FW%ö66÷VçB†&öG“¢F–7BÂF#¢6W76–öâÒFWVæG2†vWEöF"’Â6öçFW‡C¢&WVW7D6öçFW‡BÒFWVæG2…÷&WV—&Uö•ö¶W’’“ Ð¢g&öÒ—fâæ÷Væ6Æræ66÷VçEöFVÆVvF–öâ–×÷'B&Vv—7FW%ö66÷Vç@Ð¢G'“ Ð¢66÷VçBÒ&Vv—7FW%ö66÷VçB†F"Â&öG’ÂFVæçEö–CÖ6öçFW‡BçFVæçEö–BÐ¢F"æ6öÖÖ—B‚Ð¢&WGW&â66÷VçBæÖöFVÅöGV×‚Ð¢W†6WBfÇVTW'&÷"2S Ð¢&—6R…EEW†6WF–öâ‡7FGW5ö6öFSÓCÂFWF–Ã×7G"†R’Ð Ð¤ævWB‚"ö’ö÷Væ6Ærö66÷VçG2"Ð¦FVbÆ—7Eö66÷VçG2†F#¢6W76–öâÒFWVæG2†vWEöF"’Â6öçFW‡C¢&WVW7D6öçFW‡BÒFWVæG2…÷&WV—&Uö•ö¶W’’“ Ð¢g&öÒ—fâæ÷Væ6Æræ66÷VçEöFVÆVvF–öâ–×÷'BÆ—7Eö66÷VçG0Ð¢66÷VçG2ÒÆ—7Eö66÷VçG2†F"ÂFVæçEö–CÖ6öçFW‡BçFVæçEö–BÐ¢&WGW&â²&66÷VçG2#¢¶æÖöFVÅöGV×‚’f÷"–â66÷VçG5×ÐÐ Ð¤ævWB‚"ö’ö÷Væ6Ærö66÷VçG2÷¶66÷VçEö6öææV7F–öåö–GÒ"Ð¦FVbvWEö66÷VçB†66÷VçEö6öææV7F–öåö–C¢7G"ÂF#¢6W76–öâÒFWVæG2†vWEöF"’Â6öçFW‡C¢&WVW7D6öçFW‡BÒFWVæG2…÷&WV—&Uö•ö¶W’’“ Ð¢g&öÒ—fâæF"ç&W÷6—F÷&–W2æ66÷VçE÷&Wò–×÷'B66÷VçE&W÷6—F÷'Ð¢&WòÒ66÷VçE&W÷6—F÷'’†F"Ð¢66÷VçBÒ&WòævWB†66÷VçEö6öææV7F–öåö–BÂFVæçEö–CÖ6öçFW‡BçFVæçEö–BÐ¢–bæ÷B66÷VçC Ð¢&—6R…EEW†6WF–öâ‡7FGW5ö6öFSÓCBÂFWF–ÃÒ$66÷VçBæ÷Bf÷VæB"Ð¢&WGW&â²&66÷VçEö6öææV7F–öåö–B#¢66÷VçBæ66÷VçEö6öææV7F–öåö–BÂ'ÆFf÷&Ò#¢66÷VçBçÆFf÷&ÒÂ'7FGW2#¢66÷VçBç7FGW2Â'W&Ö—76–öç2#¢66÷VçBçW&Ö—76–öç5ö§6öçÐÐ Ð¤ç÷7B‚"ö’ö÷Væ6Ærö66÷VçG2÷¶66÷VçEö6öææV7F–öåö–GÒ÷&Wfö¶R"Ð¦FVb&Wfö¶Uö66÷VçB†66÷VçEö6öææV7F–öåö–C¢7G"ÂF#¢6W76–öâÒFWVæG2†vWEöF"’Â6öçFW‡C¢&WVW7D6öçFW‡BÒFWVæG2…÷&WV—&Uö•ö¶W’’“ Ð¢g&öÒ—fâæ÷Væ6Æræ66÷VçEöFVÆVvF–öâ–×÷'B&Wfö¶Uö66÷Vç@Ð¢&Wfö¶VBÒ&Wfö¶Uö66÷VçB†F"Â66÷VçEö6öææV7F–öåö–BÂFVæçEö–CÖ6öçFW‡BçFVæçEö–BÐ¢F"æ6öÖÖ—B‚Ð¢&WGW&â²&66÷VçEö6öææV7F–öåö–B#¢66÷VçEö6öææV7F–öåö–BÂ'&Wfö¶VB#¢&Wfö¶VGÐÐ Ð¤ævWB‚"ö’ö÷Væ6Ærö66÷VçG2÷¶66÷VçEö6öææV7F–öåö–GÒ÷W&Ö—76–öç2"Ð¦FVbvWEö66÷VçE÷W&Ö—76–öç2†66÷VçEö6öææV7F–öåö–C¢7G"ÂF#¢6W76–öâÒFWVæG2†vWEöF"’Â6öçFW‡C¢&WVW7D6öçFW‡BÒFWVæG2…÷&WV—&Uö•ö¶W’’“ Ð¢g&öÒ—fâæF"ç&W÷6—F÷&–W2æ66÷VçE÷&Wò–×÷'B66÷VçE&W÷6—F÷'Ð¢&WòÒ66÷VçE&W÷6—F÷'’†F"Ð¢66÷VçBÒ&WòævWB†66÷VçEö6öææV7F–öåö–BÂFVæçEö–CÖ6öçFW‡BçFVæçEö–BÐ¢–bæ÷B66÷VçC Ð¢&—6R…EEW†6WF–öâ‡7FGW5ö6öFSÓCBÂFWF–ÃÒ$66÷VçBæ÷Bf÷VæB"Ð¢&WGW&â²&66÷VçEö6öææV7F–öåö–B#¢66÷VçEö6öææV7F–öåö–BÂ'W&Ö—76–öç2#¢66÷VçBçW&Ö—76–öç5ö§6öâÂ&ÆÆ÷vVEö7F–öç2#¢66÷VçBæÆÆ÷vVEö7F–öç5ö§6öçÐÐ Ð Ð¦FVb÷6W&–Æ—¦UöG&gB†B’ÓâF–7C Ð¢G&gE÷G—RÒ" Ð¢f÷"'B–â†Bææ÷FW2÷"""’ç7Æ—B‚“ Ð¢–b'Bç7F'G7v—F‚‚&G&gE÷G—SÒ"“ Ð¢G&gE÷G—RÒ'Bç7Æ—B‚#Ò"Â•³ÐÐ¢&WGW&â°Ð¢&G&gEö–B#¢BæG&gEö–BÀÐ¢'FVæçEö–B#¢BçFVæçEö–BÀÐ¢'&ö¦V7Eö–B#¢Bç&ö¦V7Eö–BÀÐ¢&6öçfW'6F–öåö–B#¢Bæ6öçfW'6F–öåö–BÀÐ¢&6†ææVÂ#¢Bæ6†ææVÂÀÐ¢&6†ææVÅö66÷VçEö–B#¢Bæ6†ææVÅö66÷VçEö–BÀÐ¢'F&vWE÷VW%ö–B#¢BçF&vWE÷VW%ö–BÀÐ¢'F&vWE÷&öÆR#¢BçF&vWE÷&öÆRÀÐ¢&ÖW76vU÷FW‡B#¢BæÖW76vU÷FW‡BÀÐ¢&ÖW76vU÷G—R#¢BæÖW76vU÷G—RÀÐ¢&GF6†ÖVçG2#¢BæGF6†ÖVçG5ö§6öâ÷"µÒÀÐ¢'7FGW2#¢Bç7FGW2ÀÐ¢&7&VFVEö'•övVçB#¢Bæ7&VFVEö'•övVçBÀÐ¢&G&gE÷G—R#¢G&gE÷G—RÀÐ¢&&÷fVEö'’#¢Bæ&÷fVEö'’ÀÐ¢&æ÷FW2#¢Bææ÷FW2ÀÐ¢&7&VFVEöB#¢7G"†Bæ7&VFVEöB’ÀÐ¢&&÷fVEöB#¢7G"†Bæ&÷fVEöB’–bBæ&÷fVEöBVÇ6RæöæRÀÐ¢'6VçEöB#¢7G"†Bç6VçEöB’–bBç6VçEöBVÇ6RæöæRÀÐ¢ÐÐ Ð Ð¦FVb÷6W&–Æ—¦U÷&VfW&Væ6R‡&V6÷&B’ÓâF–7C Ð¢&WGW&â°Ð¢'&VfW&Væ6Uö–B#¢&V6÷&Bç&VfW&Væ6Uö–BÀÐ¢'W6W%ö–B#¢&V6÷&BçW6W%ö–BÀÐ¢'&VfW&Væ6U÷G—R#¢&V6÷&Bç&VfW&Væ6U÷G—RÀÐ¢'fÇVR#¢&V6÷&BçfÇVUö§6öâÀÐ¢'6÷W&6R#¢&V6÷&Bç6÷W&6RÀÐ¢&6öæf–FVæ6R#¢&V6÷&Bæ6öæf–FVæ6RÀÐ¢&7&VFVEöB#¢7G"‡&V6÷&Bæ7&VFVEöB’ÀÐ¢'WFFVEöB#¢7G"‡&V6÷&BçWFFVEöB’ÀÐ¢ÐÐ