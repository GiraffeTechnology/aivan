"""End-to-end WeChat procurement-message test.

Reproduces the exact WeChat message that previously failed with
"Agent couldn't generate a response." and asserts AIVAN now returns a valid,
meaningful, OpenClaw-compatible reply through both the /invoke endpoint and the
hardened /api/openclaw/events bridge path.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from aivan.api.main import app
from aivan.api.invoke import extract_rfq_intent

client = TestClient(app)

WECHAT_MESSAGE = "帮我询价 1000件格子纯棉衬衫，45天内交东京"


def _assert_meaningful(output: str) -> None:
    assert isinstance(output, str) and output.strip()
    lowered = output.lower()
    assert "traceback" not in lowered
    assert "validationerror" not in lowered


def test_wechat_message_intent_extraction():
    intent = extract_rfq_intent(WECHAT_MESSAGE)
    assert intent["intent"] == "supplier_quotation"
    assert intent["product"] == "格子纯棉衬衫"
    assert intent["quantity"] == 1000
    assert intent["delivery_time"] == "45天内"
    assert intent["destination"] == "东京"


def test_wechat_invoke_returns_meaningful_reply():
    resp = client.post(
        "/invoke",
        json={
            "session_id": "wechat-procurement-001",
            "user_input": WECHAT_MESSAGE,
            "context": {"channel": "wechat", "dry_run": True},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("ok", "error")
    _assert_meaningful(body["output"])
    # The extracted procurement facts must surface in the reply.
    for token in ("格子纯棉衬衫", "1000", "45天内", "东京"):
        assert token in body["output"]


def test_wechat_events_bridge_never_500s(monkeypatch):
    # Force the heavy RFQ pipeline to blow up (as a down dependency would) and
    # assert the bridge still returns HTTP 200 with a structured reply_text.
    import aivan.execution.rfq_execution as rfq

    def _boom(*_args, **_kwargs):
        from aivan.integrations.gltg import GLTGUnavailableError

        raise GLTGUnavailableError("GLTG service needs to be started")

    monkeypatch.setattr(rfq, "create_rfq_from_event", _boom)

    resp = client.post(
        "/api/openclaw/events",
        json={
            "source": "openclaw",
            "channel": "wechat",
            "conversation_id": "wechat-bridge-001",
            "sender_id": "wechat-user",
            "message_text": WECHAT_MESSAGE,
            "message_type": "text",
            "mode": "auto",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "reply_text" in body
    _assert_meaningful(body["reply_text"])
    assert "东京" in body["reply_text"]
