from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from aivan.agents.requirement_agent import structure_customer_requirement_with_llm
from aivan.agents.supplier_response_agent import parse_supplier_reply
from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.event_repo import ExecutionEventRepository
from aivan.db.repositories.preference_repo import UserPreferenceRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.integrations.giraffe_db import GiraffeDBClient, persist_rfq_gltg_graph
from aivan.integrations.gltg import GLTGClient, GLTGUnavailableError
from aivan.integrations.gltg import calculate_leadtime_for_requirement
from aivan.schemas.leadtime import LeadTimeEstimate
from aivan.llm.gateway import llm_complete_json
from aivan.llm.policy import ExternalModelApiRequiresApprovalError, LocalModelUnavailableError
from aivan.execution.safety import (
    ExecutionGateResult,
    evaluate_requirement_readiness,
    evaluate_supplier_readiness,
)
from aivan.rfq.dependency_policy import classify_exception
from aivan.rfq.operator_reply import render_operator_reply
from aivan.openclaw.binding_store import bind_conversation, get_project_id
from aivan.openclaw.client import get_openclaw_client
from aivan.openclaw.contracts import OpenClawEvent
from aivan.openclaw.contracts import OpenClawSendRequest
from aivan.execution.channel_policy import USER_CONTROL_CHANNELS, normalize_channel
from aivan.openclaw.event_adapter import is_supplier_reply
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply
from aivan.schemas.rfq import (
    EventClassification,
    FallbackTrigger,
    GiraffeContext,
    RFQExecutionResult,
    RFQStrategy,
    SupplierRoutingDecision,
)

logger = logging.getLogger(__name__)

CLASSIFICATION_SYSTEM = """
You classify AIVAN private-domain trade events. Return JSON only.
Allowed event_type values: user_command, customer_new_inquiry, customer_followup,
customer_reply, supplier_reply, internal_status_request, approval_response, unknown.
Do not attach an event to a project unless AIVAN-provided state validates it.
"""

STRATEGY_SYSTEM = """
You translate user trade strategy into structured JSON. Use only the user's
instruction and AIVAN-provided context. Do not invent suppliers, history, prices,
lead times, risk facts, or compliance decisions.
"""

DRAFT_SYSTEM = """
You draft concise business email text from AIVAN-provided requirement, strategy,
supplier, and GLTG context. Do not invent facts. Return JSON only.
"""


def classify_event(event: OpenClawEvent, db: Session) -> EventClassification:
    project_repo = ProjectRepository(db)
    validated_project_id = event.project_id if event.project_id and project_repo.get(event.project_id) else None
    if not validated_project_id and event.conversation_id:
        project = project_repo.get_by_conversation(event.conversation_id)
        if project:
            validated_project_id = project.project_id

    schema_hint = {
        "event_type": "user_command | customer_new_inquiry | customer_followup | customer_reply | supplier_reply | internal_status_request | approval_response | unknown",
        "confidence": 0.0,
        "reason": "",
    }
    user_prompt = (
        f"channel={event.channel}\nrole_context={event.role_context}\n"
        f"mode={event.mode}\nmessage={event.message_text}\n"
        f"validated_project_id={validated_project_id or ''}"
    )
    try:
        raw = llm_complete_json("aivan_event_classification", CLASSIFICATION_SYSTEM, user_prompt, schema_hint)
    except Exception:
        raw = {}
    fallback = _fallback_event_type(event, bool(validated_project_id))
    event_type = raw.get("event_type") if raw.get("event_type") in EventClassification.model_fields["event_type"].annotation.__args__ else fallback
    return EventClassification(
        event_type=event_type or fallback,
        confidence=float(raw.get("confidence") or (0.7 if fallback != "unknown" else 0.3)),
        reason=raw.get("reason") or "deterministic fallback classification",
        project_id=validated_project_id,
        validated_project_attachment=bool(validated_project_id),
    )


def interpret_strategy(raw_text: str, context: GiraffeContext | None = None) -> RFQStrategy:
    schema_hint = RFQStrategy().model_dump()
    user_prompt = f"User instruction:\n{raw_text}\n\nAIVAN context keys: {list((context or GiraffeContext()).model_dump().keys())}"
    try:
        raw = llm_complete_json("aivan_strategy_interpretation", STRATEGY_SYSTEM, user_prompt, schema_hint)
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    strategy_keys = set(RFQStrategy.model_fields)
    if not (set(raw) & strategy_keys):
        return _fallback_strategy(raw_text)
    try:
        return RFQStrategy(**raw)
    except Exception:
        return _fallback_strategy(raw_text)


