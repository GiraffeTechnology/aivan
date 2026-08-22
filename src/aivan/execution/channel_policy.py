from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

from aivan.db.models.inquiry import InquiryDraftRecord

COUNTERPARTY_ROLES = {"customer", "supplier", "buyer", "seller"}
EMAIL_CHANNELS = {"email", "smtp"}
PERSONAL_IM_CHANNELS = {
    "wechat",
    "weixin",
    "line",
    "whatsapp",
    "telegram",
    "signal",
    "personal_im",
}
USER_CONTROL_CHANNELS = PERSONAL_IM_CHANNELS | {"im", "openclaw-im", "user-im"}


class DeliveryMode(StrEnum):
    AUTO_SEND = "auto_send"
    GUIDED_RELAY = "guided_relay"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ChannelCapability:
    channel: str
    delivery_mode: DeliveryMode
    aliases: tuple[str, ...] = ()
    requires_human_approval: bool = True
    supports_inbound_relay: bool = False

    def as_dict(self) -> dict:
        value = asdict(self)
        value["delivery_mode"] = self.delivery_mode.value
        value["aliases"] = list(self.aliases)
        return value


# Stage 4 delivery contract. Unknown channels fail closed as unsupported.
CHANNEL_CAPABILITY_REGISTRY: dict[str, ChannelCapability] = {
    "email": ChannelCapability(
        "email", DeliveryMode.AUTO_SEND, aliases=("smtp",)
    ),
    "line": ChannelCapability("line", DeliveryMode.AUTO_SEND),
    "wechat": ChannelCapability(
        "wechat",
        DeliveryMode.GUIDED_RELAY,
        aliases=("weixin", "we-chat"),
        supports_inbound_relay=True,
    ),
    "wangwang": ChannelCapability(
        "wangwang",
        DeliveryMode.GUIDED_RELAY,
        aliases=("aliwangwang", "ali-wangwang"),
        supports_inbound_relay=True,
    ),
    "whatsapp": ChannelCapability(
        "whatsapp", DeliveryMode.UNSUPPORTED, aliases=("whats-app",)
    ),
}

_CHANNEL_ALIASES = {
    alias: capability.channel
    for capability in CHANNEL_CAPABILITY_REGISTRY.values()
    for alias in (capability.channel, *capability.aliases)
}


def normalize_channel(channel: str | None) -> str:
    normalized = (channel or "").strip().lower().replace("_", "-")
    return _CHANNEL_ALIASES.get(normalized, normalized)


def get_channel_capability(channel: str | None) -> ChannelCapability:
    normalized = normalize_channel(channel)
    return CHANNEL_CAPABILITY_REGISTRY.get(
        normalized,
        ChannelCapability(normalized or "unknown", DeliveryMode.UNSUPPORTED),
    )


def list_channel_capabilities() -> list[dict]:
    return [
        CHANNEL_CAPABILITY_REGISTRY[channel].as_dict()
        for channel in ("email", "line", "wechat", "wangwang", "whatsapp")
    ]


def is_email_channel(channel: str | None) -> bool:
    return normalize_channel(channel) in EMAIL_CHANNELS


def is_personal_im_channel(channel: str | None) -> bool:
    normalized = normalize_channel(channel)
    return normalized in PERSONAL_IM_CHANNELS or normalized in {"we-chat", "whats-app"}


def is_counterparty_role(role: str | None) -> bool:
    return (role or "").strip().lower() in COUNTERPARTY_ROLES


def validate_counterparty_draft_channel(channel: str | None, target_role: str | None) -> None:
    """Direct transport is allowed only for channels registered as auto-send."""
    if not is_counterparty_role(target_role):
        return
    capability = get_channel_capability(channel)
    if capability.delivery_mode != DeliveryMode.AUTO_SEND:
        raise ValueError(
            "AIVAN channel policy blocks direct counterparty delivery over "
            f"'{channel or 'unknown'}' (mode={capability.delivery_mode.value})."
        )


def validate_draft_send_policy(draft: InquiryDraftRecord) -> None:
    validate_counterparty_draft_channel(draft.channel, draft.target_role)
