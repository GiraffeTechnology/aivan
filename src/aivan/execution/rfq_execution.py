from __future__ import annotations

import logging
import os

from sqlalchemy.orm import Session

from aivan.agents.requirement_agent import structure_customer_requirement_with_llm
from aivan.agents.supplier_response_agent import parse_supplier_reply
from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.pricing.customer_quote import format_customer_quote_draft
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.event_repo import ExecutionEventRepository
from aivan.db.repositories.preference_repo import UserPreferenceRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.db.repositories.domain_repo import CaseDomainRepository
from aivan.integrations.giraffe_db import (
    GiraffeDBClient,
    GiraffeDBContextError,
    persist_rfq_gltg_graph,
)
from aivan.integrations.gltg import GLTGClient, GLTGUnavailableError
from aivan.integrations.gltg import calculate_leadtime_for_requirement
from aivan.integrations.gpm_guidance_client import GPMGuidanceUnavailableError
from aivan.integrations.language_skill import (
    LanguageNormalizationRequired, LanguageSkillUnavailable,
    canonical_english_text, canonicalize_rfq, english_provenance,
)
from aivan.schemas.leadtime import LeadTimeEstimate
from aivan.llm.gateway import llm_complete_json
from aivan.llm.policy import ExternalModelApiRequiresApprovalError, LocalModelUnavailableError
from aivan.execution.safety import (
    ExecutionGateResult,
    evaluate_requirement_readiness,
    evaluate_supplier_readiness,
)
from aivan.rfq.dependency_policy import classify_exception
from aivan.rfq.operator_reply import render_canonical_operator_reply
from aivan.openclaw.binding_store import bind_conversation, get_project_id
from aivan.openclaw.contracts import OpenClawEvent
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply
from aivan.schemas.rfq import (
    EventClassification,
    GiraffeContext,
    RFQExecutionResult,
    RFQStrategy,
    SupplierRoutingDecision,
)
from aivan.execution.event_interpretation import (
    classify_event as _classify_event,
    interpret_strategy as _interpret_strategy,
)
from aivan.execution.gpm_guidance import (
    create_stage1_gpm_guidance as _create_stage1_gpm_guidance,
)
from aivan.execution.rfq_user_control import (
    _should_use_chinese_user_message,
    build_user_control_message as _build_user_control_message,
    draft_supplier_email as _draft_supplier_email,
    owner_user_id_for_event as _owner_user_id_for_event,
    send_user_control_notification as _send_user_control_notification,
)
from aivan.execution.supplier_routing import (
    create_supplier_email_drafts as _create_supplier_email_drafts,
    select_suppliers as _select_suppliers,
)
from aivan.observability.safe_logging import log_exception_safely
from aivan.execution.conversation_history import persist_canonical_message
from aivan.execution.inbound_receipt import replay_inbound_receipt
from aivan.domain.roles import (
    BusinessRole,
    Capability,
    CaseState,
    RoleAuthorizationError,
    normalize_actor_identity,
    require_capability,
)

logger = logging.getLogger(__name__)


def _invalidate_stale_customer_quote_state(project_id: str, db: Session) -> None:
    """Invalidate an older recommendation without deleting its audit history."""

    ProjectRepository(db).update_selected_option(project_id, None)
    DraftRepository(db).supersede_customer_quote_drafts(project_id)


def classify_event(event: OpenClawEvent, db: Session) -> EventClassification:
    return _classify_event(event, db, complete_json=llm_complete_json)


