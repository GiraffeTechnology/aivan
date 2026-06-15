#!/usr/bin/env python3
"""AIVAN Marketplace E2E - Alibaba Discovery Flow

Tests the marketplace sourcing pipeline:
  build queries → search Alibaba (mock) → risk-screen top candidates → verify results.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

os.environ.setdefault("AIVAN_LLM_PROVIDER", "mock")
os.environ.setdefault("OPENCLAW_MOCK_MODE", "true")
os.environ.setdefault("AIVAN_ALIBABA_MODE", "mock")


def main():
    print("=" * 60)
    print("AIVAN MARKETPLACE E2E: Alibaba Discovery")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Verify Alibaba and AliExpress are in the built-in platform list
    # ------------------------------------------------------------------
    from aiven.platforms.whitelist import BUILT_IN_PLATFORMS

    print("\n[1] Verifying built-in platform whitelist...")
    assert "alibaba" in BUILT_IN_PLATFORMS, "FAIL: 'alibaba' not in BUILT_IN_PLATFORMS"
    assert "aliexpress" in BUILT_IN_PLATFORMS, "FAIL: 'aliexpress' not in BUILT_IN_PLATFORMS"
    print(f"  Built-in platforms: {list(BUILT_IN_PLATFORMS.keys())}")
    print("  [1] OK")

    # ------------------------------------------------------------------
    # 2. Build marketplace search queries from a BuyerRequirement
    # ------------------------------------------------------------------
    from aiven.schemas.requirement import BuyerRequirement
    from aiven.sourcing.marketplaces.search_query_builder import build_marketplace_queries

    req = BuyerRequirement(
        project_id="demo_marketplace_e2e_001",
        category="apparel",
        product_type="men's shirt",
        quantity=10000,
        fabric_material="100% cotton",
        gsm=180,
        color="white",
        size_ratio="S/M/L/XL=20/40/30/10",
        destination="Vancouver",
        delivery_days=45,
        target_unit_price=4.80,
        incoterms="DDP",
        logistics_preference="air",
    )

    print("\n[2] Building marketplace search queries...")
    queries = build_marketplace_queries(req)
    assert len(queries) > 0, "FAIL: build_marketplace_queries returned empty list"
    print(f"  Generated {len(queries)} search quer{'y' if len(queries) == 1 else 'ies'}:")
    for i, q in enumerate(queries, 1):
        print(f"    {i}. {q}")
    print("  [2] OK")

    # ------------------------------------------------------------------
    # 3. Search Alibaba via mock connector
    # ------------------------------------------------------------------
    from aiven.sourcing.marketplaces.alibaba_connector import search_alibaba

    print("\n[3] Searching Alibaba (mock mode)...")
    results = search_alibaba(queries[0])

    assert results is not None, "FAIL: search_alibaba returned None"
    assert results.connector_mode == "mock", (
        f"FAIL: expected connector_mode='mock', got '{results.connector_mode}'"
    )
    assert len(results.candidates) > 0, "FAIL: search returned no candidates"

    print(f"  Found {len(results.candidates)} candidate(s) (total_found={results.total_found}):")
    for c in results.candidates:
        badges = ", ".join(c.verification_badges) if c.verification_badges else "none"
        flags = c.risk_flags if c.risk_flags else []
        print(
            f"    [{c.candidate_id}] {c.supplier_name}"
            f" | MOQ: {c.moq} | Price: {c.price_min}-{c.price_max} USD"
            f" | Badges: {badges} | Risk flags: {flags}"
        )
    print("  [3] OK")

    # ------------------------------------------------------------------
    # 4. Risk-screen the top 2 candidates
    # ------------------------------------------------------------------
    from aiven.risk.supplier_risk_agent import run_risk_screening

    print("\n[4] Running risk screening on top 2 candidates...")
    screened_count = 0
    for cand in results.candidates[:2]:
        report = run_risk_screening(
            cand.supplier_name,
            candidate_id=cand.candidate_id,
            existing_flags=cand.risk_flags,
        )
        level = report.risk_score.risk_level.upper()
        action = report.risk_score.recommended_action
        conf = report.risk_score.confidence_score
        print(
            f"  {cand.supplier_name}: {level} risk"
            f" | Action: {action} | Confidence: {conf:.2f}"
        )
        assert report.risk_score.risk_level in (
            "low", "medium", "high", "critical", "unknown"
        ), f"FAIL: unexpected risk_level '{report.risk_score.risk_level}'"
        screened_count += 1

    assert screened_count == 2, f"FAIL: expected 2 screenings, got {screened_count}"
    print("  [4] OK")

    # ------------------------------------------------------------------
    # Done
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("AIVAN MARKETPLACE E2E: PASS")
    print("=" * 60)


if __name__ == "__main__":
    main()
