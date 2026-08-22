from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from aivan.api.authorization import authorize_draft_action
from aivan.api.request_context import (
    RequestContext,
    actor_identity_from_context,
    apply_trusted_identity,
    resolve_request_context,
)
from aivan.api.serializers import serialize_draft
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.session import get_db

router = APIRouter()


def _request_context(request: Request) -> RequestContext:
    return resolve_request_context(request)


def _serialize_relay_receipt(receipt) -> dict:
    return {
        "receipt_id": receipt.receipt_id,
        "tenant_id": receipt.tenant_id,
        "draft_id": receipt.draft_id,
        "case_id": receipt.case_id,
        "channel": receipt.channel,
        "channel_account_id": receipt.channel_account_id,
        "conversation_id": receipt.conversation_id,
        "external_message_id": receipt.external_message_id,
        "receipt_reference": receipt.receipt_reference,
        "confirmed_by": receipt.confirmed_by,
        "source_trace_id": receipt.source_trace_id,
        "confirmed_at": str(receipt.confirmed_at),
    }


@router.get("/api/relay/outbox")
def get_relay_outbox(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_request_context),
):
    from aivan.execution.channel_policy import DeliveryMode, get_channel_capability

    drafts = DraftRepository(db).list_by_status(
        "approved_pending_send", tenant_id=context.tenant_id
    )
    items = []
    for draft in drafts:
        capability = get_channel_capability(draft.channel)
        if capability.delivery_mode != DeliveryMode.GUIDED_RELAY:
            continue
        items.append(
            {
                **serialize_draft(draft),
                "channel_account_id": draft.channel_account_id,
                "delivery_mode": capability.delivery_mode.value,
                "copy_payload": {
                    "message_text": draft.message_text,
                    "attachments": draft.attachments_json or [],
                },
                "confirm_path": f"/api/relay/{draft.draft_id}/confirm",
            }
        )
    return {"tenant_id": context.tenant_id, "outbox": items, "total": len(items)}


@router.post("/api/relay/{draft_id}/confirm")
def confirm_relay_delivery(
    draft_id: str,
    body: dict | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_request_context),
):
    from aivan.db.repositories.domain_repo import CaseDomainRepository
    from aivan.db.repositories.relay_repo import (
        RelayReceiptRepository,
        relay_idempotency_key,
    )
    from aivan.domain.roles import Capability
    from aivan.execution.channel_policy import DeliveryMode, get_channel_capability

    payload = body or {}
    repo = DraftRepository(db)
    draft = repo.get(draft_id, tenant_id=context.tenant_id)
    if draft is None:
        raise HTTPException(
            status_code=404, detail={"error": "not_found", "draft_id": draft_id}
        )
    identity = actor_identity_from_context(context, default_mode="approval")
    authorize_draft_action(
        draft=draft,
        identity=identity,
        capability=Capability.SEND_OUTBOUND,
        source_trace_id=context.trace_id,
        db=db,
    )
    capability = get_channel_capability(draft.channel)
    if capability.delivery_mode != DeliveryMode.GUIDED_RELAY:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "RELAY_NOT_AVAILABLE",
                "channel": capability.channel,
                "delivery_mode": capability.delivery_mode.value,
            },
        )
    if not context.idempotency_key:
        raise HTTPException(
            status_code=400,
            detail={"error": "IDEMPOTENCY_KEY_REQUIRED", "header": "Idempotency-Key"},
        )
    external_message_id = str(payload.get("external_message_id") or "").strip()
    receipt_reference = str(payload.get("receipt_reference") or "").strip()
    if not external_message_id and not receipt_reference:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "RELAY_RECEIPT_REQUIRED",
                "fields": ["external_message_id", "receipt_reference"],
            },
        )
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise HTTPException(
            status_code=400, detail={"error": "INVALID_RECEIPT_METADATA"}
        )

    receipts = RelayReceiptRepository(db)
    stored_key = relay_idempotency_key(context.tenant_id, context.idempotency_key)
    existing_for_key = receipts.get_for_idempotency_key(
        stored_key, tenant_id=context.tenant_id
    )
    if existing_for_key is not None and existing_for_key.draft_id != draft_id:
        raise HTTPException(
            status_code=409,
            detail={"error": "IDEMPOTENCY_KEY_REUSED", "draft_id": draft_id},
        )
    existing = receipts.get_for_draft(draft_id, tenant_id=context.tenant_id)
    if existing is not None:
        return {
            "status": "relayed",
            "idempotent_replay": True,
            "receipt": _serialize_relay_receipt(existing),
        }
    if draft.status != "approved_pending_send":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "INVALID_DRAFT_STATE",
                "status": draft.status,
                "required_status": "approved_pending_send",
            },
        )

    receipt, created = receipts.create_or_get(
        tenant_id=context.tenant_id,
        draft_id=draft.draft_id,
        case_id=draft.project_id,
        channel=capability.channel,
        channel_account_id=draft.channel_account_id,
        conversation_id=draft.conversation_id,
        external_message_id=external_message_id,
        receipt_reference=receipt_reference,
        idempotency_key=stored_key,
        confirmed_by=identity.actor_id,
        source_trace_id=context.trace_id,
        metadata_json=metadata,
    )
    if not created:
        if receipt.draft_id != draft_id:
            raise HTTPException(
                status_code=409,
                detail={"error": "IDEMPOTENCY_KEY_REUSED", "draft_id": draft_id},
            )
        return {
            "status": "relayed",
            "idempotent_replay": True,
            "receipt": _serialize_relay_receipt(receipt),
        }
    repo.mark_relayed(draft_id)
    CaseDomainRepository(db).record_audit(
        tenant_id=draft.tenant_id,
        case_id=draft.project_id,
        event_type="RELAY_DELIVERY_CONFIRMED",
        identity=identity,
        source_trace_id=context.trace_id,
        before={"draft_id": draft.draft_id, "status": "approved_pending_send"},
        after={
            "draft_id": draft.draft_id,
            "status": "relayed",
            "receipt_id": receipt.receipt_id,
        },
    )
    db.commit()
    return {
        "status": "relayed",
        "idempotent_replay": False,
        "receipt": _serialize_relay_receipt(receipt),
    }


