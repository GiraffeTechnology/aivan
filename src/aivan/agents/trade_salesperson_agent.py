from __future__ import annotations
from dataclasses import dataclass, field
from aivan.openclaw.contracts import OpenClawEvent
from aivan.openclaw.event_adapter import is_customer_message, is_supplier_reply
from aivan.openclaw.binding_store import get_project_id, bind_conversation
from aivan.openclaw.draft_store import create_draft_in_db
from aivan.agents.requirement_agent import structure_customer_requirement_with_llm
from aivan.agents.clarification_agent import generate_clarification_message
from aivan.agents.supplier_inquiry_agent import draft_supplier_inquiry
from aivan.agents.supplier_response_agent import parse_supplier_reply
from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.sourcing.supplier_matcher import match_suppliers_for_requirement
from aivan.sourcing.supplier_registry import list_active as list_active_suppliers
from aivan.sourcing.marketplaces.search_query_builder import build_marketplace_queries
from aivan.sourcing.marketplaces.alibaba_connector import search_alibaba
from aivan.platforms.platform_registry import is_platform_trusted
from aivan.risk.supplier_risk_agent import run_risk_screening
from aivan.risk.risk_report import should_block_supplier
from aivan.integrations.gltg import calculate_leadtime_for_requirement
from aivan.execution.event_log import append_event
from aivan.utils.ids import new_project_id
from aivan.utils.time_utils import utcnow_iso

@dataclass
class AgentTurnResult:
    project_id: str
    action: str
    message: str
    drafts_created: list[str] = field(default_factory=list)
    requirement: object = None
    supplier_matches: list = field(default_factory=list)
    buyer_options: list = field(default_factory=list)
    risk_reports: list = field(default_factory=list)
    lead_time_estimates: list = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

def handle_trade_salesperson_event(
    event: OpenClawEvent,
    db_session,
) -> AgentTurnResult:
    """Main entry point: handle an incoming OpenClaw event."""
    from aivan.db.repositories.project_repo import ProjectRepository
    project_repo = ProjectRepository(db_session)

    project_id = event.project_id
    if not project_id:
        project_id = get_project_id(event.conversation_id)

    project = project_repo.get(project_id) if project_id else None

    if not project:
        # Try by conversation_id in DB (handles cross-session restarts and test isolation)
        project = project_repo.get_by_conversation(event.conversation_id)
        if project:
            project_id = project.project_id
            bind_conversation(event.conversation_id, project_id)

    if not project:
        p = project_repo.create(
            conversation_id=event.conversation_id,
            customer_id=event.sender_id,
            channel=event.channel,
            channel_account_id=event.channel_account_id,
            customer_display_name=event.sender_display_name,
        )
        project_id = p.project_id
        project = p
        bind_conversation(event.conversation_id, project_id)
        db_session.commit()
        append_event(db_session, project_id, "PROJECT_CREATED", f"New project for {event.sender_display_name}", actor="trade_salesperson_agent")

    if is_supplier_reply(event):
        return _handle_supplier_reply(event, project_id, project, db_session)

    return _handle_customer_message(event, project_id, project, db_session)