def interpret_strategy(raw_text: str, context: GiraffeContext | None = None) -> RFQStrategy:
    return _interpret_strategy(raw_text, context, complete_json=llm_complete_json)


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
        tenant_id=event.tenant_id or "legacy",
        source=getattr(event, "source", "") or "",
        channel=event.channel or "",
        channel_account_id=event.channel_account_id or "",
        conversation_id=event.conversation_id or "",
        message_id=event.message_id or "",
        explicit_idempotency_key=event.idempotency_key or "",
    )
    repo = InboundEventRepository(db)
    db.info["aivan_inbound_replayed"] = False
    if idem_key:
        existing = repo.get(idem_key)
        if existing is not None:
            # Replay the stored result; create no new project/RFQ/draft/event.
            db.info["aivan_inbound_replayed"] = True
            return replay_inbound_receipt(existing, trace_id=event.source_trace_id)

    # Script shape is not language identification: Latin input may be French,
    # Spanish, German, or another language. The shared language service must
    # normalize every business intake before classification or persistence.
    try:
        canonicalization = canonicalize_rfq(
            event.message_text, source_channel=event.channel,
            tenant_id=event.tenant_id, sender_role=event.business_role or "buyer",
        )
    except LanguageSkillUnavailable:
        raise LanguageNormalizationRequired() from None
    if canonicalization is None:
        raise LanguageNormalizationRequired()
    text = canonical_english_text(canonicalization)
    # Keep caller-owned event immutable and its authenticated identity intact.
    event = event.model_copy(update={
        "message_text": text, "attachments": english_provenance(event.attachments),
    })
    claim = None
    if idem_key:
        claim, acquired = repo.claim(idem_key, tenant_id=event.tenant_id or "legacy")
        if not acquired:
            db.info["aivan_inbound_replayed"] = True
            return replay_inbound_receipt(claim, trace_id=event.source_trace_id)
    result = _create_rfq_from_event_inner(event, db, canonicalization=canonicalization)

    if claim is not None:
        repo.complete(
            claim,
            project_id=result.project_id,
            event_type=result.event_type,
            result_json=result.model_dump(),
        )
    return result


def _create_rfq_from_event_inner(
    event: OpenClawEvent, db: Session, *, canonicalization: dict | None = None,
) -> RFQExecutionResult:
    classification = classify_event(event, db)
    if classification.event_type == "supplier_reply":
        return _handle_supplier_reply_event(event, classification, db)
    if classification.event_type == "user_command":
        _require_event_capability(
            event, classification, Capability.EXECUTE_COMMAND, db,
            use_authenticated_actor=True,
        )
        _require_event_capability(
            event, classification, Capability.UPDATE_STRATEGY, db,
            use_authenticated_actor=True,
        )
    elif classification.event_type in {
        "customer_new_inquiry",
        "customer_followup",
        "customer_reply",
    }:
        _require_event_capability(event, classification, Capability.CREATE_INQUIRY, db)
    elif classification.event_type == "approval_response":
        _require_event_capability(
            event, classification, Capability.APPROVE_OUTBOUND, db,
            use_authenticated_actor=True,
        )
    if classification.event_type in {"internal_status_request", "approval_response", "unknown"}:
        return _record_non_rfq_event(event, classification, db)

    project = _get_or_create_project(event, classification, db)
    existing_requirement = _load_requirement(project.requirement_json)
    language_kwargs = {"canonicalization": canonicalization} if canonicalization else {}
    requirement = structure_customer_requirement_with_llm(
        raw_text=event.message_text,
        attachments=event.attachments,
        existing_requirement=existing_requirement,
        project_id=project.project_id,
        source_channel=event.channel,
        **language_kwargs,
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
        giraffe = GiraffeDBClient(db, tenant_id=event.tenant_id or "legacy").build_context(
            requirement=requirement,
            customer_id=project.customer_id,
            user_id=event.actor_id or event.sender_id,
        )
        strategy = interpret_strategy(event.message_text, giraffe)

        supplier_feasibility, suppliers_ready = evaluate_supplier_readiness(giraffe.suppliers)
        if not suppliers_ready:
            # No available supplier means selection is still needed. One real
            # supplier may proceed; drafts retain ordinary human approval.
            return _pending_supplier_result(
                project, event, classification, requirement, strategy,
                supplier_feasibility, giraffe.suppliers, db,
            )

        gltg = GLTGClient().simulate(
            requirement,
            strategy,
            supplier_count=len(giraffe.suppliers),
            tenant_id=project.tenant_id or event.tenant_id,
            source_trace_id=event.source_trace_id,
        )
    except (
        GiraffeDBContextError,
        GLTGUnavailableError,
        ExternalModelApiRequiresApprovalError,
        LocalModelUnavailableError,
    ) as exc:
        return _dependency_recovery_result(project, event, classification, requirement, exc, db)

    giraffe_db_graph: dict = {}
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
            "message": "giraffe-db graph persistence failed",
        }
        log_exception_safely(
            logger,
            "Failed to persist giraffe-db RFQ/GLTG graph",
            exc=exc,
            context={"project_id": project.project_id},
        )
        ExecutionEventRepository(db).append(
            project.project_id,
            "GIRAFFE_DB_GRAPH_PERSIST_FAILED",
            "Failed to persist pre-PO transaction graph; no drafts were created.",
            payload=giraffe_db_graph_error,
            actor="giraffe_db",
        )
        return _dependency_recovery_result(
            project,
            event,
            classification,
            requirement,
            RuntimeError("GIRAFFE_DB_GRAPH_PERSISTENCE_FAILED"),
            db,
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
    _learn_strategy_preference(
        event.actor_id or event.sender_id or "default",
        strategy,
        db,
        tenant_id=event.tenant_id or "legacy",
    )

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
    drafts_created = _create_supplier_email_drafts(project.project_id, event, requirement, strategy, giraffe, gltg, routing, db)
    if drafts_created:
        _advance_to_awaiting_supplier(project, event, db)

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
    user_message = render_canonical_operator_reply(result)
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


def _require_event_capability(
    event: OpenClawEvent,
    classification: EventClassification,
    capability: Capability,
    db: Session,
    *,
    use_authenticated_actor: bool = False,
):
    identity = (
        CaseDomainRepository.authenticated_identity_for_event(event)
        if use_authenticated_actor
        else CaseDomainRepository.identity_for_event(event)
    )
    try:
        require_capability(identity, capability)
    except RoleAuthorizationError as exc:
        CaseDomainRepository(db).record_audit(
            tenant_id=event.tenant_id or "legacy",
            case_id=classification.project_id or event.project_id or "",
            event_type="EVENT_ACTION_REJECTED",
            identity=identity,
            source_trace_id=event.source_trace_id,
            rejection_reason=exc.reason,
        )
        db.commit()
        raise
    return identity


def _automation_identity():
    return normalize_actor_identity(
        actor_id="aivan-workflow",
        business_role=BusinessRole.ADMIN,
        execution_mode="auto",
        authorization_basis="configured_case_workflow_policy",
    )


def _advance_to_awaiting_supplier(project, event: OpenClawEvent, db: Session) -> None:
    repo = CaseDomainRepository(db)
    automation = _automation_identity()
    if project.case_state == CaseState.INQUIRY.value:
        repo.transition_case(
            project=project,
            after=CaseState.SOURCING,
            identity=automation,
            source_trace_id=event.source_trace_id,
        )
    if project.case_state == CaseState.SOURCING.value:
        repo.transition_case(
            project=project,
            after=CaseState.AWAITING_SUPPLIER,
            identity=automation,
            source_trace_id=event.source_trace_id,
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
        gltg_simulation=None,
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

    # Ready facts must survive supplier selection and a later conversation.
    payload = {**(project.requirement_json or {}), **requirement.model_dump(), "strategy": strategy.model_dump()}
    ProjectRepository(db).update_requirement(project.project_id, payload)
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
        gltg_simulation=None,
        supplier_routing=SupplierRoutingDecision(),
        drafts_created=[],
        user_control_message=message,
    )


def _dependency_recovery_result(project, event, classification, requirement, exc, db):
    """Structured recovery for a dependency failure (never a generic backend error)."""
    # Preserve parsed facts and prior case history; failure is not a saved result.
    payload = {**(project.requirement_json or {}), **requirement.model_dump()}
    ProjectRepository(db).update_requirement(project.project_id, payload)
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
        gltg_simulation=None,
        supplier_routing=SupplierRoutingDecision(),
        drafts_created=[],
        user_control_message=message,
    )


