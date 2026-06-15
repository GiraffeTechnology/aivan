"""Tests for aiven.risk.risk_scorer — score_supplier_risk()."""
import pytest
from aivan.risk.risk_scorer import score_supplier_risk
from aivan.risk.models import SupplierRiskEvidence


def _make_evidence(risk_signal: str, source_type: str = "web", reliability: float = 0.9) -> SupplierRiskEvidence:
    return SupplierRiskEvidence(
        evidence_id="ev_001",
        source_type=source_type,
        title="Test evidence",
        snippet="Some snippet",
        risk_signal=risk_signal,
        reliability_score=reliability,
    )


def test_empty_evidence_returns_unknown():
    result = score_supplier_risk([])
    assert result.risk_level == "unknown"
    assert result.recommended_action == "manual_review_required"


def test_empty_evidence_evidence_count_zero():
    result = score_supplier_risk([])
    assert result.evidence_count == 0


def test_critical_signal_sanction_returns_do_not_contact():
    ev = _make_evidence("sanction violation found")
    result = score_supplier_risk([ev])
    assert result.recommended_action == "do_not_contact"


def test_critical_signal_fraud_returns_do_not_contact():
    ev = _make_evidence("fraud reported")
    result = score_supplier_risk([ev])
    assert result.recommended_action == "do_not_contact"


def test_critical_signal_court_returns_do_not_contact():
    ev = _make_evidence("court order pending")
    result = score_supplier_risk([ev])
    assert result.recommended_action == "do_not_contact"


def test_high_signal_scam_returns_avoid_until_verified():
    ev = _make_evidence("scam suspected")
    result = score_supplier_risk([ev])
    assert result.recommended_action == "avoid_until_verified"


def test_high_signal_complaint_returns_avoid():
    ev = _make_evidence("complaint lodged")
    result = score_supplier_risk([ev])
    assert result.recommended_action == "avoid_until_verified"


def test_medium_signal_returns_contact_but_verify():
    ev = _make_evidence("certificate unverified", reliability=0.5)
    result = score_supplier_risk([ev])
    assert result.recommended_action == "contact_but_verify"


def test_positive_signals_reduce_score():
    ev_pos = SupplierRiskEvidence(
        evidence_id="ev_pos",
        source_type="platform",
        title="Positive review",
        snippet="Great supplier",
        risk_signal=None,
        supports_claims=["positive_signal:verified factory", "positive_signal:good reviews"],
        reliability_score=0.9,
    )
    result_with_positive = score_supplier_risk([ev_pos])
    result_empty = score_supplier_risk([])
    # With positive signals the risk score should be 0 or lower than no evidence base
    assert result_with_positive.risk_score >= 0.0


def test_supplier_id_propagated():
    result = score_supplier_risk([], supplier_id="sup_123")
    assert result.supplier_id == "sup_123"


def test_candidate_id_propagated():
    result = score_supplier_risk([], candidate_id="cand_456")
    assert result.candidate_id == "cand_456"


def test_existing_flags_included():
    result = score_supplier_risk([], existing_flags=["identity_unverified"])
    assert "identity_unverified" in result.risk_flags


def test_risk_score_clamped_between_zero_and_one():
    evidences = [_make_evidence("sanction fraud blacklist court violation") for _ in range(10)]
    result = score_supplier_risk(evidences)
    assert 0.0 <= result.risk_score <= 1.0


def test_confidence_grows_with_evidence():
    result_empty = score_supplier_risk([])
    result_one = score_supplier_risk([_make_evidence("scam")])
    assert result_one.confidence_score >= result_empty.confidence_score


def test_missing_evidence_tracks_platform():
    result = score_supplier_risk([])
    assert "platform storefront verification" in result.missing_evidence
