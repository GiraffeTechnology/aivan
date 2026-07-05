#!/usr/bin/env python3
"""Private-domain RFQ E2E smoke (no external model API).

Drives the RFQ execution loop end-to-end with external model APIs OFF, proving
the baseline closes without any external provider call. Uses the mock provider
as a stand-in local model and the GLTG fake transport for offline runs.

Scenario 1 — language boundary: raw Chinese input with no language-skill
service must stop at a safe operator confirmation (no GLTG run, no supplier
drafts, no leak of internal ids).

Scenario 2 — approval gate: with the language skill available (simulated via
the client's httpx MockTransport seam, same as the test suite), the canonical
RFQ must produce supplier drafts that are ALL pending human approval and never
auto-sent, a user IM approval notification, and the private-domain audit
events (GIRAFFE_CONTEXT_LOOKUP, GLTG_SIMULATION_CREATED,
USER_CONTROL_APPROVAL_REQUESTED).
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))
sys.path.insert(0, _REPO_ROOT)  # for tests.gltg_fake

os.environ.setdefault("AIVAN_EXTERNAL_MODEL_API_ENABLED", "false")
os.environ.setdefault("AIVAN_LLM_PROVIDER", "mock")
os.environ.setdefault("OPENCLAW_MOCK_MODE", "true")
os.environ.setdefault("AIVAN_DB_URL", "sqlite:///:memory:")
os.environ.setdefault("AIVAN_REQUIRE_HUMAN_APPROVAL", "true")
# Sanctioned test-mode tenant fallback (mirrors tests/conftest.py) so offline
# service calls resolve a tenant without a production placeholder.
os.environ.setdefault("AIVAN_TEST_MODE", "true")
os.environ.setdefault("AIVAN_TEST_TENANT_ID", "test_tenant")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from aivan.db.models import Base  # noqa: E402
from aivan.db.repositories.draft_repo import DraftRepository  # noqa: E402
from aivan.db.repositories.event_repo import ExecutionEventRepository  # noqa: E402
from aivan.execution.rfq_execution import create_rfq_from_event  # noqa: E402
from aivan.integrations import gltg_client as _gltg_client  # noqa: E402
from aivan.openclaw.contracts import OpenClawEvent  # noqa: E402


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _event(message_text: str, conv: str, msg: str) -> OpenClawEvent:
    return OpenClawEvent(
        source="openclaw",
        channel="wechat",
        conversation_id=conv,
        message_id=msg,
        sender_id="user_001",
        sender_display_name="Operator",
        message_text=message_text,
        role_context="user",
        mode="command",
    )


RFQ_ZH = "帮我询价 10000 件白色纯棉衬衣，45 天内交温哥华，高品质。"

# Simulated giraffe-language-skill responses for RFQ_ZH (mirrors the payload
# shape used by tests/test_language_skill_integration.py).
_NORMALIZE_RESPONSE = {
    "raw_text": RFQ_ZH,
    "language": {"detected": "zh", "confidence": 0.99},
    "canonical_language": "en",
    "canonical_text": (
        "RFQ: 10000 pcs high quality white cotton shirts, deliver to Vancouver within 45 days."
    ),
    "requested_output_language": "zh",
    "field_evidence": {
        "quantity": {"value": 10000, "source": "raw_rule", "span": "10000 件", "confidence": 1.0},
        "destination": {"value": "Vancouver", "source": "raw_rule+glossary", "span": "温哥华", "confidence": 1.0},
    },
    "translation": {"provider": "mock", "model": "mock", "glossary_version": "2026-07-01"},
    "warnings": [],
}

_STRUCTURE_RESPONSE = {
    "schema": "trade_rfq.v1",
    "validation_status": "valid",
    "structured": {
        "quantity": 10000,
        "quantity_unit": "pcs",
        "product_name": "white cotton shirt",
        "product_category": "apparel",
        "destination": "Vancouver",
        "lead_time_days": 45,
        "quality_level": "high",
        "intent": "supplier_rfq",
    },
    "missing_fields": [],
    "confidence_score": 0.95,
    "field_sources": {
        "quantity": "language_skill",
        "product_name": "language_skill",
        "product_category": "language_skill",
        "destination": "language_skill",
        "lead_time_days": "language_skill",
    },
}


def _language_skill_transport():
    import httpx

    def handle(request: "httpx.Request") -> "httpx.Response":
        if request.url.path == "/v1/inbound/normalize":
            return httpx.Response(200, json=_NORMALIZE_RESPONSE)
        if request.url.path == "/v1/structure/rfq":
            return httpx.Response(200, json=_STRUCTURE_RESPONSE)
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handle)


def scenario_language_boundary(db) -> None:
    print("── Scenario 1: raw Chinese input without language skill stops at safe confirmation")
    os.environ["AIVAN_LANGUAGE_SKILL_ENABLED"] = "false"
    result = create_rfq_from_event(
        _event(RFQ_ZH, "pd_e2e_conv_001", "pd_e2e_msg_001"),
        db,
    )
    print("   action:", result.action)
    print("   drafts_created:", result.drafts_created)

    assert "draft_" not in result.user_control_message, "raw draft ids leaked into reply"
    assert "Strategy=" not in result.user_control_message
    supplier_drafts = [
        d for d in DraftRepository(db).list_for_project(result.project_id)
        if d.target_role == "supplier"
    ]
    assert not supplier_drafts, "language boundary must block supplier drafts for raw non-English input"
    print("   [OK] blocked safely, no supplier drafts, no internal-id leak")


def scenario_approval_gate(db) -> None:
    print("── Scenario 2: canonicalized RFQ closes behind the approval gate")
    from aivan.integrations import language_skill_client

    os.environ["AIVAN_LANGUAGE_SKILL_ENABLED"] = "true"
    language_skill_client.set_default_transport(_language_skill_transport())
    try:
        result = create_rfq_from_event(
            _event(RFQ_ZH, "pd_e2e_conv_002", "pd_e2e_msg_002"),
            db,
        )
    finally:
        language_skill_client.set_default_transport(None)
        os.environ["AIVAN_LANGUAGE_SKILL_ENABLED"] = "false"
    project_id = result.project_id
    print("   action:", result.action)
    print("   drafts_created:", len(result.drafts_created))

    drafts = DraftRepository(db).list_for_project(project_id)
    supplier_drafts = [d for d in drafts if d.target_role == "supplier"]
    user_notifications = [
        d for d in drafts
        if d.target_role == "user" and "draft_type=approval_request_im" in (d.notes or "")
    ]
    events = ExecutionEventRepository(db).list_for_project(project_id)
    event_types = {e.event_type for e in events}

    assert result.drafts_created, "expected supplier drafts for a canonicalized RFQ"
    assert supplier_drafts, "expected supplier drafts persisted for the project"
    assert all(d.status == "pending_approval" for d in supplier_drafts), (
        "every counterparty draft must await human approval"
    )
    assert all(d.sent_at is None for d in supplier_drafts), (
        "no supplier message may be sent before approval"
    )
    assert user_notifications, "expected a user IM approval notification"
    assert "GIRAFFE_CONTEXT_LOOKUP" in event_types, f"missing GIRAFFE_CONTEXT_LOOKUP in {sorted(event_types)}"
    assert "GLTG_SIMULATION_CREATED" in event_types, f"missing GLTG_SIMULATION_CREATED in {sorted(event_types)}"
    assert "USER_CONTROL_APPROVAL_REQUESTED" in event_types, (
        f"missing USER_CONTROL_APPROVAL_REQUESTED in {sorted(event_types)}"
    )
    assert "draft_" not in result.user_control_message, "raw draft ids leaked into reply"

    print(f"   supplier drafts pending approval: {len(supplier_drafts)}")
    print(f"   user IM approval notifications  : {len(user_notifications)}")
    print(f"   audit events                    : {len(events)}")
    print("   [OK] drafts gated, nothing auto-sent, audit trail complete")


def main() -> int:
    # Offline GLTG fake so this runs without a live GLTG server. A missing
    # fake must fail loudly — scenario 2's assertions depend on GLTG running.
    from tests.gltg_fake import mock_transport

    _gltg_client.set_default_transport(mock_transport())

    scenario_language_boundary(_session())
    scenario_approval_gate(_session())
    print("\n[OK] private-domain RFQ loop closed without external model API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
