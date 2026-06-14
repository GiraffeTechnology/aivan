from __future__ import annotations
import os
from aiven.openclaw.contracts import OpenClawSendRequest, OpenClawSendResponse
from aiven.openclaw.client import get_openclaw_client
from aiven.openclaw.account_delegation import check_permission

SUPPORTED_IM_CHANNELS = [
    "openclaw-wangwang",
    "openclaw-1688-im",
    "openclaw-alibaba-im",
    "openclaw-marketplace-im",
    "openclaw-email",
    "openclaw-web",
]

def send_seller_im(
    db_session,
    account_connection_id: str,
    channel: str,
    target_peer_id: str,
    message_text: str,
    conversation_id: str = "",
    attachments: list = None,
    require_approval: bool = True,
) -> dict:
    """Send a marketplace IM message to a seller through OpenClaw. Always requires approval."""
    if require_approval:
        raise ValueError("All outbound messages must be human-approved before sending. Use the draft approval flow.")

    if channel not in SUPPORTED_IM_CHANNELS:
        return {"success": False, "error": f"Unsupported channel: {channel}. Supported: {SUPPORTED_IM_CHANNELS}"}

    has_permission = check_permission(db_session, account_connection_id, "send_approved_messages")
    if not has_permission:
        return {"success": False, "error": f"Account {account_connection_id} does not have send_approved_messages permission or is revoked."}

    client = get_openclaw_client()
    request = OpenClawSendRequest(
        channel=channel,
        channel_account_id=account_connection_id,
        conversation_id=conversation_id or f"conv_{target_peer_id}",
        target_peer_id=target_peer_id,
        message_text=message_text,
        message_type="text",
        attachments=attachments or [],
        account_connection_id=account_connection_id,
    )
    response = client.send_message(request)
    return {"success": response.success, "message_id": response.message_id, "error": response.error}

def check_account_reauth_status(account_connection_id: str) -> dict:
    """Check if account needs re-authentication (e.g., WangWang session expired)."""
    client = get_openclaw_client()
    status = client.check_account_status(account_connection_id)
    if status.get("status") in ("expired", "reauth_required"):
        return {"needs_reauth": True, "status": status.get("status"), "account_connection_id": account_connection_id}
    return {"needs_reauth": False, "status": status.get("status", "connected"), "account_connection_id": account_connection_id}
