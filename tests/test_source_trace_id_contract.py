"""GPM quote-guidance boundary enforces the giraffe-db record-id contract."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.responses import JSONResponse

from aivan.gpm import router as gpm_router
from aivan.gpm.router import QuoteGuidanceRequest, create_quote_guidance


@pytest.fixture(autouse=True)
def _mock_runtime(monkeypatch):
    # Avoid any real LLM call; use the deterministic mock analysis path.
    monkeypatch.setenv("GPM_LLM_RUNTIME_MODE", "mock")
    gpm_router._reset_store(gpm_router.GPMPacketStore(db_client=None))


def _call(supplier_id):
    body = QuoteGuidanceRequest(sku="SKU-1", supplier_id=supplier_id, supplier_quote=4.5)
    return asyncio.run(create_quote_guidance(body, tenant_id="tenant-1"))


@pytest.mark.parametrize("supplier_id", ["SUP" "_SYN_1", "RFQ" "_SYN_12", "SUP" "_SYN_000001"])  # legacy-id-ok
def test_legacy_supplier_id_rejected_with_envelope(supplier_id):
    # The handler returns the envelope at the top level (JSONResponse), not a
    # raised HTTPException whose body would nest under ``detail``.
    result = _call(supplier_id)
    assert isinstance(result, JSONResponse)
    assert result.status_code == 422
    assert json.loads(result.body) == {
        "error": "invalid_record_id",
        "expected_format": "GDB_SYN_V1_<ENTITY>_<000001>",
        "received": supplier_id,
    }


def test_canonical_supplier_id_accepted():
    packet = _call("GDB_SYN_V1_SUP_000001")
    assert packet["supplier_id"] == "GDB_SYN_V1_SUP_000001"


def test_own_namespace_supplier_id_accepted():
    packet = _call("sup_001")
    assert packet["supplier_id"] == "sup_001"


def test_missing_supplier_id_accepted():
    packet = _call(None)
    assert packet["supplier_id"] is None
