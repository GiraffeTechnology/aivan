"""Acceptance tests for the myaivan Web first iteration (PRD §21.1).

Covers the 20 required test cases: pages, conversation flow, upload,
outbound draft review actions (copy / ✉️ / ✅ / ❌), email adapter states,
Markdown backup, audit logging, and product-positioning guardrails.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "aivan" / "app" / "static"
TEMPLATES = ROOT / "src" / "aivan" / "app" / "templates"

BUYER_INQUIRY = (
    "Buyer inquiry: we need 10000 white cotton shirts delivered to Vancouver within 45 days. "
    "Please quote your best price."
)


@pytest.fixture(autouse=True)
def _web_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AIVAN_WEB_UPLOAD_DIR", str(tmp_path / "uploads"))
    # conftest sets OPENCLAW_MOCK_MODE=true → email adapter defaults to mock.


def _new_case(api_client) -> str:
    state = api_client.post("/api/myaivan/cases", json={}).json()
    return state["case"]["id"]


def _make_draft(api_client, case_id: str, text_suffix: str = " Please draft a reply for wechat.") -> dict:
    state = api_client.post(
        f"/api/myaivan/cases/{case_id}/messages",
        json={"content": BUYER_INQUIRY + text_suffix, "type": "paste"},
    ).json()
    assert state["outboundDrafts"], "expected a generated draft"
    return state["outboundDrafts"][-1]


def _events(api_client, case_id: str) -> list[str]:
    state = api_client.get(f"/api/myaivan/cases/{case_id}").json()
    return [log["event"] for log in state["auditLogs"]]


# ── 1–2: welcome page & navigation ────────────────────────────────────────────

def test_00_root_domain_entry_redirects_to_myaivan(api_client):
    resp = api_client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/myaivan"
    head = api_client.head("/", follow_redirects=False)
    assert head.status_code == 303
    assert head.headers["location"] == "/myaivan"


def test_01_welcome_page_renders(api_client):
    assert api_client.head("/myaivan").status_code == 200
    resp = api_client.get("/myaivan")
    assert resp.status_code == 200
    # English is the canonical/system language in the markup…
    assert "Welcome back. What should your AIVAN handle today?" in resp.text
    assert "Start Working" in resp.text
    assert "MyAIVAN is your AIVAN digital trade assistant" in resp.text
    assert "/static/giraffe-logo.png" in resp.text
    assert (STATIC / "giraffe-logo.png").is_file()
    css = (STATIC / "myaivan.css").read_text()
    assert ".mv-giraffe-icon" in css
    logo_css = css.split(".mv-giraffe-icon", 1)[1].split("}", 1)[0]
    assert "vmin" in logo_css and "max-height" in logo_css and "height: auto" in logo_css
    assert 'data-i18n="welcome.title"' in resp.text
    # …and the required Chinese copy is served through the zh catalog.
    zh = api_client.get("/api/myaivan/i18n/zh").json()["strings"]
    assert zh["welcome.title"] == "欢迎回来。今天要让你的 AIVAN 处理哪一条询价？"
    assert zh["welcome.start"] == "开始工作"


def test_02_start_working_navigates_to_conversation(api_client):
    welcome = api_client.get("/myaivan").text
    assert 'href="/myaivan/work"' in welcome
    resp = api_client.get("/myaivan/work")
    assert resp.status_code == 200


# ── 3–5: conversation page structure & alignment ─────────────────────────────

def test_03_conversation_page_renders_three_areas(api_client):
    html = api_client.get("/myaivan/work").text
    assert ">MyAIVAN<" in html
    assert 'id="conversation-stream"' in html   # top
    assert 'id="stream-review-resizer"' in html
    assert 'id="review-area"' in html           # middle
    assert 'id="review-input-resizer"' in html
    assert 'id="message-input"' in html         # bottom
    assert 'id="paste-btn"' in html
    assert 'id="file-input"' in html and 'id="image-input"' in html
    assert 'id="voice-btn"' in html
    assert 'id="send-btn"' in html
    assert 'id="message-input" rows="4"' in html
    assert 'id="lang-select"' in html  # language switcher
    css = (STATIC / "myaivan.css").read_text()
    input_css = css.split(".mv-input-row textarea", 1)[1].split("}", 1)[0]
    assert "min-height" in input_css and "overflow-y: auto" in input_css
    assert "row-resize" in css
    js = (STATIC / "myaivan.js").read_text()
    assert "myaivan.layoutHeights" in js
    assert "stream-review-resizer" in js and "review-input-resizer" in js


def test_04_user_messages_align_right():
    css = (STATIC / "myaivan.css").read_text()
    js = (STATIC / "myaivan.js").read_text()
    assert "mv-bubble-user" in js and '"user"' in js
    assert ".mv-bubble-user" in css and "flex-end" in css.split(".mv-bubble-user", 1)[1][:120]


def test_05_aivan_messages_align_left():
    css = (STATIC / "myaivan.css").read_text()
    js = (STATIC / "myaivan.js").read_text()
    assert "mv-bubble-aivan" in js
    assert ".mv-bubble-aivan" in css and "flex-start" in css.split(".mv-bubble-aivan", 1)[1][:140]


# ── 6: paste works or safe fallback ───────────────────────────────────────────

def test_06_paste_message_accepted_and_fallback_copy_present(api_client):
    case_id = _new_case(api_client)
    state = api_client.post(
        f"/api/myaivan/cases/{case_id}/messages",
        json={"content": BUYER_INQUIRY, "type": "paste"},
    )
    assert state.status_code == 200
    roles = [(m["role"], m["type"]) for m in state.json()["messages"]]
    assert ("user", "paste") in roles
    assert any(role == "aivan" for role, _ in roles)
    js = (STATIC / "myaivan.js").read_text()
    assert "Ctrl+V / Cmd+V" in js  # clipboard-permission fallback instruction


# ── 7–8: uploads ──────────────────────────────────────────────────────────────

def test_07_file_upload_works(api_client):
    case_id = _new_case(api_client)
    resp = api_client.post(
        f"/api/myaivan/cases/{case_id}/uploads",
        files={
            "file": (
                "spec.txt",
                io.BytesIO(b"Buyer asks for 5000 cotton shirts to Tokyo within 45 days."),
                "text/plain",
            )
        },
    )
    assert resp.status_code == 200
    state = resp.json()
    assert state["attachments"] and state["attachments"][0]["kind"] == "file"
    summaries = [m for m in state["messages"] if m["role"] == "aivan" and m["type"] == "structured_summary"]
    assert any("Text preview" in m["content"] for m in summaries)
    assert any("5000 cotton shirts" in m["metadata"]["understanding"]["textPreview"] for m in summaries)
    assert "file_uploaded" in _events(api_client, case_id)


def test_08_image_upload_works(api_client):
    case_id = _new_case(api_client)
    png_1x1 = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00"
        b"\x90wS\xde"
    )
    resp = api_client.post(
        f"/api/myaivan/cases/{case_id}/uploads",
        files={"file": ("sample.png", io.BytesIO(png_1x1), "image/png")},
    )
    assert resp.status_code == 200
    state = resp.json()
    assert state["attachments"][0]["kind"] == "image"
    summaries = [m for m in state["messages"] if m["role"] == "aivan" and m["type"] == "structured_summary"]
    assert any("1x1" in m["content"] for m in summaries)
    assert "image_uploaded" in _events(api_client, case_id)


# ── 9: voice placeholder is safe ──────────────────────────────────────────────

def test_09_voice_button_is_placeholder_not_fake_transcription():
    js = (STATIC / "myaivan.js").read_text()
    assert "Voice input coming soon" in js
    assert "transcri" not in js.lower()  # no fake transcription implemented


# ── 10: draft appears in review area ─────────────────────────────────────────

def test_10_generated_draft_appears_in_review_area(api_client):
    case_id = _new_case(api_client)
    draft = _make_draft(api_client, case_id)
    assert draft["status"] == "draft"
    assert draft["channel"] == "wechat"
    assert draft["body"]
    assert "draft_generated" in _events(api_client, case_id)


# ── 11: copy ─────────────────────────────────────────────────────────────────

def test_11_copy_marks_copied_and_audits(api_client):
    case_id = _new_case(api_client)
    draft = _make_draft(api_client, case_id)
    resp = api_client.post(f"/api/myaivan/cases/{case_id}/drafts/{draft['id']}/copied")
    assert resp.status_code == 200
    assert resp.json()["outboundDrafts"][-1]["status"] == "copied"
    assert "draft_copied" in _events(api_client, case_id)


# ── 12: ✅ mark as manually sent ──────────────────────────────────────────────

def test_12_mark_manually_sent(api_client):
    case_id = _new_case(api_client)
    draft = _make_draft(api_client, case_id)
    resp = api_client.post(f"/api/myaivan/cases/{case_id}/drafts/{draft['id']}/mark-sent")
    assert resp.status_code == 200
    state = resp.json()
    assert state["outboundDrafts"][-1]["status"] == "manually_sent"
    assert state["case"]["status"] == "sent"
    assert "manual_send_confirmed" in _events(api_client, case_id)


# ── 13: ❌ reject ─────────────────────────────────────────────────────────────

def test_13_reject_draft_and_aivan_asks_for_revision(api_client):
    case_id = _new_case(api_client)
    draft = _make_draft(api_client, case_id)
    resp = api_client.post(f"/api/myaivan/cases/{case_id}/drafts/{draft['id']}/reject")
    assert resp.status_code == 200
    state = resp.json()
    assert state["outboundDrafts"][-1]["status"] == "rejected"
    aivan_texts = [m["content"] for m in state["messages"] if m["role"] == "aivan"]
    assert any("What should I change" in t for t in aivan_texts)
    assert "draft_rejected" in _events(api_client, case_id)
    # A rejected draft cannot be re-approved or emailed.
    conflict = api_client.post(f"/api/myaivan/cases/{case_id}/drafts/{draft['id']}/mark-sent")
    assert conflict.status_code == 409


# ── 14: ✉️ email via adapter (mock mode) ─────────────────────────────────────

def test_14_email_send_uses_adapter_mock_mode(api_client):
    case_id = _new_case(api_client)
    draft = _make_draft(api_client, case_id, " Please draft a reply for email.")
    resp = api_client.post(
        f"/api/myaivan/cases/{case_id}/drafts/{draft['id']}/send-email",
        json={"recipient": "buyer@example.com"},
    )
    assert resp.status_code == 200
    state = resp.json()
    assert state["emailResult"]["success"] is True
    assert state["emailResult"]["provider"] == "mock"  # never claimed as real delivery
    assert state["outboundDrafts"][-1]["status"] == "email_sent"
    events = _events(api_client, case_id)
    assert "email_send_requested" in events and "email_sent" in events


# ── 15: email unavailable state ───────────────────────────────────────────────

def test_15_email_not_configured_is_safe(api_client, monkeypatch):
    monkeypatch.delenv("OPENCLAW_MOCK_MODE", raising=False)
    monkeypatch.delenv("AIVAN_WEB_EMAIL_MOCK", raising=False)
    monkeypatch.delenv("AIVAN_EMAIL_SEND_MODE", raising=False)

    status = api_client.get("/api/myaivan/email/status").json()
    assert status["status"] == "not_configured"

    case_id = _new_case(api_client)
    draft = _make_draft(api_client, case_id, " Please draft a reply for email.")
    resp = api_client.post(
        f"/api/myaivan/cases/{case_id}/drafts/{draft['id']}/send-email",
        json={"recipient": "buyer@example.com"},
    )
    assert resp.status_code == 200
    result = resp.json()["emailResult"]
    assert result["success"] is False
    assert "not configured" in result["error"].lower()
    assert resp.json()["outboundDrafts"][-1]["status"] == "failed"
    assert "email_failed" in _events(api_client, case_id)


# ── 16: backup exports markdown ───────────────────────────────────────────────

def test_16_backup_exports_markdown(api_client):
    case_id = _new_case(api_client)
    draft = _make_draft(api_client, case_id)
    api_client.post(f"/api/myaivan/cases/{case_id}/drafts/{draft['id']}/mark-sent")
    resp = api_client.get(f"/api/myaivan/cases/{case_id}/backup.md")
    assert resp.status_code == 200
    md = resp.text
    assert md.startswith("# AIVAN Case Backup")
    for section in ("## Conversation", "## Outbound Drafts", "## Audit Log"):
        assert section in md
    assert "manually_sent" in md
    assert "backup_exported" in _events(api_client, case_id)


# ── 17: audit log records copy/send/reject ────────────────────────────────────

def test_17_audit_log_records_full_review_cycle(api_client):
    case_id = _new_case(api_client)
    draft = _make_draft(api_client, case_id)
    api_client.post(f"/api/myaivan/cases/{case_id}/drafts/{draft['id']}/copied")
    api_client.post(f"/api/myaivan/cases/{case_id}/drafts/{draft['id']}/mark-sent")
    second = _make_draft(api_client, case_id)
    api_client.post(f"/api/myaivan/cases/{case_id}/drafts/{second['id']}/reject")
    events = _events(api_client, case_id)
    for expected in ("case_created", "message_received", "draft_generated",
                     "draft_copied", "manual_send_confirmed", "draft_rejected"):
        assert expected in events, f"missing audit event {expected}"


# ── 18: no direct IM sending ──────────────────────────────────────────────────

def test_18_no_direct_im_send_implemented():
    from aivan.web import router as web_router

    paths = {route.path for route in web_router.router.routes}
    for path in paths:
        assert "im" not in path.split("/")[-1] and "wechat" not in path and "whatsapp" not in path, (
            f"unexpected IM outbound route: {path}"
        )
    # The web module never calls the OpenClaw IM send client.
    source = (ROOT / "src" / "aivan" / "web").rglob("*.py")
    for py in source:
        text = py.read_text()
        assert "get_openclaw_client" not in text, f"{py.name} must not send IM messages"
        assert "send_message" not in text, f"{py.name} must not send IM messages"


# ── 19–20: positioning guardrails ─────────────────────────────────────────────

def test_19_ui_does_not_describe_aivan_as_generic_chatbot():
    for name in ("myaivan_welcome.html", "myaivan_work.html"):
        text = (TEMPLATES / name).read_text().lower()
        assert "chatbot" not in text
        assert "crm" not in text


def test_20_product_copy_keeps_trade_assistant_positioning():
    from aivan.web import i18n

    welcome = (TEMPLATES / "myaivan_welcome.html").read_text()
    work = (TEMPLATES / "myaivan_work.html").read_text()
    assert "digital trade assistant" in welcome
    assert "digital trade assistant" in work
    assert "MyAIVAN is your AIVAN digital trade assistant" in welcome
    assert "数字业务员" in i18n.CATALOG_ZH["welcome.tagline"]
    assert "数字业务员" in i18n.CATALOG_ZH["work.brand_sub"]


# ── Extra behavior guards ─────────────────────────────────────────────────────

def test_risk_note_present_for_price_and_leadtime_drafts(api_client):
    case_id = _new_case(api_client)
    draft = _make_draft(api_client, case_id)
    # Generated body references quantity/lead time → at least medium risk.
    assert draft["riskLevel"] in ("medium", "high")
    assert draft["riskNotes"]


def test_chinese_input_asks_for_canonicalization_not_extraction(api_client):
    case_id = _new_case(api_client)
    state = api_client.post(
        f"/api/myaivan/cases/{case_id}/messages",
        json={"content": "帮我询价 5000 件格子衬衫，45 天交东京。", "type": "paste"},
    ).json()
    turn = state["turn"]["analysis"]
    assert turn["language"] == "zh"
    assert turn["extracted"] == {}  # language boundary: no local extraction
    aivan_texts = [m["content"] for m in state["messages"] if m["role"] == "aivan"]
    assert any("语言标准化" in t or "确认" in t for t in aivan_texts)


def test_invalid_message_returns_controlled_error(api_client):
    case_id = _new_case(api_client)
    resp = api_client.post(f"/api/myaivan/cases/{case_id}/messages", json={"content": ""})
    assert resp.status_code == 422
    resp = api_client.get("/api/myaivan/cases/nonexistent")
    assert resp.status_code == 404
