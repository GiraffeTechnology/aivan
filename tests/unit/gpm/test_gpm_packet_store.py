"""GPMPacketStore unit tests — 12 scenarios with mock GiraffeDBClient."""
import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException

from aivan.gpm.packet_store import GPMPacketStore
from aivan.gpm.giraffe_db_client import GiraffeDBClientError

SAMPLE = {
    "packet_id": "gpm_pkt_test001",
    "tenant_id": "default",
    "sku": "TEST-SKU-G01",
    "supplier_quote": 3.75,
    "currency": "USD",
    "approval_status": "pending",
    "dispatched": False,
    "human_approval_required": True,
}


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.check_schema_version.return_value = {"schema_version": "0.1.0"}
    return db


@pytest.fixture
def store(mock_db):
    return GPMPacketStore(db_client=mock_db)


@pytest.fixture
def store_no_db():
    return GPMPacketStore(db_client=None)


# 1. save() → giraffe-db success → memory synced
def test_save_persists_to_db_and_memory(store, mock_db):
    mock_db.create_packet.return_value = SAMPLE
    result = store.save(SAMPLE)
    mock_db.create_packet.assert_called_once()
    assert result["packet_id"] == "gpm_pkt_test001"
    assert store._mem["gpm_pkt_test001"] is not None


# 2. save() → giraffe-db failure → memory fallback, no crash
def test_save_degrades_to_memory_on_db_failure(store, mock_db):
    mock_db.create_packet.side_effect = GiraffeDBClientError("conn refused", 503)
    result = store.save(SAMPLE)
    assert result["packet_id"] == "gpm_pkt_test001"
    assert "gpm_pkt_test001" in store._mem


# 3. get() → memory hit → no DB call
def test_get_memory_hit_skips_db(store, mock_db):
    store._mem["gpm_pkt_test001"] = SAMPLE
    result = store.get("gpm_pkt_test001")
    assert result is not None
    mock_db.get_packet.assert_not_called()


# 4. get() → memory miss → fetch from giraffe-db and backfill
def test_get_memory_miss_fetches_from_db(store, mock_db):
    mock_db.get_packet.return_value = SAMPLE
    result = store.get("gpm_pkt_test001")
    assert result is not None
    mock_db.get_packet.assert_called_once()
    assert "gpm_pkt_test001" in store._mem


# 5. get() → not found → None
def test_get_nonexistent_returns_none(store, mock_db):
    mock_db.get_packet.return_value = None
    assert store.get("nonexistent") is None


# 6. update_status() → giraffe-db success → memory synced
def test_update_status_writes_to_db_and_memory(store, mock_db):
    approved = {**SAMPLE, "approval_status": "approved", "operator_id": "op-001"}
    mock_db.update_packet_status.return_value = approved
    store._mem["gpm_pkt_test001"] = SAMPLE
    result = store.update_status("gpm_pkt_test001", "approved", "op-001")
    assert result["approval_status"] == "approved"
    assert store._mem["gpm_pkt_test001"]["approval_status"] == "approved"


# 7. update_status() → giraffe-db failure → memory fallback
def test_update_status_degrades_to_memory_on_db_failure(store, mock_db):
    mock_db.update_packet_status.side_effect = GiraffeDBClientError("err", 503)
    store._mem["gpm_pkt_test001"] = dict(SAMPLE)
    result = store.update_status("gpm_pkt_test001", "approved", "op-001")
    assert result["approval_status"] == "approved"


# 8. dispatched remains False after update_status
def test_dispatched_remains_false_after_update(store, mock_db):
    approved = {**SAMPLE, "approval_status": "approved", "dispatched": False}
    mock_db.update_packet_status.return_value = approved
    result = store.update_status("gpm_pkt_test001", "approved", "op-001")
    assert result["dispatched"] is False


# 9. write_audit() → success → True
def test_write_audit_returns_true_on_success(store, mock_db):
    mock_db.create_audit_record.return_value = {"audit_id": "abc"}
    ok = store.write_audit("gpm_pkt_test001", "op-001", "approved")
    assert ok is True


# 10. write_audit() → giraffe-db failure → False, no crash
def test_write_audit_returns_false_on_failure(store, mock_db):
    mock_db.create_audit_record.side_effect = GiraffeDBClientError("err", 503)
    ok = store.write_audit("gpm_pkt_test001", "op-001", "approved")
    assert ok is False


# 11. list_by_tenant() → uses giraffe-db
def test_list_by_tenant_uses_db(store, mock_db):
    mock_db.list_packets.return_value = [SAMPLE]
    result = store.list_by_tenant(tenant_id="default")
    assert len(result) == 1
    assert result[0]["packet_id"] == "gpm_pkt_test001"


# 12. list_by_tenant() → giraffe-db failure → memory fallback
def test_list_by_tenant_degrades_to_memory(store, mock_db):
    mock_db.list_packets.side_effect = GiraffeDBClientError("err", 503)
    store._mem["gpm_pkt_test001"] = SAMPLE
    result = store.list_by_tenant(tenant_id="default")
    assert len(result) >= 1


@pytest.mark.parametrize("operation", ["save", "get", "update", "audit", "list"])
def test_production_db_failure_never_degrades_to_memory(monkeypatch, mock_db, operation):
    monkeypatch.setenv("AIVAN_ENV", "production")
    store = GPMPacketStore(db_client=mock_db)
    store._mem["gpm_pkt_test001"] = dict(SAMPLE)

    if operation == "save":
        mock_db.create_packet.side_effect = GiraffeDBClientError("err", 503)
        call = lambda: store.save(SAMPLE)
    elif operation == "get":
        mock_db.get_packet.side_effect = GiraffeDBClientError("err", 503)
        call = lambda: store.get("gpm_pkt_test001", tenant_id="default")
    elif operation == "update":
        mock_db.update_packet_status.side_effect = GiraffeDBClientError("err", 503)
        call = lambda: store.update_status(
            "gpm_pkt_test001", "approved", "op-001", tenant_id="default"
        )
    elif operation == "audit":
        mock_db.create_audit_record.side_effect = GiraffeDBClientError("err", 503)
        call = lambda: store.write_audit("gpm_pkt_test001", "op-001", "approved")
    else:
        mock_db.list_packets.side_effect = GiraffeDBClientError("err", 503)
        call = lambda: store.list_by_tenant(tenant_id="default")

    with pytest.raises(HTTPException) as exc_info:
        call()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["error"] == "GPM_PERSISTENCE_UNAVAILABLE"


def test_production_durable_success_never_populates_memory(monkeypatch, mock_db):
    monkeypatch.setenv("AIVAN_ENV", "production")
    store = GPMPacketStore(db_client=mock_db)
    approved = {**SAMPLE, "approval_status": "approved"}
    mock_db.create_packet.return_value = SAMPLE
    mock_db.get_packet.return_value = SAMPLE
    mock_db.update_packet_status.return_value = approved

    assert store.save(SAMPLE) == SAMPLE
    assert store.get(SAMPLE["packet_id"], tenant_id="default") == SAMPLE
    assert store.update_status(
        SAMPLE["packet_id"], "approved", "op-001", tenant_id="default"
    ) == approved
    assert store._mem == {}
