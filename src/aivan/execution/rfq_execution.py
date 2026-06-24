from __future__ import annotations

from sqlalchemy.orm import Session

from aivan.agents.requirement_agent import structure_customer_requirement_with_llm
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.event_repo import ExecutionEventRepository
from aivan.db.repositories.preference_repo import UserPreferenceRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.integrations.giraffe_db import GiraffeDBClient
from aivan.integrations.gltg import GLTGClient
from aivan.llm.gateway import llm_complete_json
from aivan.openclaw.binding_store import bind_conversation, get_project_id
from aivan.openclaw.client import get_openclaw_client
from aivan.openclaw.contracts import OpenClawEvent
from aivan.openclaw.contracts import OpenClawSendRequest
from aivan.execution.channel_policy import USER_CONTROL_CHANNELS, normalize_channel
from aivan.openclaw.event_adapter import is_supplier_reply
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.rfq import (
    EventClassification,
    FallbackTrigger,
    GiraffeContext,
    RFQExecutionResult,
    RFQStrategy,
    SupplierRoutingDecision,
)

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
    if not raw or raw.get("priority") not in {"speed", "price", "quality", "reliability", "balanced"}:
        raw = _fallback_strategy(raw_text).model_dump()
    return RFQStrategy(**raw)


def create_rfq_from_event(event: OpenClawEvent, db: Session) -> RFQExecutionResult:
    classification = classify_event(event, db)
    if classification.event_type in {"supplier_reply", "internal_status_request", "approval_response", "unknown"}:
        return _record_non_rfq_event(event, classification, db)

    project = _get_or_create_project(event, classification, db)
    existing_requirement = _load_requirement(project.requirement_json)
    requirement = structure_customer_requirement_with_llm(
        raw_text=event.message_text,
        attachments=event.attachments,
        existing_requirement=existing_requirement,
        project_id=project.project_id,
    )

    strategy = interpret_strategy(event.message_text)
    giraffe = GiraffeDBClient(db).build_context(
        requirement=requirement,
        customer_id=project.customer_id,
        user_id=event.actor_id or event.sender_id,
    )
    strategy = interpret_strategy(event.message_text, giraffe)
    gltg = GLTGClient().simulate(requirement, strategy, supplier_count=len(giraffe.suppliers))
    routing = _select_suppliers(giraffe, strategy)

    project_payload = requirement.model_dump()
    project_payload["strategy"] = strategy.model_dump()
    project_payload["giraffe_context_summary"] = {
        "known_suppliers": len(giraffe.suppliers),
        "risk_flags": len(giraffe.risk_flags),
    }
    project_payload["gltg_simulation"] = gltg.model_dump()
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

    drafts_created = _create_supplier_email_drafts(project.project_id, event, requirement, strategy, giraffe, gltg, routing, db)
    user_message = _build_user_control_message(requirement, strategy, gltg, routing, drafts_created)
    user_notification = _send_user_control_notification(project.project_id, event, user_message, db)
    event_repo.append(
        project.project_id,
        "USER_CONTROL_APPROVAL_REQUESTED",
        "Prepared user IM approval summary",
        payload={"message_text": user_message, "draft_ids": drafts_created, "notification": user_notification},
        actor="aivan",
    )
    db.commit()

    return RFQExecutionResult(
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
        user_control_message=user_message,
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
    channel, target_peer_id = _user_control_channel_and_target(event)
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
            "status": "approved",
            "created_by_agent": "aivan_user_control",
            "notes": "draft_type=approval_request_im",
        },
    )
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


def _user_control_channel_and_target(event: OpenClawEvent) -> tuple[str, str]:
    role = (event.role_context or "").lower()
    normalized_channel = normalize_channel(event.channel)
    if role in {"user", "owner", "operator", "sales", "salesperson"} or event.mode in {"user", "command"}:
        return event.channel or "im", event.sender_id or event.actor_id or "user"
    if normalized_channel in USER_CONTROL_CHANNELS:
        return event.channel or "im", event.actor_id or event.sender_id or "user"
    return "im", event.actor_id or "user"


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


def _build_user_control_message(
    requirement: BuyerRequirement,
    strategy: RFQStrategy,
    gltg,
    routing: SupplierRoutingDecision,
    drafts_created: list[str],
) -> str:
    return (
        f"RFQ ready for approval: {requirement.quantity or 'TBD'} {requirement.quantity_unit} "
        f"{requirement.color} {requirement.product_type or requirement.category} to {requirement.destination or 'TBD'}. "
        f"Strategy={strategy.priority}/{strategy.supplier_scope}, GLTG {strategy.lead_time_confidence}="
        f"{gltg.selected_confidence_days} days, deadline risk={gltg.deadline_risk_level}. "
        f"{len(routing.selected_supplier_ids)} supplier email drafts are pending approval: {', '.join(drafts_created)}."
    )


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
