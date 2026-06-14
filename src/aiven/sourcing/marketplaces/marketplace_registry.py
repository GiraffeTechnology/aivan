from __future__ import annotations
from typing import Callable
from aiven.sourcing.marketplaces.marketplace_models import SearchResult

_connectors: dict[str, Callable] = {}

def register_connector(platform_id: str, fn: Callable) -> None:
    _connectors[platform_id] = fn

def get_connector(platform_id: str) -> Callable | None:
    return _connectors.get(platform_id)

def list_connectors() -> list[str]:
    return list(_connectors.keys())

def _init_default_connectors():
    from aiven.sourcing.marketplaces.alibaba_connector import search_alibaba
    register_connector("alibaba", lambda q, **kw: search_alibaba(q, platform="alibaba", **kw))
    register_connector("1688", lambda q, **kw: search_alibaba(q, platform="1688", **kw))
    register_connector("aliexpress", lambda q, **kw: search_alibaba(q, platform="aliexpress", **kw))
    from aiven.sourcing.marketplaces.openclaw_marketplace_connector import search_via_openclaw
    register_connector("openclaw_marketplace", lambda q, **kw: search_via_openclaw(q, **kw))

_init_default_connectors()

def search_platform(platform_id: str, query: str, **kwargs) -> SearchResult:
    connector = get_connector(platform_id)
    if connector is None:
        return SearchResult(query=query, platform=platform_id, connector_mode="not_found", error=f"No connector for platform: {platform_id}")
    return connector(query, **kwargs)
