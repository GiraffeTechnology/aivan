"""Tests for the giraffe-language-skill RFQ intake integration.

These use an httpx MockTransport so no live language-skill server is required,
and toggle the feature via the AIVAN_LANGUAGE_SKILL_ENABLED env var.
"""

from __future__ import annotations

import httpx
import pytest

from aivan.integrations import language_skill_client
from aivan.integrations.language_skill import (
    LanguageSkillUnavailable,
    apply_to_requirement,
    canonicalize_rfq,
)
from aivan.integrations.language_skill_client import LanguageSkillClient
from aivan.schemas.requirement import BuyerRequirement

ZH_RFQ = "询价 5000 件格子衬衫，45天交东京，高品质，请给我一个初步报价"

_NORMALIZE_RESPONSE = {
    "raw_text": ZH_RFQ,
    "language": {"detected": "zh", "confidence": 0.98},
    "canonical_language": "en",
    "canonical_text": "inquiry 5000 pcs high quality plaid shirt, deliver to Tokyo, 45 days, preliminary quote",
    "field_evidence": {
        "quantity": {"value": 5000, "source": "raw_rule", "span": "5000 件", "confidence": 1.0},
        "destination": {"value": "Tokyo", "source": "raw_rule+glossary", "span": "交东京", "confidence": 1.0},
    },
    "translation": {"provider": "mock", "model": "mock", "glossary_version": "2026-07-01"},
    "warnings": [],
}

_STRUCTURE_RESPONSE = {
    "schema": "trade_rfq.v1",
    "validation_status": "valid",
    "structured": {
        "quantity": 5000,
        "quantity_unit": "pcs",
        "product_name": "plaid shirt",
        "product_category": "apparel",
        "product_modifier": ["plaid"],
        "destination": "Tokyo",
        "lead_time_days": 45,
        "quality_level": "high",
        "intent": "preliminary_quote",
    },
    "missing_fields": [],
    "confidence_score": 0.95,
    "field_sources": {"quantity": "raw_rule", "destination": "raw_rule+glossary"},
}


def _handler(captured: dict):
    def handle(request: httpx.Request) -> httpx.Response:
        captured.setdefault("paths", []).append(request.url.path)
        if request.url.path == "/v1/inbound/normalize":
            return httpx.Response(200, json=_NORMALIZE_RESPONSE)
        if request.url.path == "/v1/structure/rfq":
            return httpx.Response(200, json=_STRUCTURE_RESPONSE)
        return httpx.Response(404, json={"detail": "not found"})

    return handle


@pytest.fixture
def enabled_service(monkeypatch):
    """Enable the feature and route all client traffic to a mock transport."""
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "true")
    captured: dict = {}
    language_skill_client.set_default_transport(httpx.MockTransport(_handler(captured)))
    yield captured
    language_skill_client.set_default_transport(None)


def test_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")
    assert canonicalize_rfq(ZH_RFQ) is None


def test_canonicalize_calls_both_endpoints(enabled_service):
    canon = canonicalize_rfq(ZH_RFQ, source_channel="wechat")
    assert canon is not None
    assert enabled_service["paths"] == ["/v1/inbound/normalize", "/v1/structure/rfq"]
    assert canon["structure"]["structured"]["destination"] == "Tokyo"


def test_apply_overlays_authoritative_fields(enabled_service):
    canon = canonicalize_rfq(ZH_RFQ)
    req = BuyerRequirement(project_id="p1", raw_text=ZH_RFQ)
    apply_to_requirement(req, canon)

    assert req.quantity == 5000
    assert req.quantity_unit == "pcs"
    assert req.product_type == "plaid shirt"
    assert req.category == "apparel"
    assert req.destination == "Tokyo"
    assert req.delivery_days == 45
    assert req.language == "zh"
    assert req.confidence == pytest.approx(0.95)

    ls = req.extra["language_skill"]
    assert ls["validation_status"] == "valid"
    assert ls["canonical_text"].startswith("inquiry")
    assert ls["structured"]["quality_level"] == "high"
    assert ls["translation"]["glossary_version"] == "2026-07-01"
    assert req.extra["quality_level"] == "high"
    assert req.extra["product_modifier"] == ["plaid"]


