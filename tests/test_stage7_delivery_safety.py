from __future__ import annotations

import importlib
import re
from pathlib import Path

from aivan.db.repositories.draft_repo import DraftRepository
from aivan.execution.rfq_execution import _send_user_control_notification
from aivan.openclaw.contracts import OpenClawEvent


ROOT = Path(__file__).resolve().parents[1]


def test_user_control_notification_never_sends_on_owner_resolution(db_session, monkeypatch):
    class ForbiddenClient:
        def send_message(self, _request):
            raise AssertionError("owner resolution must never become outbound consent")

    client_module = importlib.import_module("aivan.openclaw.client")
    monkeypatch.setattr(client_module, "get_openclaw_client", lambda: ForbiddenClient())
    event = OpenClawEvent(
        source="openclaw",
        channel="wechat",
        channel_account_id="trusted-account",
        conversation_id="owner-thread",
        message_id="inbound-1",
        sender_id="owner-1",
        authenticated_actor_id="owner-1",
        role_context="owner",
        message_text="start an RFQ",
        mode="command",
    )

    result = _send_user_control_notification(
        "project-stage7", event, "pending approval summary", db_session
    )

    draft = DraftRepository(db_session).get(result["draft_id"])
    assert result["sent"] is False
    assert result["owner_resolved"] is True
    assert "explicit outbound authorization required" in result["error"]
    assert draft is not None
    assert draft.status == "pending_approval"
    assert "outbound_authorization=required" in draft.notes


def test_openclaw_harness_has_no_automatic_assistant_reply_path():
    source = (
        ROOT / "integrations" / "openclaw-aivan-plugin" / "index.ts"
    ).read_text(encoding="utf-8")
    assert "buildSuccessResult" not in source
    assert "assistantTexts: [replyText]" not in source
    assert 'outboundAuthorization: "required"' in source
    assert "didSendViaMessagingTool: true" in source


def test_deployment_workflow_is_quarantined_and_has_no_remote_mutation():
    workflow = (ROOT / ".github" / "workflows" / "deploy-server.yml").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "sshpass",
        "StrictHostKeyChecking=no",
        "SERVER_SSH_PASSWORD",
        "pkill",
        "systemctl",
        "openclaw gateway restart",
        "443:",
        "8443:",
    )
    assert all(token not in workflow for token in forbidden)
    assert re.search(r"(?:\d{1,3}\.){3}\d{1,3}", workflow) is None
    assert "deployment_performed: \\`false\\`" in workflow
    assert "remote_connections_opened: \\`false\\`" in workflow


def test_workflow_ipv4_detection_covers_synthetic_hosts_and_embedded_literals():
    pattern = r"(?:\d{1,3}\.){3}\d{1,3}"
    for octets in ((192, 0, 2, 10), (198, 51, 100, 20), (203, 0, 113, 30), (127, 0, 0, 1)):
        value = ".".join(str(octet) for octet in octets)
        assert re.search(pattern, value)
        assert re.search(pattern, f"prefix{value}suffix")
    assert re.search(pattern, "No remote destination is configured") is None


def test_deployment_document_is_non_executable_and_uses_target_configuration():
    notice = (ROOT / "docs" / "DEPLOYMENT_CTYUN.md").read_text(encoding="utf-8")
    forbidden = (
        "git fetch",
        "git reset --hard",
        "ollama pull",
        "ollama rm",
        "systemctl restart",
        "systemctl stop",
        "systemctl start",
    )
    assert all(token not in notice for token in forbidden)
    assert "AIVAN_EXPECTED_EGRESS_POLICY" in notice
    assert "AIVAN_DEPLOYMENT_PROFILE" in notice
    assert "AIVAN_REVERSE_BRIDGE_PORT" in notice
    assert "Missing or mismatched configuration fails closed" in notice
    assert "protected-port" in notice


def test_production_template_documents_fail_closed_identity_and_persistence():
    template = (ROOT / "deploy" / "aivan.production.env.example").read_text(
        encoding="utf-8"
    )
    assert "AIVAN_TENANT_ID=" in template
    assert "AIVAN_TENANT_API_KEYS={}" in template
    assert "AIVAN_CORS_ORIGINS=" in template
    assert "AIVAN_UI_SESSION_SECRET=" in template
    assert "AIVAN_UI_ALLOWED_ROLES=" in template
    assert "AIVAN_CANDIDATE_SHA=" in template
    assert "AIVAN_NON_CHINA_EGRESS_POLICY=" in template
    assert "AIVAN_EXPECTED_EGRESS_POLICY=" in template
    assert "AIVAN_DEPLOYMENT_PROFILE=" in template
    assert "AIVAN_DEPLOYMENT_CLOUD=" in template
    assert "AIVAN_REVERSE_BRIDGE_PORT=" in template
    assert "AIVAN_DB_URL=" in template
    assert "GIRAFFE_DB_BASE_URL=" in template
    assert "OLLAMA_MODEL=qwen3.5:9b" in template
    assert "fails startup" in template
    assert "fail closed" in template


def test_dashboard_interpolations_escape_api_data_and_auth_is_session_scoped():
    script = (ROOT / "src" / "aivan" / "app" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    page = (ROOT / "src" / "aivan" / "app" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "function escapeHtml" in script
    assert "sessionStorage" not in script
    assert "localStorage" not in script
    assert "/api/session/login" in script
    assert "keyInput.value = ''" in script
    assert "Approve & Send" not in script
    assert "all data stays on your machine" not in page.lower()


def test_cors_wildcard_is_rejected_and_production_defaults_closed(monkeypatch):
    from aivan.api.main import _cors_origins

    monkeypatch.setenv("AIVAN_CORS_ORIGINS", "*")
    try:
        _cors_origins()
    except RuntimeError as exc:
        assert "must not contain '*'" in str(exc)
    else:
        raise AssertionError("wildcard CORS must fail closed")

    monkeypatch.setenv("AIVAN_CORS_ORIGINS", "")
    monkeypatch.setenv("AIVAN_ENV", "production")
    assert _cors_origins() == []
