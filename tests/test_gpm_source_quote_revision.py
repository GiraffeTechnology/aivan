"""GPM guidance follows actual supplier quote revisions, not random UI IDs."""
from types import SimpleNamespace

import pytest

from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.execution.gpm_guidance import create_stage1_gpm_guidance
from aivan.integrations.gpm_guidance_client import GPMGuidanceClient, GPMGuidanceUnavailableError
from aivan.openclaw.contracts import OpenClawEvent
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply


@pytest.fixture
def captured(monkeypatch):
    requests = []
    def create(self, **kwargs):
        requests.append(kwargs)
        return {"packet_id": "gpm_packet_fixture", "recommendation": "review", "confidence": "medium"}
    monkeypatch.setattr(GPMGuidanceClient, "create_guidance", create)
    return requests


def reply(price=12.5, currency="GBP"):
    return SupplierReply(project_id="case-1", supplier_id="supplier-1", unit_price=price,
                         currency=currency, raw_text=f"Quote {price} {currency}; MOQ 100.", moq=100)


def options(replies):
    return generate_buyer_options(BuyerRequirement(project_id="case-1", quantity=100), replies, [], "case-1")


def guidance(option, replies):
    return create_stage1_gpm_guidance(project=SimpleNamespace(tenant_id="tenant-a", project_id="case-1"),
        event=OpenClawEvent(tenant_id="tenant-a", conversation_id="quote-revisions", source_trace_id="trace-1", message_id="message-1",
                           authenticated_actor_id="sales-1", authenticated_actor_role="sales"),
        requirement=BuyerRequirement(project_id="case-1", quantity=100), selected_option=option,
        replies=replies, gltg_result=SimpleNamespace(gltg_run_id="gltg-run-1", source_api_version="v2"))


def test_regenerated_options_share_quote_revision_and_effective_idempotency(captured):
    source = reply()
    first, second = options([source])[0], options([source])[0]
    assert first.option_id != second.option_id
    guidance(first, [source])
    guidance(second, [source])
    assert captured[0]["quote_id"] != first.option_id
    assert captured[0]["quote_id"] == captured[1]["quote_id"]
    assert captured[0]["idempotency_key"] == captured[1]["idempotency_key"]


def test_latest_supplier_revision_does_not_consume_older_reply(captured):
    old, revised = reply(12.5), reply(13.75)
    current = options([old, revised])[0]
    guidance(current, [old, revised])
    assert captured[0]["supplier_quote"] == 13.75
    guidance(options([old])[0], [old])
    assert captured[0]["quote_id"] != captured[1]["quote_id"]


def test_superseded_selected_revision_rejected_before_gpm(captured):
    old, revised = reply(12.5), reply(13.75)
    with pytest.raises(GPMGuidanceUnavailableError, match="GPM_SOURCE_QUOTE_SUPERSEDED"):
        guidance(options([old])[0], [old, revised])
    assert captured == []


def test_competing_supplier_cannot_substitute_for_selected_quote(captured):
    own = reply()
    other = reply(1.0).model_copy(update={"supplier_id": "other-supplier"})
    with pytest.raises(GPMGuidanceUnavailableError, match="GPM_SOURCE_QUOTE_MISSING"):
        guidance(options([own])[0], [other])
    assert captured == []


def test_legacy_option_with_changed_source_terms_rejected(captured):
    old, revised = reply(12.5), reply(13.75)
    legacy = options([old])[0].model_copy(update={"source_quote_reference": ""})
    with pytest.raises(GPMGuidanceUnavailableError, match="GPM_SOURCE_QUOTE_MISMATCH"):
        guidance(legacy, [old, revised])
    assert captured == []
