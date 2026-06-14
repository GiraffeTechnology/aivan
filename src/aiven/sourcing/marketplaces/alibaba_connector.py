from __future__ import annotations
import os
from aiven.sourcing.marketplaces.marketplace_models import MarketplaceSupplierCandidate, SearchResult
from aiven.sourcing.marketplaces.supplier_candidate_normalizer import normalize_candidate
from aiven.utils.ids import new_candidate_id

MOCK_ALIBABA_RESULTS = [
    {
        "candidate_id": f"cand_alibaba_001",
        "supplier_name": "Guangzhou Trendy Garment Co., Ltd.",
        "platform_supplier_id": "1688_supplier_001",
        "product_title": "White 100% Cotton Men's Dress Shirt 180GSM Factory",
        "categories": ["apparel", "men's shirts"],
        "materials": ["100% cotton", "cotton"],
        "moq": 3000,
        "price_min": 4.20,
        "price_max": 5.50,
        "currency": "USD",
        "region": "Guangdong",
        "country": "CN",
        "years_on_platform": 6,
        "verification_badges": ["Gold Supplier", "Assessed Supplier"],
        "rating_signals": {"score": 4.7, "reviews": 328},
        "wangwang_id": "ww_trendy_001",
        "openclaw_peer_id": "oc_peer_trendy_001",
        "source": "alibaba_mock",
    },
    {
        "candidate_id": f"cand_alibaba_002",
        "supplier_name": "Fujian Excellent Apparel Manufacturing",
        "platform_supplier_id": "alibaba_com_sup_002",
        "product_title": "OEM Cotton Men Shirt 180GSM MOQ 5000",
        "categories": ["apparel", "shirts"],
        "materials": ["cotton", "CVC"],
        "moq": 5000,
        "price_min": 3.90,
        "price_max": 5.00,
        "currency": "USD",
        "region": "Fujian",
        "country": "CN",
        "years_on_platform": 4,
        "verification_badges": ["Trade Assurance"],
        "rating_signals": {"score": 4.5, "reviews": 215},
        "wangwang_id": "ww_fujian_002",
        "openclaw_peer_id": "oc_peer_fujian_002",
        "source": "alibaba_mock",
    },
    {
        "candidate_id": f"cand_alibaba_003",
        "supplier_name": "Zhejiang New Style Textile Ltd.",
        "platform_supplier_id": "alibaba_com_sup_003",
        "product_title": "Men Cotton Shirt Manufacturer 180gsm White",
        "categories": ["textile", "apparel"],
        "materials": ["cotton", "spandex"],
        "moq": 2000,
        "price_min": 4.60,
        "price_max": 6.00,
        "currency": "USD",
        "region": "Zhejiang",
        "country": "CN",
        "years_on_platform": 2,
        "verification_badges": [],
        "rating_signals": {"score": 4.1, "reviews": 45},
        "wangwang_id": None,
        "openclaw_peer_id": None,
        "source": "alibaba_mock",
    },
    {
        "candidate_id": f"cand_alibaba_004",
        "supplier_name": "Dongguan Fast Fashion Clothing Co.",
        "platform_supplier_id": "1688_sup_004",
        "product_title": "Fast delivery Cotton Shirt Wholesale Factory",
        "categories": ["apparel"],
        "materials": ["cotton blend"],
        "moq": 1000,
        "price_min": 3.50,
        "price_max": 4.80,
        "currency": "USD",
        "region": "Guangdong",
        "country": "CN",
        "years_on_platform": 1,
        "verification_badges": [],
        "rating_signals": {"score": 3.8, "reviews": 12},
        "wangwang_id": "ww_fast_004",
        "openclaw_peer_id": None,
        "source": "alibaba_mock",
    },
    {
        "candidate_id": f"cand_alibaba_005",
        "supplier_name": "Shanghai Premium Apparel Export",
        "platform_supplier_id": "alibaba_com_sup_005",
        "product_title": "Premium Cotton Men Dress Shirt 180GSM Export",
        "categories": ["apparel", "export"],
        "materials": ["100% cotton", "Egyptian cotton"],
        "moq": 8000,
        "price_min": 5.00,
        "price_max": 7.00,
        "currency": "USD",
        "region": "Shanghai",
        "country": "CN",
        "years_on_platform": 9,
        "verification_badges": ["Gold Supplier", "Assessed Supplier", "ISO 9001"],
        "rating_signals": {"score": 4.9, "reviews": 892},
        "wangwang_id": "ww_premium_005",
        "openclaw_peer_id": "oc_peer_premium_005",
        "source": "alibaba_mock",
    },
]

def search_alibaba_mock(query: str, platform: str = "alibaba", limit: int = 5) -> SearchResult:
    candidates = []
    for raw in MOCK_ALIBABA_RESULTS[:limit]:
        candidate = normalize_candidate(raw, platform)
        candidates.append(candidate)

    return SearchResult(
        query=query,
        platform=platform,
        candidates=candidates,
        total_found=len(MOCK_ALIBABA_RESULTS),
        connector_mode="mock",
    )

def search_alibaba(query: str, platform: str = "alibaba", limit: int = 10) -> SearchResult:
    mode = os.environ.get("AIVEN_ALIBABA_MODE", "mock").lower()
    if mode == "mock":
        return search_alibaba_mock(query, platform, limit)
    return SearchResult(query=query, platform=platform, connector_mode="not_configured", error="Alibaba API not configured. Set AIVEN_ALIBABA_MODE=official_api and provide credentials.")
