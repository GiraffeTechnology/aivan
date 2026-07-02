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
    assert ls["canonical_english_text"].startswith("inquiry")
    assert ls["canonical_text"].startswith("inquiry")
    assert req.extra["canonical_english_text"].startswith("inquiry")
    assert req.extra["requested_output_language"] == "zh"
    assert req.extra["final_output_language"] == "zh"
    assert ls["structured"]["quality_level"] == "high"
    assert ls["translation"]["glossary_version"] == "2026-07-01"
    assert req.extra["quality_level"] == "high"
    assert req.extra["product_modifier"] == ["plaid"]


def test_requirement_agent_uses_language_skill_before_aivan_llm(enabled_service, monkeypatch):
    # P0 language rule: valid non-English RFQ packets are extracted by the
    # shared language-skill layer, not by an AIVAN-local multilingual parser.
    from aivan.agents import requirement_agent

    def fail_if_called(*args, **kwargs):
        raise AssertionError("AIVAN LLM must not receive raw non-English RFQ text")

    monkeypatch.setattr(requirement_agent, "llm_complete_json", fail_if_called)
    req = requirement_agent.structure_customer_requirement_with_llm(
        raw_text=ZH_RFQ, project_id="p1", source_channel="wechat"
    )
    assert enabled_service["paths"] == ["/v1/inbound/normalize", "/v1/structure/rfq"]
    assert req.quantity == 5000
    assert req.destination == "Tokyo"
    assert req.product_type == "plaid shirt"
    assert req.delivery_days == 45
    assert req.extra["non_english_extracted_by"] == "language_skill"
    assert req.extra["canonical_english_text"].startswith("inquiry 5000 pcs")
    assert req.extra["language_skill"]["validation_status"] == "valid"


def test_chinese_rfq_language_skill_keeps_tokyo_plaid_and_quality(enabled_service, monkeypatch):
    # Canonical non-English path: the language skill (not an AIVAN-internal
    # translation layer) supplies Tokyo, the plaid modifier, and the high
    # quality level. The local AIVAN LLM must not run on raw Chinese.
    from aivan.agents import requirement_agent

    monkeypatch.setattr(
        requirement_agent,
        "llm_complete_json",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected AIVAN LLM call")),
    )

    req = requirement_agent.structure_customer_requirement_with_llm(
        raw_text=ZH_RFQ, project_id="p1", source_channel="wechat"
    )

    assert req.language == "zh"
    assert req.destination == "Tokyo"
    assert req.extra["product_modifier"] == ["plaid"]
    assert req.extra["quality_level"] == "high"
    assert req.extra["language_skill"]["structured"]["quality_level"] == "high"


def test_non_english_without_language_skill_blocks_local_extraction(monkeypatch):
    from aivan.agents import requirement_agent

    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("AIVAN LLM must not parse raw non-English input")

    monkeypatch.setattr(requirement_agent, "llm_complete_json", fail_if_called)

    req = requirement_agent.structure_customer_requirement_with_llm(
        raw_text=ZH_RFQ, project_id="p1", source_channel="wechat"
    )

    assert req.language == "zh"
    assert req.quantity is None
    assert req.delivery_days is None
    assert req.destination == ""
    assert req.product_type == ""
    assert req.extra["non_english_local_extraction_blocked"] == "language_skill_required"


def test_non_english_aivan_llm_receives_only_canonical_english_with_attachments(
    enabled_service, monkeypatch
):
    # Attachments may still require AIVAN enrichment, but the prompt must use
    # the language-skill canonical English text, never the raw Chinese message.
    from aivan.agents import requirement_agent

    captured: dict[str, str] = {}

    def capture_prompt(task, system_prompt, user_prompt):
        captured["prompt"] = user_prompt
        return {
            "category": "apparel",
            "product_type": "plaid shirt",
            "quantity": 5000,
            "quantity_unit": "pcs",
            "destination": "Tokyo",
            "delivery_days": 45,
            "confidence": 0.9,
            "language": "en",
        }

    monkeypatch.setattr(requirement_agent, "llm_complete_json", capture_prompt)

    req = requirement_agent.structure_customer_requirement_with_llm(
        raw_text=ZH_RFQ,
        attachments=[{"filename": "spec.jpg", "type": "image/jpeg"}],
        project_id="p1",
        source_channel="wechat",
    )

    assert "inquiry 5000 pcs high quality plaid shirt" in captured["prompt"]
    assert "询价" not in captured["prompt"]
    assert "交东京" not in captured["prompt"]
    assert "Language: en" in captured["prompt"]
    assert req.extra["non_english_extracted_by"] == "language_skill"


