"""Actual configured email HTTP transport into a synthetic loopback recorder.

The recorder is a labelled channel-contract fixture, not an email provider and
not evidence of real-world delivery. Core product and dependency APIs stay real.
"""
from __future__ import annotations

import json
import subprocess
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def run_email_acceptance(run):
    messages = []

    class Recorder(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/messages/send":
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if body.get("channel") not in {"email", "smtp"} or body.get("target_peer_id") != "synthetic-buyer@example.invalid":
                self.send_error(422, "Only the synthetic email fixture recipient is allowed")
                return
            messages.append(body)
            result = {"success": True, "message_id": f"synthetic-recorder-{len(messages)}",
                      "sent_at": datetime.now(timezone.utc).isoformat()}
            data = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"

    def configure(enabled):
        command = [str(run.prefix / "myaivan"), "prepare", "--openclaw-url", url if enabled else "",
                   "--enable-email" if enabled else "--disable-email", "--restart"]
        result = subprocess.run(command, capture_output=True, timeout=180)
        run.results.setdefault("email_configuration_checks", []).append({
            "configured": enabled, "exit_code": result.returncode, "loopback_only": True})
        run.flush()
        if result.returncode:
            raise AssertionError("Installed email configuration/restart failed; inspect private installation logs")

    def event(text, message_id, *, role="buyer", case=None):
        actor = run.supplier_id if role == "supplier" else f"email-buyer-{run.run_id}"
        headers = run.headers("web", key=message_id)
        headers.update({"X-AIVAN-Participant-ID": actor, "X-AIVAN-Participant-Role": role,
                        "X-AIVAN-Participant-Conversation-Role": f"{role}_thread"})
        payload = {"source": "myaivan", "channel": "email", "conversation_id": f"email-{role}-{run.run_id}",
                   "message_id": f"{message_id}-{run.run_id}", "sender_id": actor if role == "supplier" else "synthetic-buyer@example.invalid",
                   "sender_display_name": f"Synthetic email {role}", "message_text": text}
        if case:
            payload["project_id"] = case
        return run.request("web", "POST", "/api/rfq/create-from-event", headers=headers, body=payload)

    try:
        configure(True)
        created = event("Please quote cotton shirts for our synthetic acceptance test.", "email-inquiry")
        case_id = created["project_id"]
        initial = run.request("web", "GET", f"/api/workbench/cases/{case_id}/requirement")
        run.request("web", "PATCH", f"/api/workbench/cases/{case_id}/requirement", key="email-clarify", body={
            "expected_requirement_sha256": initial["requirement_sha256"], "fields": {
                "category": "apparel", "product_type": "cotton shirt", "quantity": 1200,
                "fabric_material": "cotton", "gsm": 180, "color": "white", "size_ratio": "S/M/L/XL 300/300/300/300",
                "packaging": "Individually bagged", "destination": "Vancouver", "delivery_days": 60}})
        replied = event("We quote unit price USD 8.50; MOQ 100 pcs; production lead time 30 days. These are synthetic acceptance quotation facts.", "email-reply", role="supplier", case=case_id)
        assert replied["action"] == "buyer_options_ready", replied
        draft_id = replied["drafts_created"][0]
        assert not messages, "No channel transport may occur while generating a draft"
        run.request("web", "POST", f"/api/drafts/{draft_id}/approve",
                    body={"preview_id": "render_" + "0" * 32}, expected=(404,))
        assert not messages, "An invalid preview proof must not reach transport"
        preview = run.request("web", "POST", f"/api/drafts/{draft_id}/preview", body={"target_language": "en"})
        assert preview["recipient"] == "synthetic-buyer@example.invalid"
        assert preview["manual_delivery"] is False
        assert not messages, "Preview must not reach transport"
        approved = run.request("web", "POST", f"/api/drafts/{draft_id}/approve", body={"preview_id": preview["preview_id"]})
        assert approved["sent"] is True and len(messages) == 1, approved
        assert messages[0]["message_text"] == preview["message_text"]
        assert messages[0]["target_peer_id"] == "synthetic-buyer@example.invalid"
        run.request("web", "POST", f"/api/drafts/{draft_id}/approve", body={"preview_id": preview["preview_id"]}, expected=(409,))
        assert len(messages) == 1, "Repeat approval must not duplicate delivery"
        run.save("synthetic-openclaw-recorder", {"evidence_class": "synthetic loopback HTTP channel acknowledgement",
                                                "real_email_delivery": False, "messages": messages})
        run.checkpoint("configured_email_explicit_approval_single_transport", synthetic_recorder_requests=1,
                       transport_before_approval=0, real_email_delivery=False)
    finally:
        try:
            configure(False)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