def create_rfq_from_event(event: OpenClawEvent, db: Session) -> RFQExecutionResult:
    """Idempotent entry point for inbound events.

    A duplicated/retried inbound event (same source+channel+account+conversation+
    message) replays its original result instead of creating duplicate projects,
    RFQs, drafts, or execution events. Events without a stable identity (no
    message id and no conversation id) are processed without idempotency rather
    than being wrongly collapsed together.
    """
    from aivan.db.repositories.inbound_event_repo import (
        InboundEventRepository,
        build_inbound_idempotency_key,
    )

    idem_key = build_inbound_idempotency_key(
        source=getattr(event, "source", "") or "",
        channel=event.channel or "",
        channel_account_id=event.channel_account_id or "",
        conversation_id=event.conversation_id or "",
        message_id=event.message_id or "",
    )
    repo = InboundEventRepository(db)
    if idem_key:
        existing = repo.get(idem_key)
        if existing is not None:
            # Replay the stored result; create no new project/RFQ/draft/event.
            return RFQExecutionResult(**existing.result_json)

    result = _create_rfq_from_event_inner(event, db)

    if idem_key:
        repo.record(
            idem_key,
            project_id=result.project_id,
            event_type=result.event_type,
            result_json=result.model_dump(),
        )
        db.commit()
    return result


def _create_rfq_from_event_inner(event: OpenClawEvent, db: Session) -> RFQExecutionResult:
    classification = classify_event(event, db)
    if classification.event_type == "supplier_reply":
        return _handle_supplier_reply_event(event, classification, db)
    if classification.event_type in {"internal_status_request", "approval_response", "unknown"}:
        return _record_non_rfq_event(event, classification, db)

    project = _get_or_create_project(event, classification, db)
    existing_requirement = _load_requirement(project.requirement_json)
    requirement = structure_customer_requirement_with_llm(
        raw_text=event.message_text,
        attachments=event.attachments,
        existing_requirement=existing_requirement,
        project_id=project.project_id,
        source_channel=event.channel,
    )

    # ---- Execution readiness gate ------------------------------------- #
    # Nothing downstream (strategy, giraffe-db context, GLTG, graph
    # persistence, supplier drafts) may run until the requirement is ready.
    gate = evaluate_requirement_readiness(requirement)
    if not gate.ready:
        return _blocked_requirement_result(project, event, classification, requirement, gate, db)

    # ---- Dependency-guarded execution --------------------------------- #
    try:
        strategy = interpret_strategy(event.message_text)
        giraffe = GiraffeDBClient(db).build_context(
            requirement=requirement,
            customer_id=project.customer_id,
            user_id=event.actor_id or event.sender_id,
        )
        strategy = interpret_strategy(event.message_text, giraffe)

        supplier_feasibility, suppliers_ready = evaluate_supplier_readiness(giraffe.suppliers)
        if not suppliers_ready:
            # 0 suppliers -> selection; exactly 1 -> single-supplier confirmation.
            # Neither is an error, and neither runs GLTG or creates drafts.
            return _pending_supplier_result(
                project, event, classification, requirement, strategy,
                supplier_feasibility, giraffe.suppliers, db,
            )

        gltg = GLTGClient().simulate(requirement, strategy, supplier_count=len(giraffe.suppliers))
    except (GLTGUnavailableError, ExternalModelApiRequiresApprovalError, LocalModelUnavailableError) as exc:
        return _dependency_recovery_result(project, event, classification, requirement, exc, db)

    giraffe_db_graph: dict = {}
    giraffe_db_graph_error: dict | None = None
    try:
        giraffe_db_graph = persist_rfq_gltg_graph(
            event=event,
            project_id=project.project_id,
            requirement=requirement,
            strategy=strategy,
            gltg=gltg,
        )
    except Exception as exc:
        giraffe_db_graph_error = {
            "error_type": exc.__class__.__name__,
            "message": str(exc),
        }
        logger.exception(
            "Failed to persist giraffe-db RFQ/GLTG graph for project %s",
            project.project_id,
        )
    routing = _select_suppliers(giraffe, strategy)

    project_payload = requirement.model_dump()
    project_payload["strategy"] = strategy.model_dump()
    project_payload["giraffe_context_summary"] = {
        "known_suppliers": len(giraffe.suppliers),
        "risk_flags": len(giraffe.risk_flags),
    }
    project_payload["gltg_simulation"] = gltg.model_dump()
    if giraffe_db_graph:
        project_payload["giraffe_db_graph"] = giraffe_db_graph
    ProjectRepository(db).update_requirement(project.project_id, project_payload)
    _learn_strategy_preference(event.actor_id or event.sender_id or "default", strategy, db)

    event_repo = ExecutionEventRepository(db)
    event_repo.append(
        project.project_id,
        "EVENT_CLASSIFIED",
        f"Inbound event classified as {classification.event_type}",
        payload=classification.model_dump(),
        actor="aivan_event_api",
    )
    event_repo.append(
        project.project_id,
        "STRATEGY_INTERPRETED",
        f"Strategy priority={strategy.priority}, scope={strategy.supplier_scope}",
        payload=strategy.model_dump(),
        actor="llm_strategy_interpreter",
    )
    event_repo.append(
        project.project_id,
        "GIRAFFE_CONTEXT_LOOKUP",
        f"Loaded {len(giraffe.suppliers)} known suppliers and private-domain context",
        payload=giraffe.model_dump(),
        actor="giraffe_db",
    )
    event_repo.append(
        project.project_id,
        "GLTG_SIMULATION_CREATED",
        f"{strategy.lead_time_confidence} lead time={gltg.selected_confidence_days} days",
        payload=gltg.model_dump(),
        actor="gltg",
    )
    if giraffe_db_graph:
        event_repo.append(
            project.project_id,
            "GIRAFFE_DB_GRAPH_PERSISTED",
            f"Persisted pre-PO transaction graph {giraffe_db_graph.get('procurement_case_id')}",
            payload=giraffe_db_graph,
            actor="giraffe_db",
        )
    if giraffe_db_graph_error:
        event_repo.append(
            project.project_id,
            "GIRAFFE_DB_GRAPH_PERSIST_FAILED",
            "Failed to persist pre-PO transaction graph; RFQ workflow continued.",
            payload=giraffe_db_graph_error,
            actor="giraffe_db",
        )

    drafts_created = _create_supplier_email_drafts(project.project_id, event, requirement, strategy, giraffe, gltg, routing, db)

    result = RFQExecutionResult(
        project_id=project.project_id,
        event_type=classification.event_type,
        action="pending_email_approval",
        message="RFQ/project created or updated. Supplier email drafts are pending human approval.",
        strategy=strategy,
        requirement=requirement.model_dump(),
        giraffe_context=giraffe,
        gltg_simulation=gltg,
        supplier_routing=routing,
        drafts_created=drafts_created,
    )
    # Deterministic, language-matched operator reply (no debug fields / raw ids).
    user_message = render_operator_reply(result, requirement.language)
    result.user_control_message = user_message
    user_notification = _send_user_control_notification(project.project_id, event, user_message, db)
    event_repo.append(
        project.project_id,
        "USER_CONTROL_APPROVAL_REQUESTED",
        "Prepared user IM approval summary",
        payload={"message_text": user_message, "draft_ids": drafts_created, "notification": user_notification},
        actor="aivan",
    )
    db.commit()
    return result


