"""Regression coverage for Aivan's real Stage 1 pricing-to-GPM mapping."""

from __future__ import annotations

from types import SimpleNamespace

from aivan.execution.gpm_guidance import _gpm_actor, create_stage1_gpm_guidance
from aivan.integrations.gpm_guidance_client import GPMGuidanceClient
from aivan.openclaw.contracts import OpenClawEvent
from aivan.schemas.quote import BuyerOption, QuoteCalculation
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply


def test_selected_buyer_quote_identity_actor_and_gltg_lineage_reach_gpm(monkeypatch):
    captured = {}

    def create(self, **kwargs):
        captured.update(kwargs)
        return {
            "packet_id": "gpm_pkt_quote001",
            "recommendation": "negotiate",
            "confidence": "medium",
            "human_approval_required": True,
            "approval_status": "pending",
            "dispatched": False,
        }

    monkeypatch.setattr(GPMGuidanceClient, "create_guidance", create)
    project = SimpleNamespace(tenant_id="tenant-a", project_id="case-1")
    event = OpenClawEvent(
        tenant_id="tenant-a",
        source_trace_id="trace-1",
        conversation_id="conversation-1",
        message_id="message-1",
        sender_id="supplier-1",
        authenticated_actor_id="sales-1",
        authenticated_actor_role="sales",
    )
    requirement = BuyerRequirement(
        product_type="shirt",
        quantity=1000,
        target_currency="USD",
    )
    quote = QuoteCalculation(
        supplier_id="supplier-1",
        unit_price=12.5,
        quantity=1000,
        currency="USD",
        supplier_total=12500.0,
        buyer_unit_price=15.0,
        buyer_total=15000.0,
        margin_rate=0.1667,
    )
    option = BuyerOption(
        option_id="quote-1",
        project_id="case-1",
        option_label="Recommended",
        option_type="balanced",
        supplier_id="supplier-1",
        quote=quote,
    )
    replies = [
        SupplierReply(
            project_id="case-1",
            supplier_id="supplier-1",
            raw_text="USD 12.50",
            unit_price=12.5,
            currency="EUR",
        )
    ]
    gltg = SimpleNamespace(gltg_run_id="gltg-run-1", source_api_version="v2")

    create_stage1_gpm_guidance(
        project=project,
        event=event,
        requirement=requirement,
        selected_option=option,
        replies=replies,
        gltg_result=gltg,
    )

    assert captured["tenant_id"] == "tenant-a"
    assert captured["actor_id"] == "sales-1"
    assert captured["actor_role"] == "sales"
    assert captured["case_id"] == "case-1"
    assert captured["quote_id"] == "quote-1"
    assert captured["supplier_quote"] == 12.5
    assert captured["currency"] == "USD"
    assert captured["buyer_unit_price"] == 15.0
    assert captured["buyer_total"] == 15000.0
    assert captured["supplier_total"] == 12500.0
    assert captured["margin_rate"] == 0.1667
    assert captured["gltg_run_id"] == "gltg-run-1"
    assert captured["gltg_api_version"] == "v2"


def test_untrusted_sender_identity_cannot_substitute_for_service_actor(
    monkeypatch,
):
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.delenv("GPM_SERVICE_ACTOR_ID", raising=False)
    monkeypatch.delenv("GPM_SERVICE_ACTOR_ROLE", raising=False)
    project = SimpleNamespace(tenant_id="tenant-a", project_id="case-1")
    event = OpenClawEvent(
        tenant_id="tenant-a",
        source_trace_id="trace-1",
        conversation_id="conversation-1",
        message_id="message-1",
        sender_id="self-asserted-sender",
        actor_id="self-asserted-actor",
        business_role="sales",
    )
    assert _gpm_actor(event) == ("", "")


def test_gltg_result_without_provider_run_id_gets_stable_snapshot_reference(
    monkeypatch,
):
    captured = []

    def create(self, **kwargs):
        captured.append(kwargs)
        return {
            "packet_id": "gpm_pkt_snapshot001",
            "recommendation": "negotiate",
            "confidence": "medium",
            "human_approval_required": True,
            "approval_status": "pending",
            "dispatched": False,
        }

    monkeypatch.setattr(GPMGuidanceClient, "create_guidance", create)
    project = SimpleNamespace(tenant_id="tenant-a", project_id="case-1")
    event = OpenClawEvent(
        tenant_id="tenant-a",
        source_trace_id="trace-1",
        conversation_id="conversation-1",
        authenticated_actor_id="sales-1",
        authenticated_actor_role="sales",
    )
    requirement = BuyerRequirement(product_type="shirt", quantity=1000)
    quote = QuoteCalculation(
        supplier_id="supplier-1",
        unit_price=12.5,
        quantity=1000,
        currency="USD",
        supplier_total=12500.0,
        buyer_unit_price=15.0,
        buyer_total=15000.0,
        margin_rate=0.1667,
    )
    option = BuyerOption(
        option_id="quote-1",
        project_id="case-1",
        option_label="Recommended",
        option_type="balanced",
        supplier_id="supplier-1",
        quote=quote,
    )
    replies = [
        SupplierReply(
            project_id="case-1",
            supplier_id="supplier-1",
            raw_text="USD 12.50",
            unit_price=12.5,
            currency="USD",
        )
    ]
    gltg = SimpleNamespace(
        p50_days=30.5,
        p80_days=35.25,
        p90_days=40.0,
        selected_confidence_days=35.25,
        deadline_risk_level="low",
        source_api_version="v1",
        assessment_schema_version=None,
        supplier_ids=["supplier-1"],
        gltg_run_id=None,
    )

    for _ in range(2):
        create_stage1_gpm_guidance(
            project=project,
            event=event,
            requirement=requirement,
            selected_option=option,
            replies=replies,
            gltg_result=gltg,
        )

    first_reference = captured[0]["gltg_run_id"]
    assert first_reference.startswith("gltg-snapshot-sha256-")
    assert captured[1]["gltg_run_id"] == first_reference
    assert captured[0]["gltg_api_version"] == "v1"
