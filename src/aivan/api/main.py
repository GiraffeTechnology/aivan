from __future__ import annotations
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from aivan.db.session import get_db, init_db
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.platform_repo import PlatformRepository
from aivan.db.repositories.account_repo import AccountRepository

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from aivan.platforms.platform_registry import _ensure_init
    _ensure_init()
    yield

app = FastAPI(title="AIVAN - AI Trade Salesperson", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_templates_dir = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
_static_dir = os.path.join(os.path.dirname(__file__), "..", "app", "static")

templates = Jinja2Templates(directory=_templates_dir)

try:
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
except Exception:
    pass

@app.get("/health")
def health():
    return {"status": "ok", "product": "AIVAN", "version": "0.1.0"}

@app.get("/app", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def serve_app(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "title": "AIVAN"})

@app.post("/api/openclaw/events")
def openclaw_event(event_data: dict, db: Session = Depends(get_db)):
    try:
        from aivan.openclaw.event_adapter import parse_openclaw_event
        from aivan.agents.trade_salesperson_agent import handle_trade_salesperson_event
        event = parse_openclaw_event(event_data)
        result = handle_trade_salesperson_event(event, db)
        return {
            "project_id": result.project_id,
            "action": result.action,
            "message": result.message,
            "drafts_created": result.drafts_created,
            "errors": result.errors,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/skill/invoke")
def skill_invoke(event_data: dict, db: Session = Depends(get_db)):
    return openclaw_event(event_data, db)

@app.post("/api/openclaw/drafts/{draft_id}/approve")
def approve_draft(draft_id: str, body: dict = None, db: Session = Depends(get_db)):
    repo = DraftRepository(db)
    approved_by = (body or {}).get("approved_by", "user")
    draft = repo.approve(draft_id, approved_by)
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found or not pending")
    from aivan.openclaw.outbound_approval import send_if_approved
    response = send_if_approved(draft_id, db)
    db.commit()
    return {"draft_id": draft_id, "status": "approved", "sent": response.success, "error": response.error}

@app.post("/api/openclaw/drafts/{draft_id}/reject")
def reject_draft(draft_id: str, db: Session = Depends(get_db)):
    repo = DraftRepository(db)
    draft = repo.reject(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    db.commit()
    return {"draft_id": draft_id, "status": "rejected"}

@app.get("/api/openclaw/projects/{project_id}/pending-drafts")
def get_pending_drafts(project_id: str, db: Session = Depends(get_db)):
    repo = DraftRepository(db)
    drafts = repo.list_pending(project_id)
    return {"project_id": project_id, "drafts": [
        {"draft_id": d.draft_id, "target_role": d.target_role, "message_text": d.message_text[:200], "created_by_agent": d.created_by_agent, "status": d.status}
        for d in drafts
    ]}

@app.get("/api/openclaw/projects/{project_id}/state")
def get_project_state(project_id: str, db: Session = Depends(get_db)):
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
def register_account(body: dict, db: Session = Depends(get_db)):
    from aivan.openclaw.account_delegation import register_account
    try:
        account = register_account(db, body)
        db.commit()
        return account.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/openclaw/accounts")
def list_accounts(db: Session = Depends(get_db)):
    from aivan.openclaw.account_delegation import list_accounts
    accounts = list_accounts(db)
    return {"accounts": [a.model_dump() for a in accounts]}

@app.get("/api/openclaw/accounts/{account_connection_id}")
def get_account(account_connection_id: str, db: Session = Depends(get_db)):
    from aivan.db.repositories.account_repo import AccountRepository
    repo = AccountRepository(db)
    account = repo.get(account_connection_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"account_connection_id": account.account_connection_id, "platform": account.platform, "status": account.status, "permissions": account.permissions_json}

@app.post("/api/openclaw/accounts/{account_connection_id}/revoke")
def revoke_account(account_connection_id: str, db: Session = Depends(get_db)):
    from aivan.openclaw.account_delegation import revoke_account
    revoked = revoke_account(db, account_connection_id)
    db.commit()
    return {"account_connection_id": account_connection_id, "revoked": revoked}

@app.get("/api/openclaw/accounts/{account_connection_id}/permissions")
def get_account_permissions(account_connection_id: str, db: Session = Depends(get_db)):
    from aivan.db.repositories.account_repo import AccountRepository
    repo = AccountRepository(db)
    account = repo.get(account_connection_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"account_connection_id": account_connection_id, "permissions": account.permissions_json, "allowed_actions": account.allowed_actions_json}