def _empty_gltg_simulation() -> "GLTGSimulation":
    """A zeroed GLTG simulation for blocked/recovery results (GLTG not run)."""
    from aivan.schemas.rfq import GLTGSimulation

    return GLTGSimulation(
        p50_days=0,
        p80_days=0,
        p90_days=0,
        minimum_feasible_days=0,
        supplier_set_feasibility="unknown",
        known_suppliers_first_feasibility="unknown_without_deadline",
        public_bidding_time_cost_days=0,
        fallback_trigger_recommendation=FallbackTrigger(),
        selected_confidence_days=0,
        deadline_risk_level="unknown",
        explanation="GLTG not run (requirement/dependency gate blocked execution).",
    )


def _persist_raw_requirement_only(project, requirement, gate, db) -> None:
    """Persist the raw requirement and gate state without executing anything."""
    payload = requirement.model_dump()
    payload["execution_gate"] = gate.model_dump()
    ProjectRepository(db).update_requirement(project.project_id, payload)


def _blocked_requirement_result(project, event, classification, requirement, gate, db):
    """Requirement not ready: preserve raw evidence, ask for confirmation."""
    _persist_raw_requirement_only(project, requirement, gate, db)
    event_repo = ExecutionEventRepository(db)
    event_repo.append(
        project.project_id,
        "EXECUTION_GATE_BLOCKED",
        gate.blocked_reason,
        payload=gate.model_dump(),
        actor="aivan_execution_gate",
    )
    result = RFQExecutionResult(
        project_id=project.project_id,
        event_type=classification.event_type,
        action=gate.next_action,
        message=gate.blocked_reason,
        strategy=RFQStrategy(),
        requirement=requirement.model_dump(),
        giraffe_context=GiraffeContext(),
        gltg_simulation=_empty_gltg_simulation(),
        supplier_routing=SupplierRoutingDecision(),
        drafts_created=[],
        user_control_message=gate.operator_message,
    )
    notification = _send_user_control_notification(
        project.project_id, event, gate.operator_message, db
    )
    event_repo.append(
        project.project_id,
        "USER_CONTROL_CONFIRMATION_REQUESTED",
        "Requested operator confirmation for blocked RFQ",
        payload={"message_text": gate.operator_message, "notification": notification},
        actor="aivan",
    )
    db.commit()
    return result