def _get_or_create_project(event: OpenClawEvent, classification: EventClassification, db: Session):
    repo = ProjectRepository(db)
    project_id = classification.project_id or event.project_id or get_project_id(event.conversation_id)
    project = repo.get(project_id, tenant_id=event.tenant_id) if project_id else None
    if project:
        bind_conversation(event.conversation_id, project.project_id)
        _bind_event_to_case(project, event, db)
        return project
    project = repo.get_by_conversation(event.conversation_id, tenant_id=event.tenant_id)
    if project:
        bind_conversation(event.conversation_id, project.project_id)
        _bind_event_to_case(project, event, db)
        return project
    project = repo.create(
        conversation_id=event.conversation_id,
        customer_id=event.sender_id,
        channel=event.channel,
        channel_account_id=event.channel_account_id,
        customer_display_name=event.sender_display_name,
        tenant_id=event.tenant_id or "legacy",
    )
    bind_conversation(event.conversation_id, project.project_id)
    _bind_event_to_case(project, event, db)
    ExecutionEventRepository(db).append(
        project.project_id,
        "PROJECT_CREATED",
        f"Created RFQ project for {event.sender_display_name or event.sender_id or 'incoming event'}",
        actor="aivan_event_api",
    )
    return project


def _bind_event_to_case(project, event: OpenClawEvent, db: Session):
    """Attach the event's role-specific thread and participant to an existing Case."""

    project.source_trace_id = event.source_trace_id or project.source_trace_id
    conversation, participant, message, _created = CaseDomainRepository(
        db
    ).bind_inbound_event(project.project_id, event)
    persist_canonical_message(db, project=project, event=event, message=message)
    db.flush()
    return conversation, participant, message


