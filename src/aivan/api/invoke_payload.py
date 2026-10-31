"""Normalize supported inbound skill payloads without executing business actions."""
from __future__ import annotations

import uuid


def _first_non_empty(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_invoke_payload(raw: dict) -> dict:
    """Normalize any supported /invoke body into a native OpenClaw event dict.

    Accepts three shapes and maps them onto the fields parse_openclaw_event reads,
    preserving project_id / role_context so follow-up supplier/buyer turns attach to
    the existing project instead of being misclassified as a new RFQ:
      - OpenClaw event   : {message_text, conversation_id, ...}  (native, passthrough)
      - OpenClaw standard: {session_id, user_input, context}
      - WeChat webhook   : {content, from_user, room_id, msg_type}
    """
    if not isinstance(raw, dict):
        raise ValueError("payload must be a JSON object")

    # Native OpenClaw event — already in the shape the adapter expects.
    if "message_text" in raw:
        return dict(raw)

    # OpenClaw standard skill invocation.
    if "user_input" in raw:
        context = raw.get("context")
        if not isinstance(context, dict):
            context = {}
        event = {
            "source": "openclaw",
            "channel": _first_non_empty(context.get("channel")) or "openclaw",
            "conversation_id": _first_non_empty(raw.get("session_id"), context.get("conversation_id"))
            or str(uuid.uuid4()),
            "sender_id": _first_non_empty(context.get("sender_id")) or "openclaw-user",
            "message_text": raw.get("user_input") or "",
            "message_type": "text",
            "mode": _first_non_empty(context.get("mode")) or "auto",
        }
        # Preserve provider routing/replay identity; authentication and role
        # authority still come from apply_trusted_identity after normalization.
        for key in ("message_id", "channel_account_id", "idempotency_key", "project_id"):
            value = _first_non_empty(context.get(key), raw.get(key))
            if value:
                event[key] = value
        if _first_non_empty(context.get("role_context")):
            event["role_context"] = context["role_context"]
        return event

    # WeChat webhook delivery.
    if "content" in raw:
        event = {
            "source": "wechat",
            "channel": "wechat",
            "conversation_id": _first_non_empty(raw.get("room_id"), raw.get("from_user"))
            or str(uuid.uuid4()),
            "sender_id": _first_non_empty(raw.get("from_user")) or "wechat-user",
            "message_text": raw.get("content") or "",
            "message_type": _first_non_empty(raw.get("msg_type")) or "text",
            "mode": "auto",
        }
        for key in ("message_id", "channel_account_id", "idempotency_key", "project_id"):
            value = _first_non_empty(raw.get(key))
            if value:
                event[key] = value
        return event

    raise ValueError(f"unrecognized payload keys: {sorted(raw.keys())}")