def _pending_supplier_result(project, event, classification, requirement, strategy,
                             feasibility, suppliers, db):
    """Not enough suppliers to execute. Never fabricate drafts, never error.

    0 suppliers -> pending_supplier_selection; exactly 1 -> single-supplier
    confirmation (single-supplier risk). Both stop before GLTG and drafts.
    """
    from aivan.execution.safety import SUPPLIER_FEASIBILITY_ACTION

    action = SUPPLIER_FEASIBILITY_ACTION.get(feasibility, "pending_supplier_selection")
    zh = _should_use_chinese_user_message(requirement)
    if action == "pending_supplier_confirmation":
        supplier_name = ""
        if suppliers:
            supplier_name = suppliers[0].get("name") or suppliers[0].get("supplier_id") or ""
        message = (
            f"仅找到 1 个供应商候选（{supplier_name}）。单一供应商存在风险，"
            "请确认是否仅向该供应商询价，或补充更多供应商。AIVAN 未发送任何询价。"
            if zh
            else (
                f"Only 1 supplier candidate found ({supplier_name}). Single-supplier "
                "sourcing carries risk — please confirm whether to inquire this "
                "supplier alone or add more. No inquiries were sent."
            )
        )
        event_type = "SUPPLIER_CONFIRMATION_REQUIRED"
        event_summary = "Single supplier candidate; confirmation required"
    else:
        message = (
            "未找到已授权的供应商候选，请先添加或确认供应商。AIVAN 未生成任何供应商草稿。"
            if zh
            else "No authorized supplier candidates found. Please add or confirm suppliers. No drafts were created."
        )
        event_type = "SUPPLIER_SELECTION_REQUIRED"
        event_summary = "No authorized supplier candidates available"

    event_repo = ExecutionEventRepository(db)
    event_repo.append(
        project.project_id,
        event_type,
        event_summary,
        payload={"message_text": message, "supplier_feasibility": feasibility},
        actor="aivan_execution_gate",
    )
    notification = _send_user_control_notification(project.project_id, event, message, db)
    db.commit()
    return RFQExecutionResult(
        project_id=project.project_id,
        event_type=classification.event_type,
        action=action,
        message=message,
        strategy=strategy,
        requirement=requirement.model_dump(),
        giraffe_context=GiraffeContext(),
        gltg_simulation=_empty_gltg_simulation(),
        supplier_routing=SupplierRoutingDecision(),
        drafts_created=[],
        user_control_message=message,
    )


def _dependency_recovery_result(project, event, classification, requirement, exc, db):
    """Structured recovery for a dependency failure (never a generic backend error)."""
    recovery = classify_exception(exc)
    zh = _should_use_chinese_user_message(requirement)
    message = recovery.operator_message(zh)
    event_repo = ExecutionEventRepository(db)
    event_repo.append(
        project.project_id,
        "DEPENDENCY_RECOVERY",
        f"Dependency '{recovery.dependency}' unavailable: {recovery.blocked_reason}",
        payload=recovery.model_dump(),
        actor="aivan_dependency_policy",
    )
    logger.warning(
        "Dependency recovery for project %s: %s", project.project_id, recovery.blocked_reason
    )
    notification = _send_user_control_notification(project.project_id, event, message, db)
    db.commit()
    return RFQExecutionResult(
        project_id=project.project_id,
        event_type=classification.event_type,
        action=recovery.action,
        message=recovery.blocked_reason,
        strategy=RFQStrategy(),
        requirement=requirement.model_dump(),
        giraffe_context=GiraffeContext(),
        gltg_simulation=_empty_gltg_simulation(),
        supplier_routing=SupplierRoutingDecision(),
        drafts_created=[],
        user_control_message=message,
    )


def _fallback_event_type(event: OpenClawEvent, has_project: bool) -> str:
    text = (event.message_text or "").lower()
    role = (event.role_context or "").lower()
    if is_supplier_reply(event):
        return "supplier_reply"
    if any(word in text for word in ["approve", "approved", "同意", "批准", "发送", "send it"]):
        return "approval_response"
    if any(word in text for word in ["status", "进度", "状态"]):
        return "internal_status_request"
    if role in {"user", "owner", "operator", "sales", "salesperson"} or event.mode in {"user", "command"}:
        return "user_command"
    if role in {"buyer", "customer", "b_side"}:
        return "customer_followup" if has_project else "customer_new_inquiry"
    if event.channel in {"wechat", "line", "whatsapp", "im", "openclaw-im"}:
        return "user_command"
    return "customer_followup" if has_project else "customer_new_inquiry"