def _load_requirement(payload: dict | None) -> BuyerRequirement | None:
    if not payload:
        return None
    try:
        return BuyerRequirement(**{k: v for k, v in payload.items() if k in BuyerRequirement.model_fields})
    except Exception:
        return None


def _learn_strategy_preference(user_id: str, strategy: RFQStrategy, db: Session, *, tenant_id: str = "legacy") -> None:
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
        tenant_id=tenant_id,
    )


def _handle_supplier_reply_event(event: OpenClawEvent, classification: EventClassification, db: Session) -> RFQExecutionResult:
    project_id = classification.project_id or event.project_id
    project = (
        ProjectRepository(db).get(project_id, tenant_id=event.tenant_id or "legacy")
        if project_id
        else None
    )
    if project is None or not classification.validated_project_attachment:
        identity = CaseDomainRepository.identity_for_event(event)
        CaseDomainRepository(db).record_audit(
            tenant_id=event.tenant_id or "legacy",
            case_id=project_id or "",
            event_type="SUPPLIER_REPLY_REJECTED",
            identity=identity,
            source_trace_id=event.source_trace_id,
            rejection_reason="supplier_reply_requires_validated_case_binding",
        )
        db.commit()
        raise RoleAuthorizationError(
            "SUPPLIER_CASE_BINDING_REQUIRED",
            "Supplier reply must be attached to an existing validated Case thread",
            reason="supplier_reply_requires_validated_case_binding",
        )
    project = ProjectRepository(db).get_for_update(
        project.project_id, tenant_id=event.tenant_id or "legacy"
    )
    if project is None:
        raise RoleAuthorizationError(
            "SUPPLIER_CASE_BINDING_REQUIRED",
            "Supplier reply must be attached to an existing validated Case thread",
            reason="supplier_reply_case_disappeared_before_lock",
        )
    supplier_identity = _require_event_capability(
        event, classification, Capability.RESPOND_AS_SUPPLIER, db
    )
    bind_conversation(event.conversation_id, project.project_id)
    _bind_event_to_case(project, event, db)
    if project.case_state == CaseState.INQUIRY.value and project.requirement_json:
        _advance_to_awaiting_supplier(project, event, db)
    if project.case_state == CaseState.AWAITING_SUPPLIER.value:
        CaseDomainRepository(db).transition_case(
            project=project,
            after=CaseState.SUPPLIER_REPLIED,
            identity=supplier_identity,
            source_trace_id=event.source_trace_id,
        )
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
    # A model cannot supply this identity. Bind the actual inbound message,
    # already authenticated and case-bound, to the persisted parsed revision.
    reply.source_event_id = ":".join((event.source or "", event.channel or "",
        event.channel_account_id or "", event.conversation_id or "", event.message_id or ""))
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
        return RFQExecutionResult(
            project_id=project.project_id,
            event_type="supplier_reply",
            action="supplier_reply_requires_requirement",
            message="Supplier reply parsed, but no project requirement was available for buyer option generation.",
            strategy=empty_strategy,
            requirement={},
            giraffe_context=GiraffeContext(),
            gltg_simulation=None,
            supplier_routing=SupplierRoutingDecision(selected_supplier_ids=[reply.supplier_id] if reply.supplier_id else []),
        )

    strategy_payload = (project.requirement_json or {}).get("strategy") or {}
    try:
        strategy = RFQStrategy(**strategy_payload)
    except Exception:
        strategy = RFQStrategy()

    # P2: carry supplier_id so generate_buyer_options can match lead time to this reply
    try:
        lead_time = calculate_leadtime_for_requirement(
            requirement,
            supplier_reply=reply,
            supplier_id=reply.supplier_id or None,
            tenant_id=project.tenant_id or event.tenant_id,
            source_trace_id=event.source_trace_id,
        )
    except GLTGUnavailableError as exc:
        _invalidate_stale_customer_quote_state(project.project_id, db)
        return _dependency_recovery_result(
            project, event, classification, requirement, exc, db
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

    try:
        gltg = GLTGClient().simulate(
            requirement,
            strategy,
            supplier_count=len(all_replies),
            supplier_id=reply.supplier_id or None,
            tenant_id=project.tenant_id or event.tenant_id,
            source_trace_id=event.source_trace_id,
        )
    except GLTGUnavailableError as exc:
        _invalidate_stale_customer_quote_state(project.project_id, db)
        return _dependency_recovery_result(
            project, event, classification, requirement, exc, db
        )
    gpm_guidance = None
    if buyer_options:
        try:
            gpm_guidance = _create_stage1_gpm_guidance(
                project=project,
                event=event,
                requirement=requirement,
                selected_option=buyer_options[0],
                replies=all_replies,
                gltg_result=gltg,
            )
        except GPMGuidanceUnavailableError as exc:
            error_code = str(exc) or "GPM_GUIDANCE_UNAVAILABLE"
            requirement_payload["buyer_options"] = option_payloads
            requirement_payload["gpm_guidance"] = {
                "status": "unavailable",
                "error": error_code,
            }
            project_repo.update_requirement(project.project_id, requirement_payload)
            _invalidate_stale_customer_quote_state(project.project_id, db)
            event_repo.append(
                project.project_id,
                "GPM_GUIDANCE_UNAVAILABLE",
                "GPM execution recommendation is unavailable; approval draft was not created",
                payload={"error": error_code},
                actor="gpm_guidance_client",
            )
            db.commit()
            return RFQExecutionResult(
                project_id=project.project_id,
                event_type="supplier_reply",
                action="gpm_guidance_unavailable",
                message="Supplier reply parsed, but the execution recommendation is unavailable. No approval draft was created.",
                strategy=strategy,
                requirement=requirement_payload,
                giraffe_context=GiraffeContext(),
                gltg_simulation=gltg,
                supplier_routing=SupplierRoutingDecision(
                    selected_supplier_ids=[reply.supplier_id] if reply.supplier_id else []
                ),
                drafts_created=[],
            )
        option_payloads[0]["gpm_guidance"] = gpm_guidance
        requirement_payload["gpm_guidance"] = gpm_guidance
        event_repo.append(
            project.project_id,
            "GPM_GUIDANCE_CREATED",
            "GPM advisory execution recommendation created; human approval remains required",
            payload=gpm_guidance,
            actor="gpm_guidance_client",
        )

    requirement_payload["buyer_options"] = option_payloads
    project_repo.update_requirement(project.project_id, requirement_payload)
    if option_payloads:
        project_repo.update_selected_option(project.project_id, option_payloads[0])

    drafts_created = (
        _create_customer_quote_email_draft(
            project,
            event,
            buyer_options,
            db,
            gpm_guidance=gpm_guidance,
        )
        if buyer_options
        else []
    )
    if drafts_created and project.case_state == CaseState.SUPPLIER_REPLIED.value:
        CaseDomainRepository(db).transition_case(
            project=project,
            after=CaseState.AWAITING_APPROVAL,
            identity=_automation_identity(),
            source_trace_id=event.source_trace_id,
        )
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


def _create_customer_quote_email_draft(
    project,
    event: OpenClawEvent,
    buyer_options: list,
    db: Session,
    *,
    gpm_guidance: dict | None = None,
) -> list[str]:
    # Supersede any pending approval drafts from earlier supplier replies so they
    # cannot be approved or sent after buyer options have been regenerated.
    DraftRepository(db).supersede_customer_quote_drafts(project.project_id)

    message_text = format_customer_quote_draft(
        buyer_options,
        _load_requirement(project.requirement_json),
        gpm_guidance=gpm_guidance,
    )
    draft = DraftRepository(db).create(
        project.project_id,
        {
            "tenant_id": project.tenant_id or event.tenant_id or "legacy",
            "conversation_id": project.conversation_id or event.conversation_id,
            "channel": project.channel or "email",
            "channel_account_id": project.channel_account_id or "",
            "target_peer_id": project.customer_id or "",
            "target_role": "customer",
            "message_text": message_text,
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
    return RFQExecutionResult(
        project_id=project.project_id,
        event_type=classification.event_type,
        action="recorded_no_rfq_created",
        message=f"Event recorded as {classification.event_type}.",
        strategy=empty_strategy,
        requirement={},
        giraffe_context=empty_context,
        gltg_simulation=None,
        supplier_routing=SupplierRoutingDecision(),
    )
