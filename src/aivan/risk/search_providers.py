from __future__ import annotations
import os
from aivan.risk.models import SearchResult, FetchedPage
from aivan.risk.web_search import WebSearchProvider, MockWebSearchProvider
from aivan.utils.time_utils import utcnow_iso
from aivan.governance.runtime_policy import is_production

class OpenClawSearchProvider(WebSearchProvider):
    provider_name = "openclaw_search"

    def search(self, query: str, limit: int = 10, locale: str | None = None) -> list[SearchResult]:
        base_url = os.environ.get("OPENCLAW_BASE_URL", "")
        if not base_url:
            if is_production():
                return []
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
            if is_production():
                return []
            return MockWebSearchProvider().search(query, limit)

    def fetch(self, url: str) -> FetchedPage:
        return FetchedPage(
            url=url,
            content="",
            fetched_at=utcnow_iso(),
            error="RISK_PAGE_FETCH_UNAVAILABLE",
        )

def get_search_provider_for_risk(supplier_name: str = "") -> WebSearchProvider:
    provider_name = os.environ.get("AIVAN_WEB_SEARCH_PROVIDER", "mock").lower()
    if provider_name == "mock":
        if is_production():
            raise RuntimeError("MOCK_RISK_SEARCH_FORBIDDEN_IN_PRODUCTION")
        return MockWebSearchProvider()
    elif provider_name == "openclaw_search":
        return OpenClawSearchProvider()
    if is_production():
        raise RuntimeError("UNKNOWN_RISK_SEARCH_PROVIDER_IN_PRODUCTION")
    return MockWebSearchProvider()