def test_requirement_agent_uses_language_skill(enabled_service, monkeypatch):
    # Force the LLM path to return nothing so the deterministic + language-skill
    # overlay is what fills the requirement.
    from aivan.agents import requirement_agent

    monkeypatch.setattr(
        requirement_agent, "llm_complete_json", lambda *a, **k: {}
    )
    req = requirement_agent.structure_customer_requirement_with_llm(
        raw_text=ZH_RFQ, project_id="p1", source_channel="wechat"
    )
    assert req.quantity == 5000
    assert req.destination == "Tokyo"
    assert req.product_type == "plaid shirt"
    assert req.delivery_days == 45
    assert req.extra["language_skill"]["validation_status"] == "valid"


def test_language_skill_overlay_sets_canonical_destination_tokyo(enabled_service):
    canon = canonicalize_rfq(ZH_RFQ)
    req = BuyerRequirement(project_id="p1", raw_text=ZH_RFQ)
    apply_to_requirement(req, canon)

    # Canonical destination is authoritative from the language skill, and the
    # provenance makes that auditable (not an AIVAN-local alias table).
    assert req.destination == "Tokyo"
    assert req.extra["destination_canonical"] == "Tokyo"
    assert req.extra["destination_source"] == "language_skill"
    assert req.extra["destination_raw"] == "交东京"
    assert req.extra["destination_confidence"] == pytest.approx(1.0)


def test_chinese_rfq_language_skill_keeps_tokyo_plaid_and_quality(enabled_service, monkeypatch):
    # Canonical non-English path: the language skill (not an AIVAN-internal
    # translation layer) supplies Tokyo, the plaid modifier, and the high
    # quality level. Force the local LLM to return nothing so the overlay is the
    # authoritative source.
    from aivan.agents import requirement_agent

    monkeypatch.setattr(requirement_agent, "llm_complete_json", lambda *a, **k: {})

    req = requirement_agent.structure_customer_requirement_with_llm(
        raw_text=ZH_RFQ, project_id="p1", source_channel="wechat"
    )

    assert req.language == "zh"
    assert req.destination == "Tokyo"
    assert req.extra["product_modifier"] == ["plaid"]
    assert req.extra["quality_level"] == "high"
    assert req.extra["language_skill"]["structured"]["quality_level"] == "high"


def test_requirement_agent_coerces_malformed_llm_string_fields(monkeypatch):
    from aivan.agents import requirement_agent

    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")
    monkeypatch.setattr(
        requirement_agent,
        "llm_complete_json",
        lambda *a, **k: {
            "category": "apparel",
            "product_type": "shirt",
            "quantity": 5000,
            "delivery_days": 45,
            "destination": "Osaka",
            "notes": ["Order: 5000 plaid shirts", "Shipped to Osaka within 45 days"],
            "confidence": 0.7,
            "language": "en",
        },
    )

    req = requirement_agent.structure_customer_requirement_with_llm(
        raw_text="Inquiry: Order 5000 plaid shirts, to be shipped to Osaka within 45 days.",
        project_id="p1",
        source_channel="email",
    )

    assert req.destination == "Osaka"
    assert req.notes == "Order: 5000 plaid shirts; Shipped to Osaka within 45 days"


def test_overlay_does_not_null_existing_when_service_omits(enabled_service):
    # A structure response missing a field must not wipe an existing value.
    req = BuyerRequirement(project_id="p1", raw_text=ZH_RFQ, color="white")
    canon = {"normalize": _NORMALIZE_RESPONSE, "structure": _STRUCTURE_RESPONSE}
    apply_to_requirement(req, canon)
    assert req.color == "white"  # untouched by RFQ overlay


def test_fail_hard_raises(monkeypatch):
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "true")
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_FAIL_SOFT", "false")

    def _boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "down"})

    client = LanguageSkillClient(transport=httpx.MockTransport(_boom))
    with pytest.raises(LanguageSkillUnavailable):
        canonicalize_rfq(ZH_RFQ, client=client)


def test_fail_soft_returns_none_on_error(monkeypatch):
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "true")
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_FAIL_SOFT", "true")

    def _boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "down"})

    client = LanguageSkillClient(transport=httpx.MockTransport(_boom))
    assert canonicalize_rfq(ZH_RFQ, client=client) is None
