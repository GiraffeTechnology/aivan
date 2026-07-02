"""Private-domain: no external model API in the baseline loop (PRD §14A/§15, §18.5)."""
from __future__ import annotations

import pytest

import aivan.agents.requirement_agent as requirement_agent
from aivan.agents.requirement_agent import structure_customer_requirement_with_llm
from aivan.execution.safety import evaluate_requirement_readiness
from aivan.llm import gateway
from aivan.llm.gateway import build_llm_provider, llm_complete_json
from aivan.llm.policy import (
    ExternalModelApiRequiresApprovalError,
    ExternalModelApproval,
    external_model_approval,
)
from aivan.rfq import semantic_sources


@pytest.fixture(autouse=True)
def _reset_provider():
    gateway.reset_provider()
    yield
    gateway.reset_provider()


def test_llm_disabled_blocks_provider_build(monkeypatch):
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AIVAN_EXTERNAL_MODEL_API_ENABLED", "false")
    with pytest.raises(ExternalModelApiRequiresApprovalError):
        build_llm_provider("requirement_structuring")


def test_vlm_disabled_blocks_provider_build(monkeypatch):
    from aivan.vlm.gateway import build_vlm_provider, VLMDisabledError

    monkeypatch.setenv("AIVAN_VLM_PROVIDER", "openai")
    monkeypatch.setenv("AIVAN_VLM_API_ENABLED", "false")
    with pytest.raises(ExternalModelApiRequiresApprovalError):
        build_vlm_provider("visual_qc")

    # Fully disabled VLM raises the disabled error, not a silent no-op.
    monkeypatch.setenv("AIVAN_VLM_PROVIDER", "disabled")
    with pytest.raises(VLMDisabledError):
        build_vlm_provider("visual_qc")


def test_llm_gateway_does_not_fall_back_to_cloud(monkeypatch):
    """An external provider without approval must raise, never silently mock/fall back."""
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("AIVAN_EXTERNAL_MODEL_API_ENABLED", "false")
    monkeypatch.setenv("AIVAN_LLM_API_ENABLED", "true")
    with pytest.raises(ExternalModelApiRequiresApprovalError):
        llm_complete_json("requirement_structuring", "sys", "user", {})


def test_confirmed_external_approval_allows_call(monkeypatch):
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AIVAN_EXTERNAL_MODEL_API_ENABLED", "false")
    approval = ExternalModelApproval(task="requirement_structuring", provider="openai")
    with external_model_approval(approval):
        # Provider build no longer raises for the approved scope.
        from aivan.llm.policy import assert_provider_allowed

        assert_provider_allowed("openai", "requirement_structuring")


# ── P0-3: external API always requires confirmation ──────────────────────────

def test_external_api_enabled_still_requires_approval_by_default(monkeypatch):
    from aivan.llm.policy import assert_provider_allowed

    # Enabling the connector is NOT authorization; a call without approval raises.
    monkeypatch.setenv("AIVAN_EXTERNAL_MODEL_API_ENABLED", "true")
    monkeypatch.delenv("AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED", raising=False)
    with pytest.raises(ExternalModelApiRequiresApprovalError):
        assert_provider_allowed("openai", "rfq_semantic_enrichment")


def test_confirmed_external_approval_allows_one_scoped_call(monkeypatch):
    from aivan.llm.policy import assert_provider_allowed

    monkeypatch.setenv("AIVAN_EXTERNAL_MODEL_API_ENABLED", "false")
    approval = ExternalModelApproval(task="draft_polishing", provider="openai")
    with external_model_approval(approval):
        assert_provider_allowed("openai", "draft_polishing")  # in-scope: allowed
    # Outside the scope the approval is gone.
    with pytest.raises(ExternalModelApiRequiresApprovalError):
        assert_provider_allowed("openai", "draft_polishing")


def test_external_approval_does_not_leak_across_tasks(monkeypatch):
    from aivan.llm.policy import assert_provider_allowed

    monkeypatch.setenv("AIVAN_EXTERNAL_MODEL_API_ENABLED", "false")
    approval = ExternalModelApproval(task="draft_polishing", provider="openai")
    with external_model_approval(approval):
        # A different task is not covered by this approval.
        with pytest.raises(ExternalModelApiRequiresApprovalError):
            assert_provider_allowed("openai", "rfq_semantic_enrichment")


def test_external_api_auto_allowed_not_private_domain_default(monkeypatch):
    from aivan.llm.policy import (
        assert_provider_allowed,
        external_model_api_auto_allowed,
    )

    # Default is false, even in the shipped .env example.
    monkeypatch.delenv("AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED", raising=False)
    assert external_model_api_auto_allowed() is False

    # Only the explicit override + connector enabled permits an unapproved call.
    monkeypatch.setenv("AIVAN_EXTERNAL_MODEL_API_ENABLED", "true")
    monkeypatch.setenv("AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED", "true")
    assert_provider_allowed("openai", "rfq_semantic_enrichment")  # no raise


def test_language_skill_with_llm_off_can_structure_rfq(monkeypatch):
    """With the LLM off but the language skill on, canonical fields are authoritative."""
    monkeypatch.setenv("AIVAN_LLM_API_ENABLED", "false")
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "true")

    canon = {
        "normalize": {
            "language": {"detected": "zh"},
            "canonical_text": "Inquiry: 5000 plaid shirts to Tokyo within 45 days, high quality.",
            "field_evidence": {"destination": {"raw": "东京"}},
            "raw_text": "询价 5000 件格子衬衫，45天交东京，高品质",
            "warnings": [],
        },
        "structure": {
            "structured": {
                "product_name": "plaid shirt",
                "product_category": "apparel",
                "destination": "Tokyo",
                "quantity": 5000,
                "lead_time_days": 45,
                "quality_level": "high",
            },
            "validation_status": "valid",
            "missing_fields": [],
            "confidence_score": 0.9,
            "field_sources": {"destination": "language_skill", "product_name": "language_skill"},
        },
    }
    monkeypatch.setattr(requirement_agent, "canonicalize_rfq", lambda *a, **k: canon)

    req = structure_customer_requirement_with_llm(
        raw_text="询价 5000 件格子衬衫，45天交东京，高品质", project_id="t1"
    )
    assert req.destination == "Tokyo"
    assert req.quantity == 5000
    assert req.delivery_days == 45
    assert semantic_sources.has_authoritative_destination(req)
    gate = evaluate_requirement_readiness(req)
    assert gate.ready


def test_private_domain_workflow_asks_confirmation_when_gates_fail(monkeypatch):
    """LLM off + skill off => raw evidence only => blocked, confirmation requested."""
    monkeypatch.setenv("AIVAN_LLM_API_ENABLED", "false")
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")

    req = structure_customer_requirement_with_llm(
        raw_text="询价 5000 件格子衬衫，45天交东京，高品质", project_id="t2"
    )
    gate = evaluate_requirement_readiness(req)
    assert not gate.ready
    assert gate.next_action.startswith("pending_")
    assert "东京" in gate.operator_message or "目的地" in gate.operator_message
