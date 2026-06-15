"""Tests for aiven.risk.models — SupplierRiskEvidence and related models."""
import pytest
from aivan.risk.models import (
    SupplierRiskEvidence,
    SupplierRiskScore,
    SupplierRiskReport,
    SupplierRiskSearchPlan,
    SearchResult,
    FetchedPage,
)


# --- SupplierRiskEvidence ---

def test_evidence_required_fields():
    ev = SupplierRiskEvidence(
        evidence_id="ev_001",
        source_type="web",
        title="Test Title",
        snippet="Some snippet text",
    )
    assert ev.evidence_id == "ev_001"
    assert ev.source_type == "web"
    assert ev.title == "Test Title"
    assert ev.snippet == "Some snippet text"


def test_evidence_optional_url_defaults_none():
    ev = SupplierRiskEvidence(
        evidence_id="ev_002",
        source_type="platform",
        title="Platform evidence",
        snippet="snippet",
    )
    assert ev.url is None


def test_evidence_optional_publisher_defaults_none():
    ev = SupplierRiskEvidence(
        evidence_id="ev_003",
        source_type="web",
        title="Title",
        snippet="snippet",
    )
    assert ev.publisher is None


def test_evidence_reliability_score_default():
    ev = SupplierRiskEvidence(
        evidence_id="ev_004",
        source_type="web",
        title="Title",
        snippet="snippet",
    )
    assert ev.reliability_score == 0.5


def test_evidence_relevance_default():
    ev = SupplierRiskEvidence(
        evidence_id="ev_005",
        source_type="web",
        title="Title",
        snippet="snippet",
    )
    assert ev.relevance == "medium"


def test_evidence_risk_signal_default_none():
    ev = SupplierRiskEvidence(
        evidence_id="ev_006",
        source_type="web",
        title="Title",
        snippet="snippet",
    )
    assert ev.risk_signal is None


def test_evidence_supports_claims_default_empty():
    ev = SupplierRiskEvidence(
        evidence_id="ev_007",
        source_type="web",
        title="Title",
        snippet="snippet",
    )
    assert ev.supports_claims == []


def test_evidence_contradicts_claims_default_empty():
    ev = SupplierRiskEvidence(
        evidence_id="ev_008",
        source_type="web",
        title="Title",
        snippet="snippet",
    )
    assert ev.contradicts_claims == []


def test_evidence_all_optional_fields_set():
    ev = SupplierRiskEvidence(
        evidence_id="ev_full",
        source_type="government",
        title="Sanctions list",
        snippet="Supplier X appears on sanctions list",
        url="https://sanctions.gov/supplier-x",
        publisher="US Treasury",
        published_date="2024-01-15",
        fetched_at="2024-06-01T00:00:00Z",
        relevance="high",
        reliability_score=0.95,
        risk_signal="sanction violation found",
        supports_claims=["sanction:confirmed"],
        contradicts_claims=[],
    )
    assert ev.url == "https://sanctions.gov/supplier-x"
    assert ev.publisher == "US Treasury"
    assert ev.published_date == "2024-01-15"
    assert ev.reliability_score == 0.95
    assert ev.risk_signal == "sanction violation found"
    assert ev.supports_claims == ["sanction:confirmed"]


def test_evidence_supports_claims_list():
    ev = SupplierRiskEvidence(
        evidence_id="ev_009",
        source_type="platform",
        title="Good reviews",
        snippet="Strong track record",
        supports_claims=["positive_signal:verified factory", "positive_signal:good reviews"],
    )
    assert len(ev.supports_claims) == 2
    assert "positive_signal:verified factory" in ev.supports_claims


def test_evidence_contradicts_claims_list():
    ev = SupplierRiskEvidence(
        evidence_id="ev_010",
        source_type="web",
        title="Contradictory info",
        snippet="Claims contradict public records",
        contradicts_claims=["address_claim", "capacity_claim"],
    )
    assert len(ev.contradicts_claims) == 2


