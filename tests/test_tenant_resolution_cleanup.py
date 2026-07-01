"""PR22 cleanup regression tests: tenant resolution fails closed.

A multi-tenant procurement system must never silently guess a tenant. See
CLAUDE task Part B (§6).
"""
import pytest

from aivan.tenancy.resolver import (
    TenantMismatchError,
    TenantResolutionError,
    resolve_service_tenant,
    resolve_tenant,
)


def test_explicit_tenant_resolves():
    assert resolve_tenant(explicit="tenant_a") == "tenant_a"


def test_verified_channel_binding_resolves():
    assert resolve_tenant(channel_binding="tenant_b") == "tenant_b"


def test_verified_case_ownership_resolves():
    assert resolve_tenant(case_ownership="tenant_c") == "tenant_c"


def test_missing_tenant_fails_closed_in_production():
    with pytest.raises(TenantResolutionError):
        resolve_tenant()  # nothing provided, not test mode


def test_missing_tenant_test_mode_uses_configured_test_tenant_only(monkeypatch):
    monkeypatch.setenv("AIVAN_TEST_MODE", "true")
    with pytest.warns(UserWarning):
        assert resolve_tenant(test_tenant="tenant_test") == "tenant_test"


def test_test_mode_without_configured_test_tenant_still_fails_closed(monkeypatch):
    monkeypatch.setenv("AIVAN_TEST_MODE", "true")
    with pytest.raises(TenantResolutionError):
        resolve_tenant()  # test mode on but no test tenant configured


def test_fallback_not_used_when_test_mode_false(monkeypatch):
    monkeypatch.setenv("AIVAN_TEST_MODE", "false")
    with pytest.raises(TenantResolutionError):
        resolve_tenant(test_tenant="tenant_test")


def test_cross_tenant_mismatch_is_rejected():
    # e.g. inbound event tenant vs. project/procurement_case tenant disagree.
    with pytest.raises(TenantMismatchError):
        resolve_tenant(explicit="tenant_a", case_ownership="tenant_b")


def test_mismatch_between_binding_and_case_rejected():
    with pytest.raises(TenantMismatchError):
        resolve_tenant(channel_binding="tenant_a", case_ownership="tenant_z")


def test_agreeing_sources_resolve():
    assert resolve_tenant(explicit="tenant_a", case_ownership="tenant_a") == "tenant_a"


# ── Service tenant (giraffe-db / GLTG writes) ─────────────────────────────


def test_service_tenant_explicit(monkeypatch):
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant_prod")
    monkeypatch.delenv("AIVAN_TEST_MODE", raising=False)
    assert resolve_service_tenant() == "tenant_prod"


def test_service_tenant_fails_closed_without_config(monkeypatch):
    monkeypatch.delenv("AIVAN_TENANT_ID", raising=False)
    monkeypatch.delenv("GIRAFFE_DB_TENANT_ID", raising=False)
    monkeypatch.delenv("AIVAN_TEST_MODE", raising=False)
    with pytest.raises(TenantResolutionError):
        resolve_service_tenant()


def test_service_tenant_does_not_default_to_server_e2e(monkeypatch):
    """Regression: the old code silently defaulted to 'server_e2e'."""
    monkeypatch.delenv("AIVAN_TENANT_ID", raising=False)
    monkeypatch.delenv("GIRAFFE_DB_TENANT_ID", raising=False)
    monkeypatch.delenv("AIVAN_TEST_MODE", raising=False)
    try:
        result = resolve_service_tenant()
    except TenantResolutionError:
        result = None
    assert result != "server_e2e"


def test_giraffe_db_persist_fails_closed_without_tenant(monkeypatch):
    """persist_rfq_gltg_graph must not write business facts under a guessed tenant."""
    from aivan.integrations.giraffe_db import persist_rfq_gltg_graph
    from aivan.openclaw.contracts import OpenClawEvent
    from aivan.schemas.requirement import BuyerRequirement
    from aivan.schemas.rfq import RFQStrategy

    monkeypatch.setenv("AIVAN_PERSIST_GIRAFFE_DB_GRAPH", "true")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://giraffe-db.internal")
    monkeypatch.delenv("AIVAN_TENANT_ID", raising=False)
    monkeypatch.delenv("GIRAFFE_DB_TENANT_ID", raising=False)
    monkeypatch.delenv("AIVAN_TEST_MODE", raising=False)

    event = OpenClawEvent(conversation_id="c1", message_id="m1", channel="email", sender_id="cust")
    with pytest.raises(TenantResolutionError):
        persist_rfq_gltg_graph(
            event=event,
            project_id="proj_1",
            requirement=BuyerRequirement(quantity=10),
            strategy=RFQStrategy(),
            gltg=None,  # tenant resolution fails before gltg is ever read
        )
