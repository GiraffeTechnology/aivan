"""OpenClaw skill-invocation smoke test for AIVAN's POST /invoke endpoint.

Simulates exactly what OpenClaw sends during skill invocation and asserts the
response conforms to the OpenClaw skill contract. This does NOT go through
OpenClaw — it hits AIVAN directly to isolate the skill.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aivan.api.main import app

client = TestClient(app)


def _assert_skill_contract(body: dict) -> None:
    assert isinstance(body, dict)
    assert body["status"] in ("ok", "error")
    assert isinstance(body["output"], str) and body["output"].strip()
    assert isinstance(body["artifacts"], list)
    # No raw traceback / validation error must ever reach OpenClaw.
    lowered = body["output"].lower()
    assert "traceback" not in lowered
    assert "validationerror" not in lowered


def test_invoke_smoke_returns_skill_contract():
    resp = client.post(
        "/invoke",
        json={
            "session_id": "audit-smoke-001",
            "user_input": "find supplier for M8 bolts, quantity 10000",
            "context": {},
        },
    )
    assert resp.status_code == 200
    _assert_skill_contract(resp.json())


def test_invoke_is_unauthenticated_probe_safe(monkeypatch):
    # Even with API-key auth configured for the REST surface, the OpenClaw
    # invocation probe must reach /invoke without credentials.
    monkeypatch.setenv("AIVAN_API_KEY", "secret-key")
    resp = client.post(
        "/invoke",
        json={"session_id": "probe", "user_input": "hello", "context": {}},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] in ("ok", "error")


@pytest.mark.parametrize("key", ["user_input", "message", "text", "content", "input"])
def test_invoke_accepts_all_payload_shapes(key):
    resp = client.post("/invoke", json={"session_id": "shape", key: "需要采购100件T恤"})
    assert resp.status_code == 200
    _assert_skill_contract(resp.json())


def test_invoke_missing_text_returns_structured_error():
    resp = client.post("/invoke", json={"session_id": "no-text", "context": {}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "could not extract message text" in body["output"]