@router.post("/api/relay/inbound")
async def relay_inbound(
    request: Request,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(_request_context),
):
    from aivan.api import main as api_main
    from aivan.db.repositories.domain_repo import CaseDomainRepository
    from aivan.db.repositories.inbound_event_repo import (
        InboundEventRepository,
        build_inbound_idempotency_key,
    )
    from aivan.execution.channel_policy import DeliveryMode, get_channel_capability
    from aivan.openclaw.event_adapter import parse_openclaw_event

    try:
        raw = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": "INVALID_JSON"}) from exc
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail={"error": "INVALID_RELAY_PAYLOAD"})
    capability = get_channel_capability(str(raw.get("channel") or ""))
    if (
        capability.delivery_mode != DeliveryMode.GUIDED_RELAY
        or not capability.supports_inbound_relay
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "RELAY_INBOUND_NOT_SUPPORTED",
                "channel": capability.channel,
                "delivery_mode": capability.delivery_mode.value,
            },
        )
    if not context.idempotency_key and not str(raw.get("message_id") or "").strip():
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INBOUND_IDENTITY_REQUIRED",
                "message": "Provide Idempotency-Key or message_id.",
            },
        )
    binding = {
        "channel_account_id": context.channel_account_id
        or str(raw.get("channel_account_id") or "").strip(),
        "conversation_id": str(raw.get("conversation_id") or "").strip(),
        "participant_actor_id": context.participant_actor_id
        or str(raw.get("actor_id") or raw.get("sender_id") or "").strip(),
    }
    missing_binding = [key for key, value in binding.items() if not value]
    if missing_binding:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "RELAY_BINDING_INCOMPLETE",
                "missing": missing_binding,
            },
        )
    event_data = api_main._normalize_invoke_payload(raw)
    event_data["source"] = "relay"
    event_data["channel"] = capability.channel
    event_data = apply_trusted_identity(event_data, context)
    event = parse_openclaw_event(event_data)
    idem_key = build_inbound_idempotency_key(
        tenant_id=context.tenant_id,
        source=event.source,
        channel=event.channel,
        channel_account_id=event.channel_account_id,
        conversation_id=event.conversation_id,
        message_id=event.message_id,
        explicit_idempotency_key=event.idempotency_key,
    )
    replayed = bool(idem_key and InboundEventRepository(db).get(idem_key))
    result = await api_main._run_skill_event_with_abort(event_data, db, request)
    if not replayed and isinstance(result, dict):
        project_id = str(result.get("project_id") or "")
        if project_id:
            CaseDomainRepository(db).record_audit(
                tenant_id=context.tenant_id,
                case_id=project_id,
                event_type="RELAY_INBOUND_ACCEPTED",
                identity=CaseDomainRepository.identity_for_event(event),
                source_trace_id=context.trace_id,
                after={
                    "channel": capability.channel,
                    "channel_account_id": event.channel_account_id,
                    "conversation_id": event.conversation_id,
                    "message_id": event.message_id,
                },
            )
            db.commit()
    if isinstance(result, dict):
        return {
            **result,
            "tenant_id": context.tenant_id,
            "trace_id": context.trace_id,
            "idempotency_key": idem_key or "",
            "idempotent_replay": replayed,
            "delivery_mode": capability.delivery_mode.value,
        }
    return result
