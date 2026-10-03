"""Inbound event classification and RFQ strategy interpretation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from aivan.db.repositories.domain_repo import CaseDomainRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.openclaw.contracts import OpenClawEvent
from aivan.openclaw.event_adapter import is_supplier_reply
from aivan.schemas.rfq import EventClassification, FallbackTrigger, GiraffeContext, RFQStrategy
from aivan.utils.env import env_bool


CompleteJson = Callable[[str, str, str, dict[str, Any]], dict[str, Any]]

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


def classify_event(
    event: OpenClawEvent,
    db: Session,
    *,
    complete_json: CompleteJson,
) -> EventClassification:
    project_repo = ProjectRepository(db)
    validated_project_id = (
        event.project_id
        if event.project_id and project_repo.get(event.project_id, tenant_id=event.tenant_id)
        else None
    )
    if not validated_project_id and event.conversation_id:
        project = project_repo.get_by_conversation(
            event.conversation_id, tenant_id=event.tenant_id
        )
        if project:
            validated_project_id = project.project_id
    if not validated_project_id and event.conversation_id:
        bound_case_id = CaseDomainRepository(db).resolve_case_id_for_conversation(
            tenant_id=event.tenant_id or "legacy",
            external_conversation_id=event.conversation_id,
            channel=event.channel,
            channel_account_id=event.channel_account_id,
        )
        if bound_case_id and project_repo.get(
            bound_case_id, tenant_id=event.tenant_id or "legacy"
        ):
            validated_project_id = bound_case_id

    fallback = fallback_event_type(event, bool(validated_project_id))
    if fallback != "unknown" and not env_bool("AIVAN_EVENT_CLASSIFICATION_LLM_ENABLED"):
        return EventClassification(
            event_type=fallback,
            confidence=0.7,
            reason="deterministic fallback classification",
            project_id=validated_project_id,
            validated_project_attachment=bool(validated_project_id),
        )

    schema_hint = {
        "event_type": (
            "user_command | customer_new_inquiry | customer_followup | customer_reply | "
            "supplier_reply | internal_status_request | approval_response | unknown"
        ),
        "confidence": 0.0,
        "reason": "",
    }
    user_prompt = (
        f"channel={event.channel}\nrole_context={event.role_context}\n"
        f"mode={event.mode}\nmessage={event.message_text}\n"
        f"validated_project_id={validated_project_id or ''}"
    )
    try:
        raw = complete_json(
            "aivan_event_classification", CLASSIFICATION_SYSTEM, user_prompt, schema_hint
        )
    except Exception:
        raw = {}
    allowed_types = EventClassification.model_fields["event_type"].annotation.__args__
    event_type = raw.get("event_type") if raw.get("event_type") in allowed_types else fallback
    return EventClassification(
        event_type=event_type or fallback,
        confidence=float(raw.get("confidence") or (0.7 if fallback != "unknown" else 0.3)),
        reason=raw.get("reason") or "deterministic fallback classification",
        project_id=validated_project_id,
        validated_project_attachment=bool(validated_project_id),
    )


def interpret_strategy(
    raw_text: str,
    context: GiraffeContext | None = None,
    *,
    complete_json: CompleteJson,
) -> RFQStrategy:
    if not env_bool("AIVAN_STRATEGY_LLM_ENABLED"):
        return fallback_strategy(raw_text)

    schema_hint = RFQStrategy().model_dump()
    context_keys = list((context or GiraffeContext()).model_dump().keys())
    user_prompt = f"User instruction:\n{raw_text}\n\nAIVAN context keys: {context_keys}"
    try:
        raw = complete_json(
            "aivan_strategy_interpretation", STRATEGY_SYSTEM, user_prompt, schema_hint
        )
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    if not (set(raw) & set(RFQStrategy.model_fields)):
        return fallback_strategy(raw_text)
    try:
        return RFQStrategy(**raw)
    except Exception:
        return fallback_strategy(raw_text)


def fallback_event_type(event: OpenClawEvent, has_project: bool) -> str:
    text = (event.message_text or "").lower()
    role = (event.business_role or event.role_context or "").lower()
    if is_supplier_reply(event):
        return "supplier_reply"
    if any(word in text for word in ["approve", "approved", "同意", "批准", "发送", "send it"]):
        return "approval_response"
    if any(word in text for word in ["status", "进度", "状态"]):
        return "internal_status_request"
    if role in {
        "user", "owner", "operator", "sales", "salesperson", "procurement",
        "follow_up", "qc", "logistics", "admin", "approver",
    } or event.mode in {"user", "command"}:
        return "user_command"
    if role in {"buyer", "customer", "b_side"}:
        return "customer_followup" if has_project else "customer_new_inquiry"
    if event.channel in {"wechat", "line", "whatsapp", "im", "openclaw-im"}:
        return "user_command"
    return "customer_followup" if has_project else "customer_new_inquiry"


def fallback_strategy(raw_text: str) -> RFQStrategy:
    text = (raw_text or "").lower()
    urgent = any(token in text for token in ["urgent", "asap", "急", "很急", "赶"])
    known = any(
        token in text
        for token in ["known", "familiar", "old supplier", "老供应商", "熟悉供应商", "靠谱"]
    )
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
