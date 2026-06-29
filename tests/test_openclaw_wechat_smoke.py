"""Smoke tests for the root-app /healthz and /invoke routes.

The production OpenClaw / WeChat harness probes `GET /healthz` and invokes
`POST /invoke`. These were returning 404 because the routes were not registered
on the FastAPI app. These tests lock the routes in place and assert /invoke
accepts every supported payload shape and never returns 404/500.
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
    # raise_server_exceptions=False mirrors a real server: an unhandled pipeline
    # error flows through the registered fail-soft handler instead of bubbling up.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


def _assert_skill_envelope(resp):
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] in ("ok", "error")
    assert isinstance(body["output"], str) and body["output"].strip()
    lowered = body["output"].lower()
    assert "traceback" not in lowered


def test_healthz_returns_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_invoke_openclaw_standard_payload(client):
    resp = client.post(
        "/invoke",
        json={"session_id": "fix-001", "user_input": "ping", "context": {}},
    )
    _assert_skill_envelope(resp)


def test_invoke_wechat_webhook_payload(client):
    resp = client.post(
        "/invoke",
        json={
            "content": "帮我询价1000件T恤",
            "from_user": "wxid_test",
            "room_id": "room@chatroom",
        },
    )
    _assert_skill_envelope(resp)


def test_invoke_openclaw_event_payload(client):
    resp = client.post(
        "/invoke",
        json={
            "source": "openclaw",
            "channel": "openclaw-weixin",
            "conversation_id": "room123@chatroom",
            "message_text": "find supplier for M8 bolts",
        },
    )
    _assert_skill_envelope(resp)
