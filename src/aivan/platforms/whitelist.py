from __future__ import annotations
from aivan.platforms.models import TrustedPlatform
from aivan.utils.time_utils import utcnow_iso

BUILT_IN_PLATFORMS: dict[str, TrustedPlatform] = {
    "alibaba": TrustedPlatform(
        platform_id="alibaba",
        display_name="Alibaba / 1688 / Alibaba.com",
        status="built_in",
        domain_patterns=["alibaba.com", "1688.com"],
        supported_channels=["wangwang", "openclaw-wangwang", "openclaw-1688-im", "openclaw-alibaba-im"],
        supported_connectors=["alibaba", "1688", "openclaw_marketplace"],
        allow_marketplace_search=True,
        allow_openclaw_account_management=True,
        allow_seller_im=True,
        risk_weight_modifier=0.85,
        built_in=True,
        user_confirmed=True,
        created_at=utcnow_iso(),
        updated_at=utcnow_iso(),
        notes="Built-in trusted platform. Users can connect Alibaba/1688 accounts through OpenClaw.",
    ),
    "aliexpress": TrustedPlatform(
        platform_id="aliexpress",
        display_name="AliExpress",
        status="built_in",
        domain_patterns=["aliexpress.com"],
        supported_channels=["openclaw-marketplace-im", "openclaw-email"],
        supported_connectors=["aliexpress", "openclaw_marketplace"],
        allow_marketplace_search=True,
        allow_openclaw_account_management=True,
        allow_seller_im=True,
        risk_weight_modifier=0.9,
        built_in=True,
        user_confirmed=True,
        created_at=utcnow_iso(),
        updated_at=utcnow_iso(),
        notes="Built-in trusted platform.",
    ),
}

def get_built_in_platforms() -> dict[str, TrustedPlatform]:
    return dict(BUILT_IN_PLATFORMS)

def is_built_in(platform_id: str) -> bool:
    return platform_id in BUILT_IN_PLATFORMS