def _handle_customer_message(event, project_id, project, db_session) -> AgentTurnResult:
    from aivan.db.repositories.project_repo import ProjectRepository
    project_repo = ProjectRepository(db_session)

    existing_req = None
    if project.requirement_json:
        try:
            from aivan.schemas.requirement import BuyerRequirement
            existing_req = BuyerRequirement(**project.requirement_json)
        except Exception:
            pass

    req = structure_customer_requirement_with_llm(
        raw_text=event.message_text,
        attachments=event.attachments,
        existing_requirement=existing_req,
        project_id=project_id,
        source_channel=event.channel,
    )

    project_repo.update_requirement(project_id, req.model_dump())
    db_session.commit()
    append_event(db_session, project_id, "REQUIREMENT_STRUCTURED", f"Category: {req.category}, product: {req.product_type}", actor="requirement_agent")

    if not req.is_complete():
        clarification_msg = generate_clarification_message(req)
        draft_id = None
        if clarification_msg:
            draft_id = create_draft_in_db(
                db_session=db_session,
                project_id=project_id,
                conversation_id=event.conversation_id,
                channel=event.channel,
                target_peer_id=event.sender_id,
                target_role="customer",
                message_text=clarification_msg,
                created_by_agent="clarification_agent",
            )
            db_session.commit()
            append_event(db_session, project_id, "OUTBOUND_DRAFT_CREATED", "Clarification draft created", payload={"draft_id": draft_id}, actor="clarification_agent")

        return AgentTurnResult(
            project_id=project_id,
            action="clarification_needed",
            message=f"Requirement incomplete. Missing: {', '.join(mf.field_name for mf in req.missing_fields)}. Clarification draft created.",
            drafts_created=[draft_id] if draft_id else [],
            requirement=req,
        )

    matches = match_suppliers_for_requirement(req, limit=10)
    append_event(db_session, project_id, "SUPPLIER_MATCHED", f"Found {len(matches)} supplier matches", actor="supplier_matcher")

    drafts_created = []
    errors = []

    if len(matches) < 3:
        queries = build_marketplace_queries(req)
        marketplace_candidates = []
        if is_platform_trusted("alibaba"):
            for query in queries[:2]:
                result = search_alibaba(query, platform="alibaba")
                marketplace_candidates.extend(result.candidates)
        append_event(db_session, project_id, "MARKETPLACE_CANDIDATES_FOUND", f"Found {len(marketplace_candidates)} marketplace candidates", actor="marketplace_connector")

        risk_reports = []
        for cand in marketplace_candidates[:5]:
            risk_report = run_risk_screening(
                supplier_name=cand.supplier_name,
                candidate_id=cand.candidate_id,
                category=req.category,
                existing_flags=cand.risk_flags,
            )
            if should_block_supplier(risk_report):
                append_event(db_session, project_id, "SUPPLIER_RISK_REPORT_CREATED", f"BLOCKED critical-risk supplier: {cand.supplier_name}", actor="risk_agent")
                continue
            risk_reports.append(risk_report)

            lt = calculate_leadtime_for_requirement(req, candidate_id=cand.candidate_id)
            append_event(db_session, project_id, "LEADTIME_ESTIMATE_CREATED", f"Lead time for {cand.supplier_name}: {lt.expected_days} days", actor="leadtime_calculator")

            inquiry_text = draft_supplier_inquiry(req, candidate=cand)
            draft_id = create_draft_in_db(
                db_session=db_session,
                project_id=project_id,
                conversation_id=event.conversation_id,
                channel=cand.contact_channels.get("channel", "openclaw-marketplace-im"),
                target_peer_id=cand.openclaw_peer_id or cand.wangwang_id or cand.candidate_id,
                target_role="supplier",
                message_text=inquiry_text,
                created_by_agent="supplier_inquiry_agent",
                notes=f"Marketplace candidate: {cand.supplier_name} ({cand.platform})",
            )
            drafts_created.append(draft_id)
            append_event(db_session, project_id, "OUTBOUND_DRAFT_CREATED", f"Supplier inquiry draft for {cand.supplier_name}", payload={"draft_id": draft_id}, actor="supplier_inquiry_agent")

        db_session.commit()
        return AgentTurnResult(
            project_id=project_id,
            action="marketplace_search_complete",
            message=f"Requirement complete. {len(marketplace_candidates)} marketplace candidates found, {len(drafts_created)} inquiry drafts created. Awaiting human approval.",
            drafts_created=drafts_created,
            requirement=req,
            supplier_matches=matches,
            risk_reports=risk_reports,
            errors=errors,
        )

    for match in matches[:5]:
        sup = match.supplier
        lt = calculate_leadtime_for_requirement(req, supplier_id=sup.supplier_id)
        inquiry_text = draft_supplier_inquiry(req, supplier=sup)
        draft_id = create_draft_in_db(
            db_session=db_session,
            project_id=project_id,
            conversation_id=event.conversation_id,
            channel=sup.channels[0] if sup.channels else "email",
            target_peer_id=sup.openclaw_peer_id or sup.email or sup.supplier_id,
            target_role="supplier",
            message_text=inquiry_text,
            created_by_agent="supplier_inquiry_agent",
        )
        drafts_created.append(draft_id)
        append_event(db_session, project_id, "OUTBOUND_DRAFT_CREATED", f"Inquiry draft for {sup.name}", payload={"draft_id": draft_id}, actor="supplier_inquiry_agent")

    db_session.commit()
    return AgentTurnResult(
        project_id=project_id,
        action="inquiry_drafts_created",
        message=f"Requirement complete. {len(matches)} suppliers matched. {len(drafts_created)} inquiry drafts created. Awaiting human approval.",
        drafts_created=drafts_created,
        requirement=req,
        supplier_matches=matches,
    )

