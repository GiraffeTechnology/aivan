from __future__ import annotations
from aivan.openclaw.contracts import OpenClawEvent

def parse_openclaw_event(data: dict) -> OpenClawEvent:
    """Parse an incoming OpenClaw event dict into an OpenClawEvent."""
    return OpenClawEvent(
        source=data.get("source", "openclaw"),
        channel=data.get("channel", ""),
        channel_account_id=data.get("channel_account_id", ""),
        conversation_id=data.get("conversation_id", ""),
        message_id=data.get("message_id", ""),
        sender_id=data.get("sender_id", ""),
        sender_display_name=data.get("sender_display_name", ""),
        message_text=data.get("message_text", ""),
        message_type=data.get("message_type", "text"),
        attachments=data.get("attachments", []),
        timestamp=data.get("timestamp", ""),
        project_id=data.get("project_id"),
        actor_id=data.get("actor_id"),
        role_context=data.get("role_context"),
        mode=data.get("mode", "auto"),
    )

def is_customer_message(event: OpenClawEvent) -> bool:
    """Return True if this looks like a customer/buyer inquiry."""
    role = (event.role_context or "").lower()
    if role in ("supplier", "seller", "m_side"):
        return False
    return role in ("", "buyer", "customer", "b_side") or event.mode == "auto"

def is_supplier_reply(event: OpenClawEvent) -> bool:
    """Return True if this looks like a supplier/seller reply."""
    role = (event.role_context or "").lower()
    return role in ("supplier", "seller", "m_side")
