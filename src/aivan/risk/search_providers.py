from __future__ import annotations
import os
from aivan.risk.models import SearchResult, FetchedPage
from aivan.risk.web_search import WebSearchProvider, MockWebSearchProvider
from aivan.utils.time_utils import utcnow_iso

class OpenClawSearchProvider(WebSearchProvider):
    provider_name = "openclaw_search"

    def search(self, query: str, limit: int = 10, locale: str | None = None) -> list[SearchResult]:
        base_url = os.environ.get("OPENCLAW_BASE_URL", "")
        if not base_url:
            return MockWebSearchProvider().search(query, limit)
        try:
            import httpx
            endpoint = os.environ.get("OPENCLAW_SEARCH_ENDPOINT", "/search/web")
            api_key = os.environ.get("OPENCLAW_API_KEY", "")
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["X-OpenClaw-Key"] = api_key
            payload = {"query": query, "limit": limit, "locale": locale}
            resp = httpx.post(f"{base_url}{endpoint}", json=payload, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            return [SearchResult(query=query, **r) for r in data.get("results", [])]
        except Exception:
            return MockWebSearchProvider().search(query, limit)

    def fetch(self, url: str) -> FetchedPage:
        return FetchedPage(url=url, content="", fetched_at=utcnow_iso(), error="fetch not implemented in mock")

def get_search_provider_for_risk(supplier_name: str = "") -> WebSearchProvider:
    provider_name = os.environ.get("AIVAN_WEB_SEARCH_PROVIDER", "mock").lower()
    if provider_name == "mock":
        return MockWebSearchProvider()
    elif provider_name == "openclaw_search":
        return OpenClawSearchProvider()
    return MockWebSearchProvider()
