from __future__ import annotations
import os
from aivan.sourcing.marketplaces.marketplace_models import SearchResult

def search_via_openclaw(query: str, platform: str = "openclaw_marketplace", account_connection_id: str = "", limit: int = 10) -> SearchResult:
    mock_mode = os.environ.get("OPENCLAW_MOCK_MODE", "true").lower() == "true"
    marketplace_enabled = os.environ.get("OPENCLAW_MARKETPLACE_ENABLED", "true").lower() == "true"

    if not marketplace_enabled:
        return SearchResult(query=query, platform=platform, connector_mode="disabled", error="OpenClaw marketplace not enabled")

    if mock_mode:
        from aivan.sourcing.marketplaces.alibaba_connector import search_alibaba_mock
        result = search_alibaba_mock(query, platform="openclaw_marketplace", limit=limit)
        result.connector_mode = "openclaw_mock"
        return result

    base_url = os.environ.get("OPENCLAW_BASE_URL", "")
    if not base_url:
        return SearchResult(query=query, platform=platform, connector_mode="not_configured", error="OPENCLAW_BASE_URL not set")

    try:
        import httpx
        endpoint = os.environ.get("OPENCLAW_MARKETPLACE_SEARCH_ENDPOINT", "/marketplaces/search")
        api_key = os.environ.get("OPENCLAW_API_KEY", "")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-OpenClaw-Key"] = api_key
        payload = {"query": query, "platform": platform, "limit": limit, "account_connection_id": account_connection_id}
        response = httpx.post(f"{base_url}{endpoint}", json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        from aivan.sourcing.marketplaces.supplier_candidate_normalizer import normalize_candidate
        candidates = [normalize_candidate(c, platform) for c in data.get("candidates", [])]
        return SearchResult(query=query, platform=platform, candidates=candidates, total_found=data.get("total_found", len(candidates)), connector_mode="openclaw_live")
    except Exception as e:
        return SearchResult(query=query, platform=platform, connector_mode="error", error=str(e))