# --- SupplierRiskScore ---

def test_risk_score_defaults():
    score = SupplierRiskScore()
    assert score.risk_level == "unknown"
    assert score.risk_score == 0.0
    assert score.confidence_score == 0.0
    assert score.evidence_count == 0
    assert score.recommended_action == "manual_review_required"
    assert score.risk_flags == []
    assert score.positive_signals == []
    assert score.missing_evidence == []


def test_risk_score_supplier_id_set():
    score = SupplierRiskScore(supplier_id="sup_001")
    assert score.supplier_id == "sup_001"


def test_risk_score_candidate_id_set():
    score = SupplierRiskScore(candidate_id="cand_001")
    assert score.candidate_id == "cand_001"


def test_risk_score_full_construction():
    score = SupplierRiskScore(
        supplier_id="sup_x",
        risk_level="high",
        risk_score=0.6,
        confidence_score=0.7,
        positive_signals=["verified_factory"],
        risk_flags=["negative_public_complaints"],
        evidence_count=5,
        missing_evidence=["platform storefront verification"],
        recommended_action="avoid_until_verified",
    )
    assert score.risk_level == "high"
    assert score.risk_score == 0.6
    assert score.confidence_score == 0.7
    assert score.evidence_count == 5
    assert "verified_factory" in score.positive_signals
    assert "negative_public_complaints" in score.risk_flags
    assert score.recommended_action == "avoid_until_verified"


# --- SupplierRiskSearchPlan ---

def test_search_plan_defaults():
    plan = SupplierRiskSearchPlan()
    assert plan.supplier_name_queries == []
    assert plan.complaint_queries == []
    assert plan.reason == ""


def test_search_plan_with_queries():
    plan = SupplierRiskSearchPlan(
        supplier_name_queries=["Acme Textiles company review"],
        complaint_queries=["Acme Textiles scam fraud"],
        reason="Standard due diligence",
    )
    assert len(plan.supplier_name_queries) == 1
    assert plan.reason == "Standard due diligence"


# --- SearchResult ---

def test_search_result_defaults():
    r = SearchResult(query="test query")
    assert r.query == "test query"
    assert r.url == ""
    assert r.title == ""
    assert r.source_type == "web"


def test_search_result_full():
    r = SearchResult(
        query="Acme fraud",
        url="https://example.com/acme",
        title="Acme Textiles Fraud Allegations",
        snippet="Reports suggest fraud...",
        publisher="Business Daily",
        published_date="2024-03-01",
        source_type="news",
    )
    assert r.url == "https://example.com/acme"
    assert r.publisher == "Business Daily"
    assert r.source_type == "news"


# --- FetchedPage ---

def test_fetched_page_defaults():
    page = FetchedPage(url="https://example.com")
    assert page.url == "https://example.com"
    assert page.status_code == 200
    assert page.error is None
    assert page.content == ""


def test_fetched_page_with_error():
    page = FetchedPage(url="https://bad.com", status_code=404, error="Not found")
    assert page.status_code == 404
    assert page.error == "Not found"


# --- SupplierRiskReport ---

def test_risk_report_construction():
    score = SupplierRiskScore(risk_level="low", recommended_action="safe_to_contact")
    report = SupplierRiskReport(
        report_id="risk_001",
        supplier_name="Acme Textiles",
        risk_score=score,
    )
    assert report.report_id == "risk_001"
    assert report.supplier_name == "Acme Textiles"
    assert report.risk_score.risk_level == "low"
    assert report.evidence == []


def test_risk_report_with_evidence():
    ev = SupplierRiskEvidence(
        evidence_id="ev_r1",
        source_type="web",
        title="Review",
        snippet="Looks good",
    )
    score = SupplierRiskScore()
    report = SupplierRiskReport(
        report_id="risk_002",
        supplier_name="XYZ Corp",
        risk_score=score,
        evidence=[ev],
    )
    assert len(report.evidence) == 1
    assert report.evidence[0].evidence_id == "ev_r1"
