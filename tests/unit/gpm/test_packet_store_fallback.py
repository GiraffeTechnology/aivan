"""GPMPacketStore in-memory fallback tenant isolation tests."""
from __future__ import annotations

from aivan.gpm.packet_store import GPMPacketStore


def _packet(packet_id: str, tenant_id: str, status: str = "pending") -> dict:
    return {
        "packet_id": packet_id,
        "tenant_id": tenant_id,
        "sku": "SKU-TEST",
        "supplier_quote": 9.99,
        "currency": "USD",
        "human_approval_required": True,
        "approval_status": status,
        "dispatched": False,
    }


class TestListByTenantInMemoryIsolation:
    def test_list_by_tenant_excludes_other_tenant_packets(self):
        store = GPMPacketStore(db_client=None)
        store.save(_packet("pkt-a1", "tenant-a"))
        store.save(_packet("pkt-b1", "tenant-b"))

        result = store.list_by_tenant(tenant_id="tenant-b")
        ids = [p["packet_id"] for p in result]
        assert "pkt-b1" in ids
        assert "pkt-a1" not in ids

    def test_list_by_tenant_status_filter_combines_with_tenant_isolation(self):
        store = GPMPacketStore(db_client=None)
        store.save(_packet("pkt-a-pend", "tenant-a", "pending"))
        store.save(_packet("pkt-b-appr", "tenant-b", "approved"))
        store.save(_packet("pkt-b-pend", "tenant-b", "pending"))

        result = store.list_by_tenant(tenant_id="tenant-b", status="pending")
        ids = [p["packet_id"] for p in result]
        assert "pkt-b-pend" in ids
        assert "pkt-b-appr" not in ids
        assert "pkt-a-pend" not in ids

    def test_list_returns_all_statuses_when_no_status_filter(self):
        store = GPMPacketStore(db_client=None)
        store.save(_packet("pkt-b-p", "tenant-b", "pending"))
        store.save(_packet("pkt-b-a", "tenant-b", "approved"))
        store.save(_packet("pkt-a-p", "tenant-a", "pending"))

        result = store.list_by_tenant(tenant_id="tenant-b")
        ids = [p["packet_id"] for p in result]
        assert "pkt-b-p" in ids
        assert "pkt-b-a" in ids
        assert "pkt-a-p" not in ids


class TestGetInMemoryTenantIsolation:
    def test_get_returns_none_for_wrong_tenant(self):
        store = GPMPacketStore(db_client=None)
        store.save(_packet("pkt-a1", "tenant-a"))

        assert store.get("pkt-a1", tenant_id="tenant-b") is None

    def test_get_returns_packet_for_correct_tenant(self):
        store = GPMPacketStore(db_client=None)
        store.save(_packet("pkt-a1", "tenant-a"))

        result = store.get("pkt-a1", tenant_id="tenant-a")
        assert result is not None
        assert result["packet_id"] == "pkt-a1"

    def test_get_without_tenant_id_returns_any_cached_packet(self):
        """When no tenant_id provided (e.g. internal warmup), no filter applied."""
        store = GPMPacketStore(db_client=None)
        store.save(_packet("pkt-a1", "tenant-a"))

        result = store.get("pkt-a1")  # no tenant_id
        assert result is not None


class TestUpdateStatusInMemoryTenantIsolation:
    def test_update_status_wrong_tenant_returns_none(self):
        store = GPMPacketStore(db_client=None)
        store.save(_packet("pkt-a1", "tenant-a"))

        result = store.update_status("pkt-a1", "approved", "op", tenant_id="tenant-b")
        assert result is None
        # Original packet untouched
        original = store.get("pkt-a1")
        assert original["approval_status"] == "pending"

    def test_update_status_correct_tenant_succeeds(self):
        store = GPMPacketStore(db_client=None)
        store.save(_packet("pkt-a1", "tenant-a"))

        result = store.update_status("pkt-a1", "approved", "op-a", tenant_id="tenant-a")
        assert result is not None
        assert result["approval_status"] == "approved"