def _handle_supplier_reply(event, project_id, project, db_session) -> AgentTurnResult:
    from aivan.db.repositories.project_repo import ProjectRepository
    project_repo = ProjectRepository(db_session)

    reply = parse_supplier_reply(
        raw_text=event.message_text,
        project_id=project_id,
        channel=event.channel,
    )
    append_event(db_session, project_id, "PRODUCTION_UPDATE_RECEIVED", f"Supplier reply received: price={reply.unit_price}", actor="supplier_response_agent")

    requirement = None
    if project.requirement_json:
        try:
            from aivan.schemas.requirement import BuyerRequirement
            requirement = BuyerRequirement(**project.requirement_json)
        except Exception:
            pass

    if not requirement:
        return AgentTurnResult(project_id=project_id, action="reply_received", message="Supplier reply received but no requirement found.", errors=["No requirement found"])

    lt = calculate_leadtime_for_requirement(requirement, supplier_reply=reply)
    append_event(db_session, project_id, "LEADTIME_ESTIMATE_CREATED", f"Lead time estimate: {lt.expected_days} days", actor="leadtime_calculator")

    options = generate_buyer_options(requirement, [reply], [lt], project_id)
    append_event(db_session, project_id, "BUYER_OPTIONS_GENERATED", f"Generated {len(options)} buyer options", actor="buyer_option_agent")

    drafts_created = []
    if options:
        option_summary = "\n".join(
            f"{opt.option_label}: {opt.reasoning} | Lead time: {opt.lead_time_estimate.expected_days if opt.lead_time_estimate else 'N/A'} days | Price: {opt.quote.buyer_unit_price if opt.quote else 'N/A'} {opt.quote.currency if opt.quote else ''}"
            for opt in options
        )
        draft_id = create_draft_in_db(
            db_session=db_session,
            project_id=project_id,
            conversation_id=event.conversation_id,
            channel=event.channel,
            target_peer_id=project.customer_id,
            target_role="customer",
            message_text=f"We have received supplier quotes. Here are your Top-3 options:\n\n{option_summary}\n\nPlease let us know which option you prefer.",
            created_by_agent="buyer_option_agent",
        )
        drafts_created.append(draft_id)
        append_event(db_session, project_id, "OUTBOUND_DRAFT_CREATED", f"Buyer options draft created", payload={"draft_id": draft_id}, actor="buyer_option_agent")

    db_session.commit()
    return AgentTurnResult(
        project_id=project_id,
        action="buyer_options_ready",
        message=f"Supplier reply parsed. {len(options)} buyer options generated. Draft awaiting approval.",
        drafts_created=drafts_created,
        requirement=requirement,
        buyer_options=options,
        lead_time_estimates=[lt],
    )
