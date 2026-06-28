from __future__ import annotations
import logging
import os
import secrets
import traceback
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

logger = logging.getLogger("aivan.api")


def _require_api_key(request: Request) -> None:
    """Enforce X-AIVAN-API-Key when AIVAN_API_KEY is configured."""
    configured = os.environ.get("AIVAN_API_KEY", "").strip()
    if not configured:
        return  # auth not enabled
    provided = request.headers.get("X-AIVAN-API-Key", "").strip()
    if not provided:
        raise HTTPException(status_code=401, detail="Missing X-AIVAN-API-Key header")
    if not secrets.compare_digest(provided, configured):
        raise HTTPException(status_code=403, detail="Invalid API key")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from aivan.platforms.platform_registry import _ensure_init
    _ensure_init()
    from aivan.gpm.router import _init_store as _gpm_init_store, get_db_client
    _gpm_init_store()
    app.state.giraffe_db_client = get_db_client()
    yield

app = FastAPI(title="AIVAN - AI Trade Salesperson", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(_gpm_router, prefix="/api/gpm", tags=["gpm"])


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never surface a raw 500 to the OpenClaw skill caller.

    OpenClaw treats an HTTP 500 from a skill as "skill broken" and disables it,
    whereas an HTTP 200 carrying {"status": "error"} is a recoverable
    "skill returned error" the user can see and retry. So any uncaught exception
    is logged with its traceback and converted to a 200 error envelope.
    Explicit HTTPException (401/403/404/409/...) is handled by FastAPI's own
    handler and keeps its status code.
    """
    logger.error(
        "Unhandled exception on %s %s: %s: %s\n%s",
        request.method,
        request.url.path,
        type(exc).__name__,
        exc,
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=200,
        content={
            "status": "error",
            "output": "Internal error; please retry or contact support.",
        },
    )


def _skill_response(result) -> dict:
    """Wrap an RFQ execution result in the OpenClaw skill envelope.

    Adds the {"status": "ok", "output": ...} contract OpenClaw expects while
    preserving every existing top-level field (project_id, action, strategy, ...)
    so the bridge plugin and existing callers keep working.
    """
    data = result.model_dump()
    return {"status": "ok", "output": data.get("message", ""), **data}

_templates_dir = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
_static_dir = os.path.join(os.path.dirname(__file__), "..", "app", "static")

templates = Jinja2Templates(directory=_templates_dir)

try:
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
except Exception:
    pass

@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok", "product": "AIVAN", "version": "0.2.0"}

@app.get("/app", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def serve_app(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "title": "AIVAN"})

@app.post("/api/openclaw/events")
def openclaw_event(
    event_data: dict,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    from aivan.openclaw.event_adapter import parse_openclaw_event
    from aivan.execution.rfq_execution import create_rfq_from_event
    event = parse_openclaw_event(event_data)
    return _skill_response(create_rfq_from_event(event, db))

@app.post("/api/skill/invoke")
def skill_invoke(event_data: dict, db: Session = Depends(get_db)):
    from aivan.openclaw.event_adapter import parse_openclaw_event
    from aivan.execution.rfq_execution import create_rfq_from_event
    return _skill_response(create_rfq_from_event(parse_openclaw_event(event_data), db))


@app.post("/api/rfq/create-from-event")
def create_rfq_from_event_api(
    event_data: dict,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    from aivan.openclaw.event_adapter import parse_openclaw_event
    from aivan.execution.rfq_execution import create_rfq_from_event
    return _skill_response(create_rfq_from_event(parse_openclaw_event(event_data), db))


def _do_approve_draft(draft_id: str, body: dict | None, db: Session) -> dict:
    repo = DraftRepository(db)
    draft = repo.get(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    if draft.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Draft {draft_id} cannot be approved: current status is '{draft.status}'",
        )
    approved_by = (body or {}).get("approved_by", "user")
    repo.approve(draft_id, approved_by)
    from aivan.openclaw.outbound_approval import send_if_approved
    response = send_if_approved(draft_id, db)
    db.commit()
    return {"draft_id": draft_id, "status": "approved", "sent": response.success, "error": response.error}


def _do_reject_draft(draft_id: str, db: Session) -> dict:
    repo = DraftRepository(db)
    draft = repo.get(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    if draft.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Draft {draft_id} cannot be rejected: current status is '{draft.status}'",
        )
    repo.reject(draft_id)
    db.commit()
    return {"draft_id": draft_id, "status": "rejected"}


@app.post("/api/openclaw/drafts/{draft_id}/approve")
def approve_draft(
    draft_id: str,
    body: dict = None,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    return _do_approve_draft(draft_id, body, db)


@app.post("/api/openclaw/drafts/{draft_id}/reject")
def reject_draft(
    draft_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    return _do_reject_draft(draft_id, db)


# Short-form aliases used by the OpenClaw plugin and dashboard
@app.post("/api/drafts/{draft_id}/approve")
def approve_draft_alias(
    draft_id: str,
    body: dict = None,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    return _do_approve_draft(draft_id, body, db)


@app.post("/api/drafts/{draft_id}/reject")
def reject_draft_alias(
    draft_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    return _do_reject_draft(draft_id, db)


@app.get("/api/drafts")
def list_all_drafts(
    project_id: str | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    repo = DraftRepository(db)
    if project_id:
        drafts = repo.list_pending(project_id)
    else:
        drafts = repo.list_all_pending()
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


@app.get("/api/openclaw/projects/{project_id}/pending-drafts")
def get_pending_drafts(
    project_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    repo = DraftRepository(db)
    drafts = repo.list_pending(project_id)
    return {"project_id": project_id, "drafts": [
        {"draft_id": d.draft_id, "target_role": d.target_role, "message_text": d.message_text[:200], "created_by_agent": d.created_by_agent, "status": d.status}
        for d in drafts
    ]}

@app.get("/api/openclaw/projects/{project_id}/state")
def get_project_state(project_id: str, db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    repo = ProjectRepository(db)
    project = repo.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    draft_repo = DraftRepository(db)
    pending = draft_repo.list_pending(project_id)
    return {
        "project_id": project_id,
        "status": project.status,
        "requirement": project.requirement_json,
        "pending_drafts": len(pending),
    }

@app.post("/api/suppliers/import")
def import_suppliers(body: dict, db: Session = Depends(get_db)):
    csv_content = body.get("csv_content", "")
    if not csv_content:
        raise HTTPException(status_code=400, detail="csv_content required")
    from aivan.sourcing.supplier_importer import import_from_csv
    count, errors = import_from_csv(csv_content, db)
    db.commit()
    return {"imported": count, "errors": errors}

@app.get("/api/suppliers")
def list_suppliers(db: Session = Depends(get_db)):
    from aivan.sourcing.supplier_registry import list_active
    suppliers = list_active()
    return {"suppliers": [s.model_dump() for s in suppliers], "total": len(suppliers)}

@app.post("/api/suppliers/match")
def match_suppliers(body: dict, db: Session = Depends(get_db)):
    from aivan.schemas.requirement import BuyerRequirement
    from aivan.sourcing.supplier_matcher import match_suppliers_for_requirement
    req = BuyerRequirement(**body)
    matches = match_suppliers_for_requirement(req, limit=10)
    return {"matches": [{"supplier": m.supplier.model_dump(), "match_score": m.match_score, "match_reason": m.match_reason} for m in matches]}

@app.get("/api/platforms")
def list_platforms():
    from aivan.platforms.platform_registry import list_all_platforms
    platforms = list_all_platforms()
    return {"platforms": [p.model_dump() for p in platforms]}

@app.get("/api/platforms/whitelist")
def list_whitelist():
    from aivan.platforms.platform_registry import list_trusted_platforms
    platforms = list_trusted_platforms()
    return {"trusted_platforms": [p.model_dump() for p in platforms]}

@app.post("/api/platforms/whitelist")
def add_platform_to_whitelist(body: dict, db: Session = Depends(get_db)):
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
    add_platform(platform)
    return {"added": platform.model_dump()}

@app.get("/api/platforms/suggestions")
def list_platform_suggestions():
    from aivan.platforms.platform_registry import list_suggestions
    sugs = list_suggestions()
    return {"suggestions": [s.model_dump() for s in sugs]}

@app.post("/api/platforms/suggestions/{suggestion_id}/approve")
def approve_platform_suggestion(suggestion_id: str):
    from aivan.platforms.platform_registry import approve_suggestion
    sug = approve_suggestion(suggestion_id)
    if not sug:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return {"suggestion_id": suggestion_id, "status": "approved"}

@app.post("/api/platforms/suggestions/{suggestion_id}/reject")
def reject_platform_suggestion(suggestion_id: str):
    from aivan.platforms.platform_registry import reject_suggestion
    sug = reject_suggestion(suggestion_id)
    if not sug:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return {"suggestion_id": suggestion_id, "status": "rejected"}

@app.post("/api/platforms/suggestions/{suggestion_id}/block")
def block_platform_suggestion(suggestion_id: str):
    from aivan.platforms.platform_registry import block_suggestion
    sug = block_suggestion(suggestion_id)
    if not sug:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return {"suggestion_id": suggestion_id, "status": "blocked"}

@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db)):
    repo = ProjectRepository(db)
    projects = repo.list_all(limit=50)
    return {"projects": [
        {"project_id": p.project_id, "status": p.status, "category": p.category, "customer_id": p.customer_id, "created_at": str(p.created_at)}
        for p in projects
    ]}

@app.get("/api/projects/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db)):
    repo = ProjectRepository(db)
    project = repo.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "project_id": project.project_id,
        "status": project.status,
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
    _: None = Depends(_require_api_key),
):
    project = ProjectRepository(db).get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    drafts = DraftRepository(db).list_for_project(project_id)
    return {"project_id": project_id, "drafts": [_serialize_draft(d) for d in drafts]}


@app.post("/api/projects/{project_id}/strategy")
def update_project_strategy(
    project_id: str,
    body: dict,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    from aivan.schemas.rfq import RFQStrategy
    project_repo = ProjectRepository(db)
    project = project_repo.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        strategy = RFQStrategy(**body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid strategy: {e}")
    requirement = dict(project.requirement_json or {})
    requirement["strategy"] = strategy.model_dump()
    project_repo.update_requirement(project_id, requirement)
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    ExecutionEventRepository(db).append(
        project_id,
        "STRATEGY_UPDATED",
        f"Strategy updated to priority={strategy.priority}, scope={strategy.supplier_scope}",
        payload=strategy.model_dump(),
        actor="api",
    )
    db.commit()
    return {"project_id": project_id, "strategy": strategy.model_dump()}


@app.post("/api/projects/{project_id}/run-gltg")
def run_project_gltg(
    project_id: str,
    body: dict | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    from aivan.integrations.giraffe_db import GiraffeDBClient
    from aivan.integrations.gltg import GLTGClient
    from aivan.schemas.requirement import BuyerRequirement
    from aivan.schemas.rfq import RFQStrategy
    project_repo = ProjectRepository(db)
    project = project_repo.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
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
    giraffe = GiraffeDBClient(db).build_context(requirement, customer_id=project.customer_id)
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
    )
    db.commit()
    return {"project_id": project_id, "gltg_simulation": simulation.model_dump()}


@app.post("/api/user-preferences/update")
def update_user_preferences(
    body: dict,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
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
    )
    db.commit()
    return {"preference": _serialize_preference(record)}


@app.get("/api/user-preferences")
def get_user_preferences(
    user_id: str | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    from aivan.db.repositories.preference_repo import UserPreferenceRepository
    repo = UserPreferenceRepository(db)
    records = repo.list_for_user(user_id) if user_id else repo.list_all()
    return {"preferences": [_serialize_preference(record) for record in records]}


@app.get("/api/projects/{project_id}/events")
def get_project_events(project_id: str, db: Session = Depends(get_db)):
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    repo = ExecutionEventRepository(db)
    events = repo.list_for_project(project_id)
    return {"project_id": project_id, "events": [
        {"event_id": e.event_id, "event_type": e.event_type, "summary": e.summary, "created_at": str(e.created_at)}
        for e in events
    ]}

@app.get("/api/projects/{project_id}/options")
def get_project_options(project_id: str, db: Session = Depends(get_db)):
    repo = ProjectRepository(db)
    project = repo.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project_id": project_id, "selected_option": project.selected_option_json}

@app.post("/api/openclaw/accounts/register")
def register_account(body: dict, db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    from aivan.openclaw.account_delegation import register_account
    try:
        account = register_account(db, body)
        db.commit()
        return account.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/openclaw/accounts")
def list_accounts(db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    from aivan.openclaw.account_delegation import list_accounts
    accounts = list_accounts(db)
    return {"accounts": [a.model_dump() for a in accounts]}

@app.get("/api/openclaw/accounts/{account_connection_id}")
def get_account(account_connection_id: str, db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    from aivan.db.repositories.account_repo import AccountRepository
    repo = AccountRepository(db)
    account = repo.get(account_connection_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"account_connection_id": account.account_connection_id, "platform": account.platform, "status": account.status, "permissions": account.permissions_json}

@app.post("/api/openclaw/accounts/{account_connection_id}/revoke")
def revoke_account(account_connection_id: str, db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    from aivan.openclaw.account_delegation import revoke_account
    revoked = revoke_account(db, account_connection_id)
    db.commit()
    return {"account_connection_id": account_connection_id, "revoked": revoked}

@app.get("/api/openclaw/accounts/{account_connection_id}/permissions")
def get_account_permissions(account_connection_id: str, db: Session = Depends(get_db), _: None = Depends(_require_api_key)):
    from aivan.db.repositories.account_repo import AccountRepository
    repo = AccountRepository(db)
    account = repo.get(account_connection_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"account_connection_id": account_connection_id, "permissions": account.permissions_json, "allowed_actions": account.allowed_actions_json}


def _serialize_draft(d) -> dict:
    draft_type = ""
    for part in (d.notes or "").split():
        if part.startswith("draft_type="):
            draft_type = part.split("=", 1)[1]
    return {
        "draft_id": d.draft_id,
        "project_id": d.project_id,
        "conversation_id": d.conversation_id,
        "channel": d.channel,
        "target_peer_id": d.target_peer_id,
        "target_role": d.target_role,
        "message_text": d.message_text,
        "message_type": d.message_type,
        "attachments": d.attachments_json or [],
        "status": d.status,
        "created_by_agent": d.created_by_agent,
        "draft_type": draft_type,
        "approved_by": d.approved_by,
        "notes": d.notes,
        "created_at": str(d.created_at),
        "approved_at": str(d.approved_at) if d.approved_at else None,
        "sent_at": str(d.sent_at) if d.sent_at else None,
    }


def _serialize_preference(record) -> dict:
    return {
        "preference_id": record.preference_id,
        "user_id": record.user_id,
        "preference_type": record.preference_type,
        "value": record.value_json,
        "source": record.source,
        "confidence": record.confidence,
        "created_at": str(record.created_at),
        "updated_at": str(record.updated_at),
    }