def _fallback_strategy(raw_text: str) -> RFQStrategy:
    text = (raw_text or "").lower()
    urgent = any(token in text for token in ["urgent", "asap", "急", "很急", "赶"])
    known = any(token in text for token in ["known", "familiar", "old supplier", "老供应商", "熟悉供应商", "靠谱"])
    cheap = any(token in text for token in ["cheap", "price", "价格", "便宜", "别太离谱"])
    quality = any(token in text for token in ["quality", "reliable", "质量", "靠谱", "可靠"])
    return RFQStrategy(
        priority="speed" if urgent else "price" if cheap and not urgent else "balanced",
        supplier_scope="known_suppliers_first" if known else "known_suppliers_only",
        public_bidding="fallback_only" if known else "disabled",
        lead_time_confidence="P80" if urgent else "P50",
        price_sensitivity="medium" if cheap else "low",
        quality_sensitivity="high" if quality else "medium",
        fallback_trigger=FallbackTrigger(
            min_valid_supplier_replies=2,
            max_wait_hours=24 if urgent else 48,
            lead_time_risk_threshold="medium",
        ),
    )


def _get_or_create_project(event: OpenClawEvent, classification: EventClassification, db: Session):
    repo = ProjectRepository(db)
    project_id = classification.project_id or event.project_id or get_project_id(event.conversation_id)
    project = repo.get(project_id) if project_id else None
    if project:
        bind_conversation(event.conversation_id, project.project_id)
        return project
    project = repo.get_by_conversation(event.conversation_id)
    if project:
        bind_conversation(event.conversation_id, project.project_id)
        return project
    project = repo.create(
        conversation_id=event.conversation_id,
        customer_id=event.sender_id,
        channel=event.channel,
        channel_account_id=event.channel_account_id,
        customer_display_name=event.sender_display_name,
    )
    bind_conversation(event.conversation_id, project.project_id)
    ExecutionEventRepository(db).append(
        project.project_id,
        "PROJECT_CREATED",
        f"Created RFQ project for {event.sender_display_name or event.sender_id or 'incoming event'}",
        actor="aivan_event_api",
    )
    return project


def _load_requirement(payload: dict | None) -> BuyerRequirement | None:
    if not payload:
        return None
    try:
        return BuyerRequirement(**{k: v for k, v in payload.items() if k in BuyerRequirement.model_fields})
    except Exception:
        return None


def _select_suppliers(giraffe: GiraffeContext, strategy: RFQStrategy) -> SupplierRoutingDecision:
    suppliers = sorted(
        giraffe.suppliers,
        key=lambda s: (
            s.get("past_performance_score", 0),
            s.get("delivery_score", 0),
            s.get("quality_score", 0),
        ),
        reverse=True,
    )
    selected = [s["supplier_id"] for s in suppliers if s.get("email")][:5]
    skipped = [s["supplier_id"] for s in suppliers if not s.get("email")]
    return SupplierRoutingDecision(
        selected_supplier_ids=selected,
        skipped_supplier_ids=skipped,
        public_bidding_mode=strategy.public_bidding,
        rationale=(
            "Known suppliers selected first from Giraffe DB context; public bidding is "
            f"{strategy.public_bidding} per strategy."
        ),
    )


def _create_supplier_email_drafts(
    project_id: str,
    event: OpenClawEvent,
    requirement: BuyerRequirement,
    strategy: RFQStrategy,
    giraffe: GiraffeContext,
    gltg,
    routing: SupplierRoutingDecision,
    db: Session,
) -> list[str]:
    repo = DraftRepository(db)
    suppliers_by_id = {supplier["supplier_id"]: supplier for supplier in giraffe.suppliers}
    draft_ids = []
    for supplier_id in routing.selected_supplier_ids:
        supplier = suppliers_by_id[supplier_id]
        message_text = _draft_supplier_email(requirement, strategy, supplier, gltg)
        draft = repo.create(
            project_id,
            {
                "conversation_id": event.conversation_id,
                "channel": "email",
                "target_peer_id": supplier.get("email", ""),
                "target_role": "supplier",
                "message_text": message_text,
                "message_type": "text",
                "attachments_json": [],
                "status": "pending_approval",
                "created_by_agent": "aivan_rfq_execution",
                "notes": f"draft_type=supplier_inquiry_email Known supplier: {supplier.get('name', supplier_id)}",
            },
        )
        draft_ids.append(draft.draft_id)
        ExecutionEventRepository(db).append(
            project_id,
            "PENDING_EMAIL_DRAFT_CREATED",
            f"Supplier inquiry email draft created for {supplier.get('name', supplier_id)}",
            payload={"draft_id": draft.draft_id, "supplier_id": supplier_id},
            actor="aivan_rfq_execution",
        )
    return draft_ids


