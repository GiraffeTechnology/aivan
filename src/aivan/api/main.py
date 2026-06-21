from __future__ import annotations
import os
import secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Request, Header
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


def _require_api_key(request: Request) -> None:
    """Enforce X-AIVAN-API-Key when AIVAN_API_KEY is configured."""
    configured = os.environ.get("AIVAN_API_KEY", "").strip()
    if not configured:
        return
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
@app.get("/api/health")
def health():
    return {"status": "ok", "product": "AIVAN", "version": "0.1.0"}


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


# ---------------------------------------------------------------------------
# Draft approval
# ---------------------------------------------------------------------------

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
    drafts = repo.list_pending(project_id) if project_id else repo.list_all_pending()
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
        {"draft_id": d.draft_id, "target_role": d.target_role,
         "message_text": d.message_text[:200], "created_by_agent": d.created_by_agent,
         "status": d.status}
        for d in drafts
    ]}


@app.get("/api/openclaw/projects/{project_id}/state")
def get_project_state(
    project_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
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


# ---------------------------------------------------------------------------
# Guided-relay endpoints (Workstream C)
# ---------------------------------------------------------------------------

@app.get("/api/relay/outbox")
def relay_outbox(
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    """List drafts waiting for human relay (awaiting_relay)."""
    repo = DraftRepository(db)
    cards = repo.list_awaiting_relay()
    return {"relay_cards": [
        {
            "draft_id": c.draft_id,
            "project_id": c.project_id,
            "channel": c.channel,
            "counterparty_id": c.target_peer_id,
            "message_text": c.message_text,
            "created_at": str(c.created_at),
        }
        for c in cards
    ]}


@app.post("/api/relay/{draft_id}/confirm")
def relay_confirm(
    draft_id: str,
    body: dict = None,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    """Human confirms they have manually sent the relay card message."""
    repo = DraftRepository(db)
    draft = repo.get(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    if draft.status != "awaiting_relay":
        raise HTTPException(
            status_code=409,
            detail=f"Draft {draft_id} not awaiting relay (status: {draft.status})",
        )
    confirmed_by = (body or {}).get("confirmed_by", "user")
    repo.mark_relayed(draft_id, confirmed_by=confirmed_by)
    db.commit()
    return {"draft_id": draft_id, "status": "relayed", "confirmed_by": confirmed_by}


@app.post("/api/relay/inbound")
def relay_inbound(
    body: dict,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    """Paste a counterparty reply into AIVAN from the Giraffe relay UI.

    body: { thread_id, counterparty_id, pasted_text, channel? }

    The pasted text is recorded as an InboundRelayEvent and then fed into
    the trade-salesperson pipeline as a synthetic inbound event.
    """
    thread_id = body.get("thread_id", "")
    counterparty_id = body.get("counterparty_id", "")
    pasted_text = body.get("pasted_text", "").strip()
    channel = body.get("channel", "")

    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id required")
    if not pasted_text:
        raise HTTPException(status_code=400, detail="pasted_text required")

    # Record the inbound event for auditability and reversal support
    from aivan.db.repositories.inbound_repo import InboundRelayRepository
    from aivan.db.repositories.event_repo import ExecutionEventRepository

    inbound_repo = InboundRelayRepository(db)
    event_repo = ExecutionEventRepository(db)

    # Synthesise a project_id from thread_id (or look up an existing project)
    # Use thread_id as project_id for traceability
    exec_event = event_repo.append(
        project_id=thread_id,
        event_type="inbound_relay_paste",
        summary=f"Pasted reply from {counterparty_id}: {pasted_text[:80]}",
        payload={"counterparty_id": counterparty_id, "pasted_text": pasted_text, "channel": channel},
        actor="relay_ui",
    )

    inbound = inbound_repo.create(
        thread_id=thread_id,
        counterparty_id=counterparty_id,
        pasted_text=pasted_text,
        channel=channel,
        linked_execution_event_id=exec_event.event_id,
    )

    # Feed into the pipeline as a synthetic OpenClaw event
    try:
        from aivan.openclaw.event_adapter import parse_openclaw_event
        from aivan.agents.trade_salesperson_agent import handle_trade_salesperson_event
        synthetic = parse_openclaw_event({
            "source": "relay_ui",
            "channel": channel,
            "conversation_id": thread_id,
            "sender_id": counterparty_id,
            "message_text": pasted_text,
            "project_id": thread_id,
            "role_context": body.get("role_context", "supplier"),
        })
        handle_trade_salesperson_event(synthetic, db)
    except Exception as e:
        db.commit()
        return {
            "inbound_id": inbound.inbound_id,
            "execution_event_id": exec_event.event_id,
            "pipeline_warning": str(e),
        }

    db.commit()
    return {
        "inbound_id": inbound.inbound_id,
        "execution_event_id": exec_event.event_id,
        "thread_id": thread_id,
        "status": "processed",
    }


# ---------------------------------------------------------------------------
# Reversal endpoints (Workstream D)
# ---------------------------------------------------------------------------

@app.get("/api/events/{event_id}/impact")
def event_impact(
    event_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    """Preview the blast radius of reversing *event_id* without committing."""
    from aivan.db.repositories.event_repo import ExecutionEventRepository
    from aivan.db.repositories.draft_repo import DraftRepository
    from aivan.db.repositories.inbound_repo import InboundRelayRepository

    event_repo = ExecutionEventRepository(db)
    draft_repo = DraftRepository(db)

    event = event_repo.get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

    affected_drafts = draft_repo.list_derived_from(event_id)
    already_sent = [
        {"draft_id": d.draft_id, "status": d.status}
        for d in affected_drafts
        if d.status in ("sent", "relayed")
    ]
    pending_invalidation = [
        {"draft_id": d.draft_id, "status": d.status}
        for d in affected_drafts
        if d.status not in ("sent", "relayed")
    ]

    return {
        "event_id": event_id,
        "superseded": event.superseded,
        "already_sent_cannot_recall": already_sent,
        "pending_invalidation": pending_invalidation,
        "requires_correction_draft": len(already_sent) > 0,
    }


@app.post("/api/events/{event_id}/reverse")
def reverse_event(
    event_id: str,
    body: dict,
    db: Session = Depends(get_db),
    _: None = Depends(_require_api_key),
):
    """Reverse an inbound event.  Requires { reason, confirm: true }.

    Returns:
    - reversal_event_id
    - affected_drafts: invalidated draft ids
    - already_sent: drafts that were already sent/relayed (cannot be recalled)
    - correction_draft_id: auto-generated correction draft (if already_sent non-empty)
    """
    if not body.get("confirm"):
        raise HTTPException(
            status_code=400,
            detail="Reversal requires { confirm: true } to prevent accidental cascade",
        )
    reason = body.get("reason", "")
    actor = body.get("actor", "user")

    from aivan.db.repositories.event_repo import ExecutionEventRepository
    from aivan.db.repositories.draft_repo import DraftRepository
    from aivan.db.repositories.inbound_repo import InboundRelayRepository

    event_repo = ExecutionEventRepository(db)
    draft_repo = DraftRepository(db)

    event = event_repo.get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    if event.superseded:
        raise HTTPException(status_code=409, detail=f"Event {event_id} is already superseded")

    # Append reversal event (also marks original superseded)
    reversal = event_repo.append_reversal(
        project_id=event.project_id,
        original_event_id=event_id,
        reason=reason,
        actor=actor,
    )

    # Supersede the InboundRelayEvent record if applicable
    inbound_repo = InboundRelayRepository(db)
    if event.payload_json:
        # Find the inbound record linked to this execution event
        linked = (
            db.query(type(None).__class__)
            .filter()  # placeholder; done via inbound_repo below
            .first() if False else None
        )
    # Simpler: supersede any inbound whose linked_execution_event_id == event_id
    from aivan.db.models.inbound_event import InboundRelayEvent
    inbounds = (
        db.query(InboundRelayEvent)
        .filter(InboundRelayEvent.linked_execution_event_id == event_id)
        .all()
    )
    for inb in inbounds:
        inb.superseded = True

    # Cascade: invalidate non-sent drafts derived from this event
    affected_draft_ids = draft_repo.invalidate_derived(event_id)

    # Identify already-sent drafts that cannot be recalled
    all_derived = draft_repo.list_derived_from(event_id)
    already_sent = [
        {"draft_id": d.draft_id, "status": d.status, "sent_at": str(d.sent_at)}
        for d in all_derived
        if d.status in ("sent", "relayed")
    ]

    # If anything was already sent, auto-generate a correction draft
    correction_draft_id = None
    if already_sent:
        correction_text = (
            f"[Correction] A previous message sent around {already_sent[0].get('sent_at', 'unknown')} "
            f"was based on incorrect information. Please disregard it. "
            f"Correction reason: {reason}"
        )
        correction = draft_repo.create(
            project_id=event.project_id,
            data={
                "channel": "email",  # operator will adjust before approving
                "message_text": correction_text,
                "created_by_agent": "reversal_engine",
                "notes": f"Auto-generated correction for reversal of {event_id}",
                "derived_from_event_id": reversal.event_id,
            },
        )
        correction_draft_id = correction.draft_id

    db.commit()
    return {
        "reversal_event_id": reversal.event_id,
        "original_event_id": event_id,
        "affected_drafts_invalidated": affected_draft_ids,
        "already_sent_cannot_recall": already_sent,
        "correction_draft_id": correction_draft_id,
        "requires_human_review": len(already_sent) > 0,
    }


# ---------------------------------------------------------------------------
# LINE webhook (Workstream B)
# ---------------------------------------------------------------------------

@app.post("/webhook/line")
async def line_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive LINE webhook events.  Verifies HMAC-SHA256 signature."""
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    from aivan.channels.line import verify_line_signature
    if not verify_line_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid LINE signature")

    import json
    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    results = []
    for line_event in payload.get("events", []):
        if line_event.get("type") != "message":
            continue
        msg = line_event.get("message", {})
        if msg.get("type") != "text":
            continue
        user_id = line_event.get("source", {}).get("userId", "")
        text = msg.get("text", "")
        reply_token = line_event.get("replyToken", "")
        try:
            from aivan.openclaw.event_adapter import parse_openclaw_event
            from aivan.agents.trade_salesperson_agent import handle_trade_salesperson_event
            event = parse_openclaw_event({
                "source": "line",
                "channel": "line",
                "conversation_id": user_id,
                "sender_id": user_id,
                "message_text": text,
                "role_context": "buyer",
            })
            result = handle_trade_salesperson_event(event, db)
            results.append({"user_id": user_id, "action": result.action})
        except Exception as e:
            results.append({"user_id": user_id, "error": str(e)})

    db.commit()
    return {"processed": len(results), "results": results}


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Platforms
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db)):
    repo = ProjectRepository(db)
    projects = repo.list_all(limit=50)
    return {"projects": [
        {"project_id": p.project_id, "status": p.status, "category": p.category,
         "customer_id": p.customer_id, "created_at": str(p.created_at)}
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
        {
            "event_id": e.event_id,
            "event_type": e.event_type,
            "summary": e.summary,
            "superseded": e.superseded,
            "references_event_id": e.references_event_id,
            "created_at": str(e.created_at),
        }
        for e in events
    ]}


@app.get("/api/projects/{project_id}/options")
def get_project_options(project_id: str, db: Session = Depends(get_db)):
    repo = ProjectRepository(db)
    project = repo.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project_id": project_id, "selected_option": project.selected_option_json}


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

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
    return {"account_connection_id": account.account_connection_id, "platform": account.platform,
            "status": account.status, "permissions": account.permissions_json}


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
    return {"account_connection_id": account_connection_id, "permissions": account.permissions_json,
            "allowed_actions": account.allowed_actions_json}
