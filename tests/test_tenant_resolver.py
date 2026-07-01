"""Unified tenant resolver tests (PRD §13, §18.8)."""
from __future__ import annotations

from aivan.utils.tenant import DEFAULT_SERVICE_TENANT_ID, resolve_service_tenant_id


def test_service_tenant_prefers_aivan_tenant(monkeypatch):
    monkeypatch.setenv("AIVAN_TENANT_ID", "aivan_t")
    monkeypatch.setenv("GIRAFFE_DB_TENANT_ID", "gdb_t")
    monkeypatch.setenv("GIRAFFE_TENANT_ID", "g_t")
    assert resolve_service_tenant_id() == "aivan_t"


def test_service_tenant_falls_back_to_giraffe_db_tenant(monkeypatch):
    monkeypatch.delenv("AIVAN_TENANT_ID", raising=False)
    monkeypatch.setenv("GIRAFFE_DB_TENANT_ID", "gdb_t")
    assert resolve_service_tenant_id() == "gdb_t"


def test_service_tenant_default(monkeypatch):
    for k in ("AIVAN_TENANT_ID", "GIRAFFE_DB_TENANT_ID", "GIRAFFE_TENANT_ID"):
        monkeypatch.delenv(k, raising=False)
    assert resolve_service_tenant_id() == DEFAULT_SERVICE_TENANT_ID


def test_gltg_v2_and_giraffe_db_graph_use_same_tenant(monkeypatch):
    monkeypatch.setenv("AIVAN_TENANT_ID", "unified_tenant")
    from aivan.utils.tenant import resolve_service_tenant_id as r1
    from aivan.integrations.gltg import resolve_service_tenant_id as r2
    from aivan.integrations.giraffe_db import resolve_service_tenant_id as r3

    assert r1() == r2() == r3() == "unified_tenant"