def test_english_rfq_still_uses_normalized_english_text(monkeypatch):
    from aivan.agents import requirement_agent

    english_canon = {
        "normalize": {
            "raw_text": "Order 5000 plaid shirts to Osaka within 45 days.",
            "language": {"detected": "en", "confidence": 1.0},
            "canonical_language": "en",
            "canonical_text": "Inquiry: 5000 pcs plaid shirts to Osaka within 45 days.",
            "requested_output_language": "en",
            "field_evidence": {},
        },
        "structure": {
            "schema": "trade_rfq.v1",
            "validation_status": "valid",
            "structured": {
                "quantity": 5000,
                "quantity_unit": "pcs",
                "product_name": "plaid shirt",
                "product_category": "apparel",
                "destination": "Osaka",
                "lead_time_days": 45,
            },
            "missing_fields": [],
            "confidence_score": 0.95,
            "field_sources": {"destination": "language_skill"},
        },
    }
    captured: dict[str, str] = {}
    monkeypatch.setattr(requirement_agent, "canonicalize_rfq", lambda *a, **k: english_canon)

    def capture_prompt(task, system_prompt, user_prompt):
        captured["prompt"] = user_prompt
        return {"confidence": 0.1, "language": "en"}

    monkeypatch.setattr(requirement_agent, "llm_complete_json", capture_prompt)

    req = requirement_agent.structure_customer_requirement_with_llm(
        raw_text="Order 5000 plaid shirts to Osaka within 45 days.",
        project_id="p1",
        source_channel="email",
    )

    assert "Inquiry: 5000 pcs plaid shirts to Osaka within 45 days." in captured["prompt"]
    assert req.destination == "Osaka"
    assert req.extra["final_output_language"] == "en"


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



def test_english_singapore_not_overwritten_by_local_llm_when_language_skill_missing_destination(monkeypatch):
    """A local LLM candidate must not become authoritative when language-skill lacks destination."""
    from aivan.agents import requirement_agent
    from aivan.execution.safety import evaluate_requirement_readiness
    from aivan.rfq import semantic_sources

    monkeypatch.setattr(
        requirement_agent,
        "canonicalize_rfq",
        lambda *a, **k: {
            "normalize": {
                "field_evidence": {
                    "quantity": {"value": 5000, "source": "raw_rule"},
                    "lead_time_days": {"value": 45, "source": "raw_rule"},
                    "product_category": {"value": "apparel", "source": "canonical_parser"},
                    "product_modifier": {"value": ["plaid"], "source": "canonical_parser"},
                }
            },
            "structure": {
                "structured": {
                    "quantity": 5000,
                    "quantity_unit": "pcs",
                    "product_name": "plaid shirt",
                    "product_category": "apparel",
                    "product_modifier": ["plaid"],
                    "destination": None,
                    "lead_time_days": 45,
                    "intent": "inquiry",
                },
                "field_sources": {
                    "quantity": "raw_rule",
                    "product_name": "canonical_parser+glossary",
                    "product_category": "canonical_parser",
                    "product_modifier": "canonical_parser",
                    "lead_time_days": "raw_rule",
                },
                "missing_fields": ["destination"],
                "validation_status": "needs_confirmation",
            },
        },
    )
    monkeypatch.setattr(
        requirement_agent,
        "llm_complete_json",
        lambda *a, **k: {
            "category": "apparel",
            "product_type": "plaid shirt",
            "quantity": 5000,
            "quantity_unit": "pcs",
            "destination": "Vancouver",
            "color": "white",
            "fabric_material": "100% cotton",
            "delivery_days": 45,
            "confidence": 0.95,
            "language": "en",
        },
    )

    req = requirement_agent.structure_customer_requirement_with_llm(
        raw_text="Inquiry: Order 5000 plaid shirts, to be shipped to Singapore within 45 days.",
        project_id="p-singapore",
        source_channel="wechat",
    )

    assert req.destination == "Vancouver"  # preserved only as provisional LLM evidence
    assert semantic_sources.source_of(req, "destination") == "llm_structured"
    gate = evaluate_requirement_readiness(req)
    assert gate.ready is False
    assert gate.next_action == "pending_destination_confirmation"
    assert "destination" in gate.missing_fields