def _learn_strategy_preference(user_id: str, strategy: RFQStrategy, db: Session) -> None:
    UserPreferenceRepository(db).upsert(
        user_id=user_id,
        preference_type="supplier_strategy",
        value={
            "default_supplier_scope": strategy.supplier_scope,
            "public_bidding": strategy.public_bidding,
            "lead_time_confidence": strategy.lead_time_confidence,
            "price_sensitivity": strategy.price_sensitivity,
            "quality_sensitivity": strategy.quality_sensitivity,
        },
        source="explicit_user_instruction",
        confidence=0.78,
    )


def _send_user_control_notification(project_id: str, event: OpenClawEvent, message_text: str, db: Session) -> dict:
    channel, target_peer_id, should_send, reason = _user_control_channel_and_target(event, db)
    repo = DraftRepository(db)
    draft = repo.create(
        project_id,
        {
            "conversation_id": event.conversation_id,
            "channel": channel,
            "target_peer_id": target_peer_id,
            "target_role": "user",
            "message_text": message_text,
            "message_type": "text",
            "attachments_json": [],
            "status": "approved" if should_send else "pending_approval",
            "created_by_agent": "aivan_user_control",
            "notes": f"draft_type=approval_request_im {reason}",
        },
    )
    if not should_send:
        return {
            "draft_id": draft.draft_id,
            "sent": False,
            "message_id": "",
            "error": "owner resolution required before sending user-control notification",
        }
    response = get_openclaw_client().send_message(
        OpenClawSendRequest(
            channel=channel,
            channel_account_id=event.channel_account_id,
            conversation_id=event.conversation_id,
            target_peer_id=target_peer_id,
            message_text=message_text,
            message_type="text",
        )
    )
    if response.success:
        repo.mark_sent(draft.draft_id)
    return {
        "draft_id": draft.draft_id,
        "sent": response.success,
        "message_id": response.message_id,
        "error": response.error,
    }


def _user_control_channel_and_target(event: OpenClawEvent, db: Session) -> tuple[str, str, bool, str]:
    role = (event.role_context or "").lower()
    normalized_channel = normalize_channel(event.channel)
    notification_channel = event.channel if normalized_channel in USER_CONTROL_CHANNELS else "im"
    if role in {"user", "owner", "operator", "sales", "salesperson"} or event.mode in {"user", "command"}:
        target = event.actor_id or event.sender_id
        if target:
            return notification_channel or "im", target, True, "verified_user_sender"
    if event.actor_id:
        return notification_channel or "im", event.actor_id, True, "verified_actor_id"
    owner_user_id = _owner_user_id_for_event(event, db)
    if owner_user_id:
        channel = event.channel if normalized_channel in USER_CONTROL_CHANNELS else "im"
        return channel or "im", owner_user_id, True, "verified_account_owner"
    return "internal", "owner_resolution_required", False, "owner_resolution_required"


def _owner_user_id_for_event(event: OpenClawEvent, db: Session) -> str:
    if not event.channel_account_id:
        return ""
    from aivan.db.models.account import OpenClawAccountRecord
    # Filter by channel + channel_account_id and require active/connected status so
    # revoked or stale accounts do not resolve as the owner.
    account = db.query(OpenClawAccountRecord).filter(
        OpenClawAccountRecord.channel == event.channel,
        OpenClawAccountRecord.channel_account_id == event.channel_account_id,
        OpenClawAccountRecord.status == "connected",
    ).first()
    return account.owner_user_id if account and account.owner_user_id else ""


def _draft_supplier_email(requirement: BuyerRequirement, strategy: RFQStrategy, supplier: dict, gltg) -> str:
    schema_hint = {"subject": "", "message_text": ""}
    user_prompt = {
        "supplier": supplier,
        "requirement": requirement.model_dump(),
        "strategy": strategy.model_dump(),
        "gltg": gltg.model_dump(),
    }
    try:
        raw = llm_complete_json("aivan_supplier_email_draft", DRAFT_SYSTEM, str(user_prompt), schema_hint)
    except Exception:
        raw = {}
    if raw.get("message_text"):
        return raw["message_text"]
    lines = [
        f"Dear {supplier.get('name', 'Supplier')},",
        "",
        "We are preparing an RFQ and would like your quotation for the following requirement:",
        f"- Product: {requirement.product_type or requirement.category or 'product'}",
        f"- Quantity: {requirement.quantity or 'TBD'} {requirement.quantity_unit}",
        f"- Material/spec: {requirement.fabric_material or requirement.material_spec or 'TBD'}",
        f"- Color/finish: {requirement.color or requirement.surface_finish or 'TBD'}",
        f"- Destination: {requirement.destination or 'TBD'}",
        f"- Target delivery: {requirement.delivery_days or 'TBD'} days",
        f"- Lead-time confidence requested: {strategy.lead_time_confidence}",
        "",
        "Please confirm price, lead time, capacity, payment terms, sample timing, and any risks.",
        "This inquiry is subject to buyer review and final approval.",
        "",
        "Best regards,",
        "AIVAN",
    ]
    return "\n".join(lines)


