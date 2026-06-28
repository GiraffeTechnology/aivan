"""Route-level proof that /api/gpm/quote-guidance enforces the giraffe-db
record-id contract through the real FastAPI stack.

Direct-handler tests cannot prove the wire shape: FastAPI wraps an
``HTTPException(detail=...)`` under a ``detail`` key, so the documented
top-level ``invalid_record_id`` envelope is only verifiable by exercising the
mounted route with a TestClient.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from aivan.api.main import app
from aivan.gpm import router as gpm_router

QUOTE_GUIDANCE_URL = "/api/gpm/quote-guidance"


@pytest.fixture(autouse=True)
def _route_env(monkeypatch):
    # Dev-mode auth (no secret) resolves to the "default" tenant, matching how
    # other GPM route paths run in tests; mock mode avoids real LLM calls.
    monkeypatch.delenv("AIVAN_AUTH_SECRET", raising=False)
    monkeypatch.setenv("GPM_LLM_RUNTIME_MODE", "mock")
    gpm_router._reset_store(gpm_router.GPMPacketStore(db_client=None))


@pytest.fixture()
def client():
    return TestClient(app)


def _post(client, supplier_id):
    body = {"sku": "SKU-1", "supplier_quote": 4.5}
    if supplier_id is not None:
        body["supplier_id"] = supplier_id
    return client.post(QUOTE_GUIDANCE_URL, json=body)


# Retired legacy ids, short and zero-padded, exercised as invalid input. legacy-id-ok
@pytest.mark.parametrize("supplier_id", ["SUP" "_SYN_1", "RFQ" "_SYN_12", "SUP" "_SYN_000001"])  # legacy-id-ok
def test_legacy_supplier_id_returns_top_level_envelope(client, supplier_id):
    response = _post(client, supplier_id)
    assert response.status_code == 422
    assert response.json() == {
        "error": "invalid_record_id",
        "expected_format": "GDB_SYN_V1_<ENTITY>_<000001>",
        "received": supplier_id,
    }
    # The envelope must not be nested under FastAPI's HTTPException ``detail``.
    assert "detail" not in response.json()


@pytest.mark.parametrize(
    "supplier_id",
    ["GDB_SYN_V1_SUP_000001", "sup_001", "supplier_001", None],
)
def test_accepted_supplier_ids_not_rejected_by_contract(client, supplier_id):
    response = _post(client, supplier_id)
    assert response.status_code == 201
    assert response.json()["supplier_id"] == supplier_id
