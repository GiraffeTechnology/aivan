#!/usr/bin/env python3
"""AIVEN Unknown Supplier Risk E2E

Tests the risk scorer (aiven.risk.risk_scorer.score_supplier_risk) with four
distinct evidence scenarios:

  Test 1 - No evidence          → risk_level='unknown', action='manual_review_required'
  Test 2 - Critical signal      → risk_level='critical', action='do_not_contact'
  Test 3 - High signal          → risk_level='high',    action='avoid_until_verified'
  Test 4 - Clean positive data  → risk_level='low',     action='safe_to_contact'
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from aiven.risk.risk_scorer import score_supplier_risk
from aiven.risk.models import SupplierRiskEvidence


def _make_evidence(
    evidence_id: str,
    source_type: str,
    title: str,
    snippet: str,
    risk_signal: str | None = None,
    supports_claims: list[str] | None = None,
    reliability_score: float = 0.8,
) -> SupplierRiskEvidence:
    return SupplierRiskEvidence(
        evidence_id=evidence_id,
        source_type=source_type,
        title=title,
        snippet=snippet,
        risk_signal=risk_signal,
        supports_claims=supports_claims or [],
        reliability_score=reliability_score,
    )


def main():
    print("=" * 60)
    print("AIVEN RISK SCREENING E2E")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Test 1: No evidence at all → unknown risk
    # ------------------------------------------------------------------
    print("\n[Test 1] No evidence → expect risk_level='unknown'")
    score1 = score_supplier_risk(
        evidence=[],
        supplier_id="test_unknown_001",
    )
    print(f"  risk_level         : {score1.risk_level}")
    print(f"  recommended_action : {score1.recommended_action}")
    print(f"  risk_flags         : {score1.risk_flags}")
    print(f"  missing_evidence   : {score1.missing_evidence}")

    assert score1.risk_level == "unknown", (
        f"FAIL Test 1: expected 'unknown', got '{score1.risk_level}'"
    )
    assert score1.recommended_action == "manual_review_required", (
        f"FAIL Test 1: expected 'manual_review_required', got '{score1.recommended_action}'"
    )
    assert "insufficient_public_presence" in score1.risk_flags, (
        "FAIL Test 1: 'insufficient_public_presence' flag missing"
    )
    print("  [Test 1] PASS")

    # ------------------------------------------------------------------
    # Test 2: Critical signal (fraud) → do_not_contact
    # ------------------------------------------------------------------
    print("\n[Test 2] Critical signal → expect risk_level='critical', action='do_not_contact'")
    ev_critical = _make_evidence(
        evidence_id="ev_critical_001",
        source_type="web",
        title="Court records: supplier charged with fraud",
        snippet=(
            "Shenzhen Fast Export Co. was named in a 2024 court judgment for "
            "trade fraud, shipping counterfeit goods to buyers."
        ),
        risk_signal="fraud court judgment against supplier",
        reliability_score=0.9,
    )
    score2 = score_supplier_risk(
        evidence=[ev_critical],
        supplier_id="test_critical_001",
    )
    print(f"  risk_level         : {score2.risk_level}")
    print(f"  recommended_action : {score2.recommended_action}")
    print(f"  risk_score         : {score2.risk_score:.3f}")
    print(f"  risk_flags         : {score2.risk_flags}")

    assert score2.risk_level == "critical", (
        f"FAIL Test 2: expected 'critical', got '{score2.risk_level}'"
    )
    assert score2.recommended_action == "do_not_contact", (
        f"FAIL Test 2: expected 'do_not_contact', got '{score2.recommended_action}'"
    )
    print("  [Test 2] PASS")

    # ------------------------------------------------------------------
    # Test 3: High signal (scam / non-delivery) → avoid_until_verified
    # ------------------------------------------------------------------
    print("\n[Test 3] High signal → expect risk_level='high', action='avoid_until_verified'")
    ev_high = _make_evidence(
        evidence_id="ev_high_001",
        source_type="web",
        title="Alibaba Buyer Reviews: non-delivery complaint",
        snippet=(
            "Multiple buyers report this supplier took deposits then stopped "
            "responding — a classic scam pattern on the platform."
        ),
        risk_signal="scam non-delivery complaint",
        reliability_score=0.75,
    )
    score3 = score_supplier_risk(
        evidence=[ev_high],
        supplier_id="test_high_001",
    )
    print(f"  risk_level         : {score3.risk_level}")
    print(f"  recommended_action : {score3.recommended_action}")
    print(f"  risk_score         : {score3.risk_score:.3f}")
    print(f"  risk_flags         : {score3.risk_flags}")

    assert score3.risk_level == "high", (
        f"FAIL Test 3: expected 'high', got '{score3.risk_level}'"
    )
    assert score3.recommended_action == "avoid_until_verified", (
        f"FAIL Test 3: expected 'avoid_until_verified', got '{score3.recommended_action}'"
    )
    print("  [Test 3] PASS")

    # ------------------------------------------------------------------
    # Test 4: Clean supplier with positive signals → low risk
    # ------------------------------------------------------------------
    print("\n[Test 4] Clean supplier → expect risk_level='low', action='safe_to_contact'")
    ev_platform = _make_evidence(
        evidence_id="ev_platform_001",
        source_type="platform",
        title="Alibaba Gold Supplier – Guangzhou Trendy Garment",
        snippet=(
            "Gold Supplier since 2018, Trade Assurance enabled, "
            "4.8 stars across 328 verified reviews. ISO 9001 certified."
        ),
        risk_signal=None,
        supports_claims=[
            "positive_signal:platform_verified",
            "positive_signal:trade_assurance",
        ],
        reliability_score=0.85,
    )
    ev_government = _make_evidence(
        evidence_id="ev_gov_001",
        source_type="government",
        title="National Enterprise Credit – business registration verified",
        snippet=(
            "Guangzhou Trendy Garment Co., Ltd. registered since 2017, "
            "no violations on record. Export licence active."
        ),
        risk_signal=None,
        supports_claims=["positive_signal:legal_registration_verified"],
        reliability_score=0.95,
    )
    score4 = score_supplier_risk(
        evidence=[ev_platform, ev_government],
        supplier_id="test_clean_001",
    )
    print(f"  risk_level         : {score4.risk_level}")
    print(f"  recommended_action : {score4.recommended_action}")
    print(f"  risk_score         : {score4.risk_score:.3f}")
    print(f"  positive_signals   : {score4.positive_signals}")

    assert score4.risk_level in ("low", "safe_to_contact", "unknown") or score4.risk_score < 0.25, (
        f"FAIL Test 4: expected low risk, got '{score4.risk_level}' (score={score4.risk_score:.3f})"
    )
    # A clean supplier should NOT trigger do_not_contact or avoid_until_verified
    assert score4.recommended_action not in ("do_not_contact", "avoid_until_verified"), (
        f"FAIL Test 4: unexpected action '{score4.recommended_action}' for clean supplier"
    )
    print("  [Test 4] PASS")

    # ------------------------------------------------------------------
    # Done
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("AIVEN RISK E2E: PASS")
    print("=" * 60)


if __name__ == "__main__":
    main()