def _should_use_chinese_user_message(requirement: BuyerRequirement) -> bool:
    return requirement.language == "zh" or any(
        "一" <= ch <= "鿿" for ch in requirement.raw_text
    )


def _risk_label_for_user(risk_level: str) -> str:
    labels = {"low": "低", "medium": "中", "high": "高", "critical": "严重", "unknown": "未知"}
    return labels.get((risk_level or "unknown").lower(), risk_level or "未知")


def _build_user_control_message(
    requirement: BuyerRequirement,
    strategy: RFQStrategy,
    gltg,
    routing: SupplierRoutingDecision,
    drafts_created: list[str],
) -> str:
    if _should_use_chinese_user_message(requirement):
        deadline = (
            f"目标交期 {requirement.delivery_days} 天"
            if requirement.delivery_days
            else "目标交期待确认"
        )
        return (
            f"RFQ 已创建，等待人工审批：{requirement.quantity or 'TBD'} {requirement.quantity_unit} "
            f"{requirement.product_type or requirement.category or 'product'}，目的地 {requirement.destination or 'TBD'}，{deadline}。"
            f"策略={strategy.priority}/{strategy.supplier_scope}，GLTG {strategy.lead_time_confidence}="
            f"{gltg.selected_confidence_days} 天，交期风险={_risk_label_for_user(gltg.deadline_risk_level)}。"
            f"已生成 {len(routing.selected_supplier_ids)} 封供应商邮件草稿，仍需人工审批后才会发送：{', '.join(drafts_created)}。"
        )

    return (
        f"RFQ ready for approval: {requirement.quantity or 'TBD'} {requirement.quantity_unit} "
        f"{requirement.color} {requirement.product_type or requirement.category} to {requirement.destination or 'TBD'}. "
        f"Strategy={strategy.priority}/{strategy.supplier_scope}, GLTG {strategy.lead_time_confidence}="
        f"{gltg.selected_confidence_days} days, deadline risk={gltg.deadline_risk_level}. "
        f"{len(routing.selected_supplier_ids)} supplier email drafts are pending approval: {', '.join(drafts_created)}."
    )


def _handle_supplier_reply_event(event: OpenClawEvent, classification: EventClassification, db: Session) -> RFQExecutionResult:
    project = _get_or_create_project(event, classification, db)
    project_repo = ProjectRepository(db)
    event_repo = ExecutionEventRepository(db)
    event_repo.append(
        project.project_id,
        "EVENT_CLASSIFIED",
        "Inbound event classified as supplier_reply; invoking supplier quote workflow",
        payload=classification.model_dump(),
        actor="aivan_event_api",
    )

    reply = parse_supplier_reply(
        raw_text=event.message_text,
        project_id=project.project_id,
        supplier_id=event.sender_id or "",
        channel=event.channel,
    )
    event_repo.append(
        project.project_id,
        "SUPPLIER_REPLY_PARSED",
        f"Supplier reply parsed: price={reply.unit_price}, lead_time={reply.lead_time_days}",
        payload=reply.model_dump(),
        actor="supplier_response_agent",
    )

    requirement = _load_requirement(project.requirement_json)
    if not requirement:
        db.commit()
        empty_strategy = RFQStrategy()
        gltg = GLTGClient().simulate(BuyerRequirement(project_id=project.project_id, quantity=1), empty_strategy, 0)
        return RFQExecutionResult(
            project_id=project.project_id,
            event_type="supplier_reply",
            action="supplier_reply_requires_requirement",
            message="Supplier reply parsed, but no project requirement was available for buyer option generation.",
            strategy=empty_strategy,
            requirement={},
            giraffe_context=GiraffeContext(),
            gltg_simulation=gltg,
            supplier_routing=SupplierRoutingDecision(selected_supplier_ids=[reply.supplier_id] if reply.supplier_id else []),
        )

    strategy_payload = (project.requirement_json or {}).get("strategy") or {}
    try:
        strategy = RFQStrategy(**strategy_payload)
    except Exception:
        strategy = RFQStrategy()

    # P2: carry supplier_id so generate_buyer_options can match lead time to this reply
    lead_time = calculate_leadtime_for_requirement(
        requirement, supplier_reply=reply, supplier_id=reply.supplier_id or None
    )
    event_repo.append(
        project.project_id,
        "LEADTIME_RECALCULATED",
        f"Lead time recalculated from supplier reply: {lead_time.expected_days} days",
        payload=lead_time.model_dump(),
        actor="leadtime_calculator",
    )

    # P1: accumulate all prior replies/lead_times then generate options from the full set
    requirement_payload = dict(project.requirement_json or {})
    requirement_payload.setdefault("supplier_replies", []).append(reply.model_dump())
    requirement_payload.setdefault("lead_time_estimates", []).append(lead_time.model_dump())

    all_replies: list[SupplierReply] = []
    for raw in requirement_payload["supplier_replies"]:
        try:
            all_replies.append(SupplierReply(**raw))
        except Exception:
            pass

    all_lead_times: list[LeadTimeEstimate] = []
    for raw in requirement_payload["lead_time_estimates"]:
        try:
            all_lead_times.append(LeadTimeEstimate(**raw))
        except Exception:
            pass

    buyer_options = generate_buyer_options(requirement, all_replies, all_lead_times, project.project_id)
    option_payloads = [option.model_dump() for option in buyer_options]
    event_repo.append(
        project.project_id,
        "BUYER_OPTIONS_GENERATED",
        f"Generated {len(buyer_options)} buyer options from {len(all_replies)} supplier replies",
        payload={"buyer_options": option_payloads},
        actor="buyer_option_agent",
    )

    requirement_payload["buyer_options"] = option_payloads
    project_repo.update_requirement(project.project_id, requirement_payload)
    if option_payloads:
        project_repo.update_selected_option(project.project_id, option_payloads[0])

    drafts_created = _create_customer_quote_email_draft(project, event, buyer_options, db) if buyer_options else []
    gltg = GLTGClient().simulate(requirement, strategy, supplier_count=len(all_replies))
    db.commit()
    return RFQExecutionResult(
        project_id=project.project_id,
        event_type="supplier_reply",
        action="buyer_options_ready" if buyer_options else "supplier_reply_parsed",
        message=f"Supplier reply parsed. {len(buyer_options)} buyer options generated. Customer email draft is pending approval.",
        strategy=strategy,
        requirement=requirement_payload,
        giraffe_context=GiraffeContext(),
        gltg_simulation=gltg,
        supplier_routing=SupplierRoutingDecision(selected_supplier_ids=[reply.supplier_id] if reply.supplier_id else []),
        drafts_created=drafts_created,
    )


