from __future__ import annotations
from typing import Literal

SendMode = Literal["auto", "guided_relay"]

# Channels not listed here fall back to the legacy OpenClaw send path.
CHANNEL_SEND_MODE: dict[str, SendMode] = {
    "email":    "auto",
    "line":     "auto",
    "wechat":   "guided_relay",
    "wangwang": "guided_relay",
}


def get_send_mode(channel: str) -> SendMode | None:
    """Return the send mode for *channel*, or None for unknown channels."""
    return CHANNEL_SEND_MODE.get(channel.lower()) if channel else None
