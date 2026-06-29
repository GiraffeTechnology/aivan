from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from aivan.db.models.intake import InquiryMessage, InquirySheet
from aivan.intake.inquiry_matcher import build_match_fingerprint, match_inquiry_sheet
from aivan.intake.rfq_structuring import normalized_product, structure_inquiry_text
from aivan.openclaw.contracts import OpenClawEvent
from aivan.utils.ids import new_id


def persist_inquiry_intake(event: OpenClawEvent, db: Session) -> InquiryMessage:
    structured = structure_inquiry_text(event.message_text)
    context = {
        "source": event.source or "openclaw",
        "channel": event.channel or "unknown",
        "conversation_id": event.conversation_id or None,
        "sender_id": event.sender_id or None,
        "message_id": event.message_id or None,
    }
    decision = match_inquiry_sheet(structured, context, db)
    sheet = decision.sheet
    if sheet is None:
        sheet = _create_sheet(structured, context, decision.decision)
        db.add(sheet)
        db.flush()
    elif decision.decision == "same_existing":
        _fill_sheet_gaps(sheet, structured, context)
        sheet.updated_at = datetime.now(timezone.utc)
        db.flush()

    message = InquiryMessage(
        id=f"imsg_{new_id()}",
        sheet_id=sheet.id,
        raw_text=event.message_text or "",
        raw_event_json=event.model_dump(),
        structured_json=structured,
        source=context["source"],
        channel=context["channel"],
        conversation_id=context["conversation_id"],
        sender_id=context["sender_id"],
        message_id=context["message_id"],
        received_at=_received_at(event),
        match_decision=decision.decision,
        match_confidence=decision.confidence,
        match_reason=decision.reason,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def serialize_sheet(sheet: InquirySheet, include_messages: bool = True) -> dict:
    payload = {
        "id": sheet.id,
        "status": sheet.status,
        "source": sheet.source,
        "channel": sheet.channel,
        "conversation_id": sheet.conversation_id,
        "sender_id": sheet.sender_id,
        "normalized_product": sheet.normalized_product,
        "product_category": sheet.product_category,
        "quantity": sheet.quantity,
        "quantity_unit": sheet.quantity_unit,
        "destination": sheet.destination,
        "lead_time_days": sheet.lead_time_days,
        "delivery_deadline": sheet.delivery_deadline,
        "quality_level": sheet.quality_level,
        "material": sheet.material,
        "spec_json": sheet.spec_json,
        "match_fingerprint": sheet.match_fingerprint,
        "created_at": sheet.created_at.isoformat() if sheet.created_at else None,
        "updated_at": sheet.updated_at.isoformat() if sheet.updated_at else None,
        "message_count": len(sheet.messages),
    }
    if include_messages:
        payload["messages"] = [serialize_message(message) for message in sorted(sheet.messages, key=lambda m: m.created_at)]
    return payload


def serialize_message(message: InquiryMessage) -> dict:
    return {
        "id": message.id,
        "sheet_id": message.sheet_id,
        "raw_text": message.raw_text,
        "raw_event_json": message.raw_event_json,
        "structured_json": message.structured_json,
        "source": message.source,
        "channel": message.channel,
        "conversation_id": message.conversation_id,
        "sender_id": message.sender_id,
        "message_id": message.message_id,
        "received_at": message.received_at.isoformat() if message.received_at else None,
        "match_decision": message.match_decision,
        "match_confidence": message.match_confidence,
        "match_reason": message.match_reason,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def _create_sheet(structured: dict, context: dict, decision: str) -> InquirySheet:
    status = "temporary_unconfirmed" if decision == "uncertain_new" else "active"
    return InquirySheet(
        id=f"isheet_{new_id()}",
        status=status,
        source=context["source"],
        channel=context["channel"],
        conversation_id=context["conversation_id"],
        sender_id=context["sender_id"],
        normalized_product=normalized_product(structured) or None,
        product_category=structured.get("product_category") or None,
        quantity=structured.get("quantity"),
        quantity_unit=structured.get("quantity_unit"),
        destination=structured.get("destination") or None,
        lead_time_days=structured.get("lead_time_days"),
        delivery_deadline=structured.get("delivery_deadline"),
        quality_level=structured.get("quality_level"),
        material=structured.get("material"),
        spec_json=structured,
        match_fingerprint=build_match_fingerprint(structured, context),
    )


def _fill_sheet_gaps(sheet: InquirySheet, structured: dict, context: dict) -> None:
    field_map = {
        "normalized_product": normalized_product(structured) or None,
        "product_category": structured.get("product_category") or None,
        "quantity": structured.get("quantity"),
        "quantity_unit": structured.get("quantity_unit"),
        "destination": structured.get("destination") or None,
        "lead_time_days": structured.get("lead_time_days"),
        "delivery_deadline": structured.get("delivery_deadline"),
        "quality_level": structured.get("quality_level"),
        "material": structured.get("material"),
    }
    for field, value in field_map.items():
        if getattr(sheet, field) in (None, "") and value not in (None, ""):
            setattr(sheet, field, value)
    merged = dict(sheet.spec_json or {})
    for key, value in structured.items():
        if merged.get(key) in (None, "") and value not in (None, ""):
            merged[key] = value
    sheet.spec_json = merged or structured
    sheet.match_fingerprint = build_match_fingerprint(sheet.spec_json or structured, context)


def _received_at(event: OpenClawEvent) -> datetime:
    raw = str(event.timestamp or "").strip()
    if raw.isdigit():
        value = int(raw)
        if value > 10_000_000_000:
            value = value // 1000
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)