def _create_customer_quote_email_draft(project, event: OpenClawEvent, buyer_options: list, db: Session) -> list[str]:
    # Supersede any pending approval drafts from earlier supplier replies so they
    # cannot be approved or sent after buyer options have been regenerated.
    DraftRepository(db).supersede_customer_quote_drafts(project.project_id)

    option_summary = "\n".join(
        f"{opt.option_label}: {opt.reasoning} | Lead time: "
        f"{opt.lead_time_estimate.expected_days if opt.lead_time_estimate else 'N/A'} days | "
        f"Price: {opt.quote.buyer_unit_price if opt.quote else 'N/A'} {opt.quote.currency if opt.quote else ''}"
        for opt in buyer_options
    )
    draft = DraftRepository(db).create(
        project.project_id,
        {
            "conversation_id": project.conversation_id or event.conversation_id,
            "channel": "email",
            "target_peer_id": project.customer_id or "",
            "target_role": "customer",
            "message_text": (
                "We have received supplier quotes. Here are the current options:\n\n"
                f"{option_summary}\n\nPlease let us know which option you prefer."
            ),
            "message_type": "text",
            "attachments_json": [],
            "status": "pending_approval",
            "created_by_agent": "buyer_option_agent",
            "notes": "draft_type=customer_quote_email generated_from=supplier_reply",
        },
    )
    ExecutionEventRepository(db).append(
        project.project_id,
        "PENDING_EMAIL_DRAFT_CREATED",
        "Customer quote email draft created from supplier reply",
        payload={"draft_id": draft.draft_id, "draft_type": "customer_quote_email"},
        actor="buyer_option_agent",
    )
    return [draft.draft_id]


def _record_non_rfq_event(event: OpenClawEvent, classification: EventClassification, db: Session) -> RFQExecutionResult:
    project = _get_or_create_project(event, classification, db)
    ExecutionEventRepository(db).append(
        project.project_id,
        "EVENT_CLASSIFIED",
        f"Inbound event classified as {classification.event_type}; no RFQ creation performed",
        payload=classification.model_dump(),
        actor="aivan_event_api",
    )
    db.commit()
    empty_strategy = RFQStrategy()
    empty_context = GiraffeContext()
    gltg = GLTGClient().simulate(BuyerRequirement(project_id=project.project_id, quantity=1), empty_strategy, 0)
    return RFQExecutionResult(
        project_id=project.project_id,
        event_type=classification.event_type,
        action="recorded_no_rfq_created",
        message=f"Event recorded as {classification.event_type}.",
        strategy=empty_strategy,
        requirement={},
        giraffe_context=empty_context,
        gltg_simulation=gltg,
        supplier_routing=SupplierRoutingDecision(),
    )
