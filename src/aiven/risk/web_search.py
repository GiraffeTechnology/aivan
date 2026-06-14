from __future__ import annotations
import os
from aiven.risk.models import SearchResult, FetchedPage
from aiven.utils.time_utils import utcnow_iso

MOCK_SEARCH_RESULTS = {
    "low": [
        SearchResult(query="mock", url="https://1688.com/shop/123", title="Guangzhou Trendy Garment Store", snippet="Established supplier since 2018, 328 reviews, Gold Supplier.", publisher="1688.com", source_type="platform"),
        SearchResult(query="mock", url="https://alibaba.com/supplier/123", title="Trendy Garment - Verified Supplier", snippet="ISO 9001 certified, 6 years on platform, 4.7 rating.", publisher="alibaba.com", source_type="platform"),
    ],
    "medium": [
        SearchResult(query="mock", url="https://alibaba.com/supplier/456", title="Fujian Apparel - Supplier Profile", snippet="Trade Assurance supplier, 4 years, 215 reviews.", publisher="alibaba.com", source_type="platform"),
        SearchResult(query="mock", url="https://complaint-site.example.com/review", title="Fujian Apparel - 1 complaint found", snippet="One customer reported delayed delivery in 2024.", publisher="review-site", source_type="review"),
    ],
    "high": [
        SearchResult(query="mock", url="https://1688.com/shop/789", title="Unknown Factory Store", snippet="New store opened 2025, no reviews.", publisher="1688.com", source_type="platform"),
        SearchResult(query="mock", url="https://scam-report.example.com", title="Possible scam report", snippet="Multiple users report non-delivery and unresponsive seller.", publisher="scam-report", source_type="complaint"),
    ],
    "critical": [
        SearchResult(query="mock", url="https://sanctions.example.gov", title="Sanctioned Entity List", snippet="Entity flagged for export control violations.", publisher="sanctions-db", source_type="government"),
        SearchResult(query="mock", url="https://court.example.com/case", title="Court record: fraud case", snippet="Company found liable for commercial fraud in 2024.", publisher="court-records", source_type="legal"),
    ],
}

class WebSearchProvider:
    provider_name: str = "mock"

    def search(self, query: str, limit: int = 10, locale: str | None = None) -> list[SearchResult]:
        raise NotImplementedError

    def fetch(self, url: str) -> FetchedPage:
        raise NotImplementedError

class MockWebSearchProvider(WebSearchProvider):
    provider_name = "mock"

    def __init__(self, risk_profile: str = "medium"):
        self.risk_profile = risk_profile

    def search(self, query: str, limit: int = 10, locale: str | None = None) -> list[SearchResult]:
        results = []
        for level, items in MOCK_SEARCH_RESULTS.items():
            for item in items:
                result = SearchResult(
                    query=query,
                    url=item.url,
                    title=item.title,
                    snippet=item.snippet,
                    publisher=item.publisher,
                    source_type=item.source_type,
                )
                results.append(result)
                if len(results) >= limit:
                    return results
        return results[:limit]

    def fetch(self, url: str) -> FetchedPage:
        return FetchedPage(url=url, title="Mock Page", content="Mock content for testing.", fetched_at=utcnow_iso())

def get_web_search_provider(risk_profile: str = "medium") -> WebSearchProvider:
    provider_name = os.environ.get("AIVEN_WEB_SEARCH_PROVIDER", "mock").lower()
    if provider_name == "mock":
        return MockWebSearchProvider(risk_profile=risk_profile)
    return MockWebSearchProvider(risk_profile=risk_profile)
