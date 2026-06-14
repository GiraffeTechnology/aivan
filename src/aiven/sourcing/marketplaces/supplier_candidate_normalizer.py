from __future__ import annotations
from aiven.sourcing.marketplaces.marketplace_models import MarketplaceSupplierCandidate

def normalize_candidate(raw: dict, platform: str) -> MarketplaceSupplierCandidate:
    """Normalize a raw marketplace result into a MarketplaceSupplierCandidate."""
    from aiven.utils.ids import new_candidate_id

    confidence = 0.5
    badges = raw.get("verification_badges", [])
    if badges:
        confidence += len(badges) * 0.05
    years = raw.get("years_on_platform", 0)
    if years and years > 3:
        confidence += 0.1
    ratings = raw.get("rating_signals", {})
    if ratings.get("score", 0) > 4.0:
        confidence += 0.1
    confidence = min(1.0, confidence)

    risk_flags = []
    if not badges:
        risk_flags.append("identity_unverified")
    if years is not None and years < 1:
        risk_flags.append("storefront_new_or_low_history")

    return MarketplaceSupplierCandidate(
        candidate_id=raw.get("candidate_id", new_candidate_id()),
        platform=platform,
        platform_supplier_id=raw.get("platform_supplier_id"),
        supplier_name=raw.get("supplier_name", raw.get("name", "Unknown Supplier")),
        product_title=raw.get("product_title"),
        product_url=raw.get("product_url"),
        storefront_url=raw.get("storefront_url"),
        categories=raw.get("categories", []),
        materials=raw.get("materials", []),
        moq=raw.get("moq"),
        price_min=raw.get("price_min"),
        price_max=raw.get("price_max"),
        currency=raw.get("currency", "USD"),
        region=raw.get("region"),
        country=raw.get("country", "CN"),
        years_on_platform=years,
        verification_badges=badges,
        transaction_signals=raw.get("transaction_signals", {}),
        rating_signals=ratings,
        delivery_signals=raw.get("delivery_signals", {}),
        contact_channels=raw.get("contact_channels", {}),
        openclaw_peer_id=raw.get("openclaw_peer_id"),
        wangwang_id=raw.get("wangwang_id"),
        source=raw.get("source", platform),
        source_url=raw.get("source_url"),
        confidence_score=confidence,
        risk_flags=risk_flags,
        raw_payload=raw,
    )
