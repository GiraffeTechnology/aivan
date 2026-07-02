"""Unified, fail-closed tenant resolver tests (PR29 unified + PR27 fail-closed salvage)."""
from __future__ import annotations

import pytest

from aivan.utils.tenant import (
    TenantMismatchError,
    TenantResolutionError,
    resolve_service_tenant,
    resolve_service_tenant_id,
    resolve_tenant,
)

_ENV = ("AIVAN_TENANT_ID", "GIRAFFE_DB_TENANT_ID", "GIRAFFE_TENANT_ID",
        "AIVAN_TEST_MODE", "AIVAN_TEST_TENANT_ID")


@pytest.fixture
def clean_tenant_env(monkeypatch):
    for k in _ENV:
        monkeypatch.delenv(k, raising=False)
    yield monkeypatch


# ── explicit env chain priority ──────────────────────────────────────────────

def test_service_tenant_prefers_aivan_tenant(clean_tenant_env):
    clean_tenant_env.setenv("AIVAN_TENANT_ID", "aivan_t")
    clean_tenant_env.setenv("GIRAFFE_DB_TENANT_ID", "gdb_t")
    clean_tenant_env.setenv("GIRAFFE_TENANT_ID", "g_t")
    assert resolve_service_tenant() == "aivan_t"


def test_service_tenant_falls_back_to_giraffe_db_tenant(clean_tenant_env):
    clean_tenant_env.setenv("GIRAFFE_DB_TENANT_ID", "gdb_t")
    assert resolve_service_tenant() == "gdb_t"


def test_service_tenant_falls_back_to_giraffe_tenant(clean_tenant_env):
    clean_tenant_env.setenv("GIRAFFE_TENANT_ID", "g_t")
    assert resolve_service_tenant() == "g_t"


# ── fail closed in production (no test fallback) ─────────────────────────────

def test_tenant_unresolved_in_production_fails_closed(clean_tenant_env):
    # No env, no test mode -> refuse to guess (no server_e2e default anymore).
    with pytest.raises(TenantResolutionError) as exc:
        resolve_service_tenant(context="giraffe_db_write")
    assert exc.value.error_code == "TENANT_RESOLUTION_REQUIRED"
    with pytest.raises(TenantResolutionError):
        resolve_service_tenant_id()


def test_test_mode_fallback_requires_both_flag_and_tenant(clean_tenant_env):
    # Flag alone (no AIVAN_TEST_TENANT_ID) still fails closed.
    clean_tenant_env.setenv("AIVAN_TEST_MODE", "true")
    with pytest.raises(TenantResolutionError):
        resolve_service_tenant()
    # Both set -> the sanctioned test fallback applies (with a warning).
    clean_tenant_env.setenv("AIVAN_TEST_TENANT_ID", "test_tenant")
    with pytest.warns(UserWarning):
        assert resolve_service_tenant() == "test_tenant"


def test_test_tenant_id_without_test_mode_is_ignored(clean_tenant_env):
    clean_tenant_env.setenv("AIVAN_TEST_TENANT_ID", "test_tenant")  # but no AIVAN_TEST_MODE
    with pytest.raises(TenantResolutionError):
        resolve_service_tenant()


# ── mismatch ─────────────────────────────────────────────────────────────────

def test_tenant_mismatch_raises(clean_tenant_env):
    with pytest.raises(TenantMismatchError) as exc:
        resolve_tenant(explicit="tenant_a", channel_binding="tenant_b", context="rfq")
    assert exc.value.error_code == "TENANT_MISMATCH"


def test_matching_sources_resolve(clean_tenant_env):
    assert resolve_tenant(explicit="t1", channel_binding="t1", case_ownership="t1") == "t1"


# ── unified resolver: GLTG v2 and giraffe-db graph use the same one ──────────

def test_gltg_v2_and_giraffe_db_graph_use_same_resolver(clean_tenant_env):
    clean_tenant_env.setenv("AIVAN_TENANT_ID", "unified_tenant")
    from aivan.integrations import gltg as gltg_mod
    from aivan.integrations import giraffe_db as gdb_mod

    # Both modules import the same fail-closed service-tenant resolver.
    assert gltg_mod.resolve_service_tenant is gdb_mod.resolve_service_tenant
    assert gltg_mod.resolve_service_tenant(context="x") == "unified_tenant"
    assert gdb_mod.resolve_service_tenant(context="y") == "unified_tenant"
