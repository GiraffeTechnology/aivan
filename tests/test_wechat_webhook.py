"""Regression tests for the WeChat -> OpenClaw -> AIVAN skill-invocation path.

Background: messages from WeChat reach AIVAN through the OpenClaw bridge plugin
(`integrations/openclaw-aivan-plugin`), which normalises them into an
OpenClaw-standard event and POSTs to AIVAN's skill-invocation endpoints. A raw
HTTP 500 from those endpoints makes OpenClaw mark the skill as broken, so AIVAN
must always answer with a valid {"status": "ok"|"error", "output": ...} envelope.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aivan.db.models import Base


@pytest.fixture
def client():
    """TestClient with an in-memory DB and server exceptions surfaced as responses."""
    from aivan.api.main import app, get_db

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    os.environ.pop("AIVAN_API_KEY", None)
    app.dependency_overrides[get_db] = override_db
    # raise_server_exceptions=False mirrors a real server: unhandled errors flow
    # through the registered exception handler instead of bubbling into the test.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


def _wechat_event() -> dict:
    """An OpenClaw-standard event as the WeChat bridge forwards it to AIVAN."""
    return {
        "source": "openclaw",
        "channel": "openclaw-weixin",
        "conversation_id": "room123@chatroom",
        "sender_id": "wxid_test",
        "message_text": "find supplier for M8 bolts",
        "message_type": "text",
        "mode": "auto",
    }


@pytest.mark.parametrize(
    "path",
    ["/api/skill/invoke", "/api/openclaw/events", "/api/rfq/create-from-event"],
)
def test_wechat_event_returns_skill_envelope(client, path):
    resp = client.post(path, json=_wechat_event())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] in ("ok", "error")
    # The OpenClaw plugin sends `reply_text` (not `output`) to WeChat, so both
    # must be present and non-empty, and they are kept identical.
    assert isinstance(body.get("output"), str) and body["output"].strip()
    assert isinstance(body.get("reply_text"), str) and body["reply_text"].strip()
    assert body["reply_text"] == body["output"]


def test_minimal_payload_does_not_500(client):
    """Even a near-empty payload must not surface a raw 500 to OpenClaw."""
    resp = client.post("/api/skill/invoke", json={"message_text": "hello"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] in ("ok", "error")
    assert body["output"].strip()
    assert body["reply_text"].strip()


def test_unhandled_exception_returns_200_error_envelope(client, monkeypatch):
    """Any uncaught exception on a skill route becomes a 200 error envelope with a
    WeChat-visible reply_text, never an HTTP 500 ('skill broken') or a traceback."""
    import aivan.api.main as main

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated downstream failure\nTraceback (most recent call last)")

    monkeypatch.setattr(main, "_skill_response", _boom)

    resp = client.post("/api/skill/invoke", json=_wechat_event())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert body["output"].strip()
    assert body["reply_text"].strip()
    assert "traceback" not in body["output"].lower()
    assert "traceback" not in body["reply_text"].lower()


def test_non_skill_route_keeps_500_on_unhandled_exception(client, monkeypatch):
    """Fail-soft is scoped to skill routes; other routes keep standard 500
    semantics rather than the OpenClaw envelope."""
    import aivan.platforms.platform_registry as registry

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated registry failure")

    monkeypatch.setattr(registry, "list_suggestions", _boom)

    resp = client.get("/api/platforms/suggestions")
    assert resp.status_code == 500
    assert "status" not in resp.json()


def test_auth_error_keeps_its_status_code(client):
    """The global handler must not swallow explicit HTTP auth errors into a 200."""
    os.environ["AIVAN_API_KEY"] = "secret-key-abc"
    try:
        resp = client.post("/api/openclaw/events", json=_wechat_event())
        assert resp.status_code == 401
    finally:
        os.environ.pop("AIVAN_API_KEY", None)
