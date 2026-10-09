#!/usr/bin/env python3
"""Real HTTP acceptance of an installed MyAivan six-service MySQL package.

Run inside the same process/network namespace as the installed services. This
runner uses no fake transport or direct business-state writes. The optional
identity fixture creates only a synthetic buyer login and role. All membership
and workflow changes use normal authenticated HTTP APIs. No external channel
delivery is attempted or claimed. Evidence excludes credentials and tokens.

Example (using the bundled Python interpreter):
  python -B -I verify_installed_business_workflow.py --prefix INSTALL_DIR \
    --package CANDIDATE.run --evidence EVIDENCE_DIR --synthetic-only \
    --allow-test-identity-fixtures --restart

Use -B -I for every bundled-Python diagnostic. The installed inventory deliberately
rejects extra bytecode files as well as changed source and binary files.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from installed_business_fixture import provision_buyer, verify_mysql_and_no_cjk
from installed_email_acceptance import run_email_acceptance


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def packaged_manifest(package: Path) -> bytes:
    """Read one packaged manifest without extracting or executing the archive."""
    with package.open("rb") as stream:
        for _ in range(100):
            if stream.readline() == b"__MYAIVAN_PAYLOAD__\n":
                break
        else:
            raise ValueError("Not a recognized MyAivan package")
        with tarfile.open(fileobj=stream, mode="r|gz") as archive:
            for member in archive:
                if member.name.removeprefix("./") == "manifest.json" and member.isfile():
                    return archive.extractfile(member).read()
    raise ValueError("The candidate package has no manifest")


class Acceptance:
    def __init__(self, args):
        self.args = args
        self.prefix = args.prefix.resolve()
        self.config = json.loads((self.prefix / "config.json").read_text())
        self.release = (self.prefix / "current").resolve()
        if self.release.parent != (self.prefix / "releases").resolve():
            raise ValueError("The selected release is outside this installation")
        if packaged_manifest(args.package) != (self.release / "manifest.json").read_bytes():
            raise ValueError("The provided package differs from the installed candidate")
        verified = subprocess.run([str(self.prefix / "myaivan"), "verify"], capture_output=True, timeout=90)
        if verified.returncode:
            raise ValueError("Installed candidate inventory verification failed")
        self.manifest = json.loads((self.release / "manifest.json").read_text())
        external = self.config.get("external", {})
        mixed = bool(args.mixed_language_source)
        if mixed and (set(external) != {"language"} or urlparse(external["language"]).hostname != "127.0.0.1"):
            raise ValueError("Mixed-source diagnosis requires exactly one loopback language API")
        if (external and not mixed) or any(self.config.get("channels", {}).get(k)
                                           for k in ("email_enabled", "openclaw_url")):
            raise ValueError("This runner requires bundled APIs and disabled external channels")
        if not args.synthetic_only or not args.allow_test_identity_fixtures:
            raise ValueError("Explicit isolated synthetic-data and identity-fixture approval is required")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,24}", args.run_id):
            raise ValueError("Run ID must be 1-24 ASCII identifier characters")
        self.run_id = args.run_id
        self.evidence = args.evidence.resolve()
        if self.evidence.exists() and any(self.evidence.iterdir()):
            raise ValueError("Use a new empty evidence directory; prior failures must be retained")
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.clients = {name: httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60,
                                          follow_redirects=False, trust_env=False)
                        for name, port in self.config["ports"].items()}
        self.tokens = {}
        self.results = {"run_id": self.run_id, "started_at": now(), "status": "running",
                        "evidence_class": ("mixed-source diagnostic: installed application and real source-language API"
                                           if mixed else "real installed-package HTTP and MySQL; synthetic business inputs"),
                        "scenario": {"fabric_material": args.fabric_material, "carrier": args.carrier_label},
                        "package_sha256": file_sha(args.package),
                        "manifest_sha256": sha((self.release / "manifest.json").read_bytes()),
                        "installed_inventory_verified": True, "package_manifest_matches_installation": True,
                        "release": self.manifest["release"], "components": self.manifest["components"],
                        "runner_sha256": sha(Path(__file__).read_bytes()),
                        "fixture_helper_sha256": sha(Path(__file__).with_name("installed_business_fixture.py").read_bytes()),
                        "email_helper_sha256": sha(Path(__file__).with_name("installed_email_acceptance.py").read_bytes()),
                        "external_messages_sent": 0, "checks": [], "milestones": {}, "blockers": []}
        if mixed:
            source = args.mixed_language_source.resolve()
            files = {str(p.relative_to(source)): sha(p.read_bytes()) for p in source.rglob("*")
                     if p.is_file() and p.suffix in {".py", ".yaml", ".yml", ".json"} and "__pycache__" not in p.parts}
            self.results["diagnostic_language_source"] = {"files": files,
                "content_sha256": sha(json.dumps(files, sort_keys=True).encode())}
        self.flush()

    def flush(self):
        (self.evidence / "results.json").write_text(json.dumps(self.results, indent=2, ensure_ascii=True))

    def save(self, name, value):
        (self.evidence / f"{name}.json").write_text(json.dumps(value, indent=2, ensure_ascii=True))

    def headers(self, service, tenant="tenant-a", key=None):
        if service == "database":
            result = {"X-Service-Tenant-ID": tenant, "X-Service-Auth": self.config["secrets"]["database"]}
        elif service == "abcdyi" and tenant in self.tokens:
            result = {"Authorization": "Bearer " + self.tokens[tenant]}
        elif service == "language":
            result = {}
        else:
            result = {"X-AIVAN-Tenant-ID": tenant, "X-AIVAN-API-Key": self.config["tenants"][tenant],
                      "X-AIVAN-Actor-ID": "installation-operator", "X-AIVAN-Role-Context": "admin",
                      "X-AIVAN-Channel-Account-ID": "synthetic-local"}
        result["X-AIVAN-Trace-ID"] = f"acceptance-{self.run_id}"
        if key:
            result["Idempotency-Key"] = f"{self.run_id}-{key}"
        return result

    def request(self, service, method, path, *, tenant="tenant-a", body=None, key=None,
                expected=(200,), headers=None, label=None, capture=True, data=None):
        effective = self.headers(service, tenant, key) if headers is None else headers
        started = time.monotonic()
        response = self.clients[service].request(method, path, json=body, data=data, headers=effective)
        record = {"label": label or f"{method} {path}", "service": service, "method": method,
                  "path": path, "tenant": tenant, "status": response.status_code,
                  "expected_status": list(expected), "duration_seconds": round(time.monotonic() - started, 3),
                  "response_sha256": sha(response.content), "passed": response.status_code in expected}
        self.results["checks"].append(record)
        self.flush()
        if response.status_code not in expected:
            raise AssertionError(f"{service} {method} {path}: HTTP {response.status_code}: {response.text[:2000]}")
        if "json" in response.headers.get("content-type", ""):
            value = response.json()
            if capture:
                self.save(f"response-{len(self.results['checks']):03d}", value)
            return value
        return response

    def checkpoint(self, name, **details):
        self.results["milestones"][name] = {"completed_at": now(), **details}
        self.flush()
        print(f"PASS {name}", flush=True)

    def independent_check(self, name, operation):
        """Continue independent work while retaining a failing overall result."""
        try:
            return operation()
        except Exception as exc:
            self.results["blockers"].append({"check": name, "type": type(exc).__name__, "message": str(exc)})
            self.flush()
            print(f"BLOCKED {name}: {exc}", flush=True)
            return None

    def login(self, tenant):
        login = self.request("abcdyi", "POST", "/api/installation/session", tenant=tenant,
                             headers=self.headers("web", tenant), capture=False)
        self.tokens[tenant] = login["access_token"]
        return login

    def event(self, text, *, role="buyer", message="inquiry", case_id=None):
        actor = self.supplier_id if role == "supplier" else f"{role}-{self.run_id}"
        headers = self.headers("web", key=message)
        headers.update({"X-AIVAN-Participant-ID": actor, "X-AIVAN-Participant-Role": role,
                        "X-AIVAN-Participant-Conversation-Role": f"{role}_thread"})
        body = {"source": "myaivan", "channel": "whatsapp", "conversation_id": f"{role}-{self.run_id}",
                "message_id": f"{message}-{self.run_id}", "sender_id": actor,
                "sender_display_name": f"Synthetic {role}", "message_text": text}
        if case_id:
            body["project_id"] = case_id
        return self.request("web", "POST", "/api/rfq/create-from-event", headers=headers, body=body)

    def auth_checks(self):
        for service, path, header_name in (
            ("web", "/api/workbench/cases", "X-AIVAN-API-Key"),
            ("database", "/api/data/suppliers", "X-Service-Auth"),
            ("gpm", "/api/gpm/packets", "X-AIVAN-API-Key"),
            ("abcdyi", "/api/installation/session", "X-AIVAN-API-Key"),
        ):
            method = "POST" if service == "abcdyi" else "GET"
            for value in (None, "invalid-synthetic-credential", b"\xff\xfe"):
                headers = self.headers("web" if service == "abcdyi" else service)
                headers.pop(header_name, None)
                if value is not None:
                    headers[header_name] = value
                self.request(service, method, path, headers=headers, expected=(400, 401, 403),
                             label=f"{service} rejects missing/wrong/non-ASCII credential")
        crossed = self.headers("web", "tenant-b")
        crossed["X-AIVAN-API-Key"] = self.config["tenants"]["tenant-a"]
        self.request("web", "GET", "/api/workbench/cases", headers=crossed, expected=(403,))
        self.checkpoint("malformed_credentials_fail_closed")

    def workflow(self):
        self.auth_checks()
        blocked_translation = self.request("language", "POST", "/v1/outbound/render", body={
            "target_language": "zh", "target_channel": "whatsapp", "message_type": "commercial_draft",
            "canonical_text": "The unit price is USD 10 and the total price is USD 12000. Human review is required.",
        }, expected=(503,), label="Ambiguous multi-fact commercial translation fails closed")
        assert blocked_translation["detail"]["error"] == "TRANSLATION_FIDELITY_UNVERIFIED"
        assert blocked_translation["detail"]["action"] == "pending_translation"
        assert "rendered_text" not in blocked_translation
        self.checkpoint("unsupported_commercial_translation_fails_closed",
                        response_code="TRANSLATION_FIDELITY_UNVERIFIED", rendered_body_returned=False)
        for tenant in ("tenant-a", "tenant-b"):
            self.login(tenant)
        buyer = provision_buyer(self.prefix, self.release, "tenant-a", self.run_id)
        self.buyer = buyer
        self.results["identity_fixture"] = {k: v for k, v in buyer.items() if k != "password"}
        self.checkpoint("explicit_synthetic_identity_fixture")
        supplier = {"supplier_name": "Synthetic Cotton Apparel Factory",
                    "name_en": "Synthetic Cotton Apparel Factory", "company_type": "factory", "country": "CN",
                    "categories_json": ["apparel"],
                    "capabilities_json": ["shirts", "The factory can manufacture cotton shirts and package them for export."],
                    "materials_json": ["cotton"], "languages_json": ["en", "zh"], "channels_json": ["email"],
                    "email": "synthetic-supplier@example.invalid", "incoterms_json": ["FOB"],
                    "quality_score": 0.9, "past_performance_score": 0.9, "active": True, "is_synthetic": True,
                    "source_type": "manual_upload", "source_record_id": self.run_id,
                    "notes": "Synthetic acceptance supplier, not a real business or offer.",
                    "metadata_json": {"moq_min": 100, "daily_capacity": 500, "monthly_capacity": 15000,
                                      "synthetic_fixture": True}}
        stored = self.request("database", "POST", "/api/data/suppliers", body=supplier)
        supplier["supplier_id"] = stored["supplier_id"]
        self.supplier_id = stored["supplier_id"]
        self.request("database", "GET", f"/api/data/suppliers/{supplier['supplier_id']}", tenant="tenant-b", expected=(404,))
        other_supplier = {**supplier, "supplier_name": "Synthetic Tenant B Factory"}
        other_supplier.pop("supplier_id")
        other_stored = self.request("database", "POST", "/api/data/suppliers", body=other_supplier, tenant="tenant-b")
        other_supplier["supplier_id"] = other_stored["supplier_id"]
        self.request("database", "GET", f"/api/data/suppliers/{other_supplier['supplier_id']}", expected=(404,))
        for tenant, own_id, foreign_id in (("tenant-a", supplier["supplier_id"], other_supplier["supplier_id"]),
                                           ("tenant-b", other_supplier["supplier_id"], supplier["supplier_id"])):
            rows = self.request("database", "GET", "/api/data/suppliers", tenant=tenant)["items"]
            identifiers = {row["supplier_id"] for row in rows}
            assert own_id in identifiers and foreign_id not in identifiers
        self.checkpoint("bidirectional_two_tenant_provider_isolation")

        # This new Chinese input is sent to the real installed language service
        # through Aivan. Human clarification supplies explicitly stated facts.
        inquiry = "\u6211\u4eec\u9700\u89811200\u4ef6\u767d\u8272\u68c9\u8d28\u886c\u886b\uff0c\u8bf7\u62a5\u4ef7\u3002"
        created = self.event(inquiry)
        assert created.get("status") == "ok", created
        self.case_id = created["project_id"]
        assert self.case_id
        replay = self.event(inquiry)
        assert replay["project_id"] == self.case_id
        before = self.request("web", "GET", f"/api/workbench/cases/{self.case_id}/requirement")
        assert not re.search("[\u3400-\u9fff]", json.dumps(before, ensure_ascii=False)), before
        assert before["requirement"]["missing_fields"], "The deliberately incomplete input must need clarification"
        self.checkpoint("chinese_intake_and_idempotent_replay", case_id=self.case_id,
                        original_source_sha256=sha(inquiry.encode()), canonical_requirement=before["requirement"])
        fields = {"category": "apparel", "product_type": "cotton shirt", "quantity": 1200,
                  "fabric_material": self.args.fabric_material, "gsm": 180, "color": "white",
                  "size_ratio": "S/M/L/XL 300/300/300/300", "packaging": "Individually bagged",
                  "destination": "Vancouver", "delivery_days": 60, "incoterms": "FOB"}
        clarification = {"expected_requirement_sha256": before["requirement_sha256"], "fields": fields}
        clarified = self.request("web", "PATCH", f"/api/workbench/cases/{self.case_id}/requirement",
                                  body=clarification, key="clarification")
        assert clarified["provider_graph"]["readback_verified"] is True
        repeated = self.request("web", "PATCH", f"/api/workbench/cases/{self.case_id}/requirement",
                                body=clarification, key="clarification")
        assert repeated["replayed"] is True
        self.request("web", "PATCH", f"/api/workbench/cases/{self.case_id}/requirement",
                     body={**clarification, "fields": {"quantity": 1800}}, key="clarification", expected=(409,))
        self.graph_id = clarified["provider_graph"]["procurement_case_id"]
        self.request("database", "GET", f"/api/data/procurement-cases/{self.graph_id}/transaction-graph")
        self.request("web", "GET", f"/api/workbench/cases/{self.case_id}", tenant="tenant-b", expected=(404,))
        self.checkpoint("human_clarification_and_provider_readback")
        self.independent_check("file_and_image_upload", self.attachments)

        reply_text = "We quote unit price USD 8.50; MOQ 100 pcs; production lead time 30 days. These are synthetic acceptance quotation facts."
        replied = self.event(reply_text, role="supplier", message="reply", case_id=self.case_id)
        assert replied.get("action") == "buyer_options_ready", replied
        detail = self.request("web", "GET", f"/api/workbench/cases/{self.case_id}")
        self.option_id = detail["case"]["selected_option"]["option_id"]
        options = detail["case"]["requirement"]["buyer_options"]
        assert options and options[0]["supplier_id"] == supplier["supplier_id"]
        assert detail["case"]["requirement"]["gpm_guidance"]["packet_id"]
        self.gpm_id = detail["case"]["requirement"]["gpm_guidance"]["packet_id"]
        denied = self.request("gpm", "GET", f"/api/gpm/quote-guidance/{self.gpm_id}", tenant="tenant-b", expected=(403, 404))
        assert "packet_id" not in denied and "recommendation" not in denied
        self.request("web", "POST", f"/api/workbench/cases/{self.case_id}/order-confirmation",
                     body={"selected_option_id": self.option_id}, key="premature-po", expected=(409,))
        draft = next(d for d in detail["drafts"] if d["draft_id"] in replied["drafts_created"])
        self.draft_id = draft["draft_id"]
        preview = self.request("web", "POST", f"/api/drafts/{self.draft_id}/preview",
                               body={"target_language": "zh", "manual_delivery": True})
        assert re.search("[\u3400-\u9fff]", preview["message_text"]), preview
        complete_draft = self.request("web", "GET", f"/api/drafts/{self.draft_id}")
        fingerprint = {name: complete_draft[name] for name in (
            "draft_id", "tenant_id", "project_id", "conversation_id", "channel", "channel_account_id",
            "target_peer_id", "target_role", "message_text", "message_type")}
        fingerprint.update(attachments_json=complete_draft["attachments"], subject="", target_language="zh",
                           sender=preview["sender"], manual_delivery=True)
        assert preview["source_sha256"] == sha(json.dumps(fingerprint, ensure_ascii=True,
                                                           sort_keys=True, separators=(",", ":")).encode())
        assert preview["rendered_sha256"] == sha(preview["message_text"].encode())
        self.save("commercial-preview-review", {
            "review_status": "requires semantic review; hashes prove binding only",
            "canonical_draft": complete_draft["message_text"],
            "rendered_draft": preview["message_text"], "target_language": "zh",
            "selected_option": detail["case"]["selected_option"],
            "requirement_quantity": detail["case"]["requirement"].get("quantity"),
            "preview_id": preview["preview_id"], "source_sha256": preview["source_sha256"],
            "rendered_sha256": preview["rendered_sha256"],
        })
        self.request("web", "POST", f"/api/workbench/cases/{self.case_id}/drafts/{self.draft_id}/copy",
                     key="copy", body={"content_sha256": preview["rendered_sha256"], "preview_id": preview["preview_id"]})
        approved = self.request("web", "POST", f"/api/drafts/{self.draft_id}/approve",
                                body={"preview_id": preview["preview_id"]})
        assert approved["sent"] is False and approved["relay_required"] is True, approved
        self.checkpoint("supplier_reply_quote_preview_and_human_approval", draft_id=self.draft_id,
                        option_id=self.option_id, gpm_packet_id=self.gpm_id, delivery_claim=False)
        self.po = self.request("web", "POST", f"/api/workbench/cases/{self.case_id}/order-confirmation",
                                body={"selected_option_id": self.option_id}, key="confirm-po")
        assert self.po["status"] == "confirmed" and self.po["readback_verified"] is True
        replay = self.request("web", "POST", f"/api/workbench/cases/{self.case_id}/order-confirmation",
                               body={"selected_option_id": self.option_id}, key="confirm-po")
        assert replay["recovered"] is True and replay["purchase_order_id"] == self.po["purchase_order_id"]
        self.request("database", "GET", f"/api/data/purchase-orders/{self.po['purchase_order_id']}")
        self.request("database", "GET", f"/api/data/purchase-orders/{self.po['purchase_order_id']}",
                     tenant="tenant-b", expected=(404,))
        self.checkpoint("human_confirmed_order_durable_readback", purchase_order_id=self.po["purchase_order_id"])
        self.fulfillment()
        self.scan_database()
        if self.args.restart:
            self.restart_and_recover()
        else:
            self.results["restart_recovery"] = "not_run"
        if self.args.email_recorder:
            run_email_acceptance(self)
            self.scan_database()
        else:
            self.results["configured_email_transport"] = "not_run"

    def attachments(self):
        fixtures = [("brief.txt", "text/plain", b"Synthetic cotton shirt specification. White cotton shirts with individually bagged packaging."),
                    ("translated-brief.txt", "text/plain", "\u6211\u4eec\u9700\u89811200\u4ef6\u767d\u8272\u68c9\u8d28\u886c\u886b\uff0c\u8bf7\u62a5\u4ef7\u3002".encode("utf-8")),
                    ("reference.png", "image/png", base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAGUlEQVR4nGNQTtnynxLMMGrAqAGjBgwXAwClzDofGBUA5AAAAABJRU5ErkJggg=="))]
        self.attachment_ids = []
        for name, media, content in fixtures:
            body = {"file_name": name, "content_type": media, "content_base64": base64.b64encode(content).decode(), "sha256": sha(content)}
            saved = self.request("web", "POST", f"/api/workbench/cases/{self.case_id}/attachments", body=body, key=name)
            assert saved["readback_verified"] is True
            assert saved["source_sha256"] == sha(content)
            assert saved["source_name_sha256"] == sha(name.encode())
            assert saved["file_name"] == f"attachment-{saved['sha256'][:12]}.{'png' if media.startswith('image') else 'txt'}"
            if media.startswith("image"):
                assert saved["processing_status"] == "stored_image_not_parsed"
                assert saved["sha256"] == sha(content)
            else:
                assert saved["canonical_language"] == "en" and saved["canonical_text"].strip()
                assert not re.search("[\u3400-\u9fff]", saved["canonical_text"])
                assert saved["sha256"] == sha(saved["canonical_text"].encode())
            repeated = self.request("web", "POST", f"/api/workbench/cases/{self.case_id}/attachments", body=body, key=name)
            assert repeated["attachment_id"] == saved["attachment_id"]
            downloaded = self.request("web", "GET", saved["download_path"])
            assert sha(downloaded.content) == saved["sha256"]
            self.request("web", "GET", saved["download_path"], tenant="tenant-b", expected=(404,))
            self.attachment_ids.append(saved["attachment_id"])
        self.checkpoint("file_and_image_upload_replay_readback", image_analysis="not_available_truthfully_reported")

    def fulfillment(self):
        body = {"purchase_order_id": self.po["purchase_order_id"]}
        order = self.request("abcdyi", "POST", "/api/orders/from-provider-confirmed", body=body)
        assert order["status"] == "IN_PRODUCTION"
        self.order_id = order["id"]
        self.execution_project_id = order["project_id"]
        repeated = self.request("abcdyi", "POST", "/api/orders/from-provider-confirmed", body=body)
        assert repeated["id"] == self.order_id
        self.request("abcdyi", "GET", f"/api/orders/{self.order_id}", tenant="tenant-b", expected=(404,))
        self.request("abcdyi", "POST", "/api/orders/from-provider-confirmed", body=body, tenant="tenant-b", expected=(404, 409))
        self.request("abcdyi", "POST", f"/api/projects/{order['project_id']}/memberships",
                     body={"user_id": self.buyer["id"], "role": "BUYER"})
        login = self.request("abcdyi", "POST", "/api/auth/login", headers={}, capture=False,
                             data={"username": self.buyer["email"], "password": self.buyer["password"]})
        self.buyer_headers = {"Authorization": "Bearer " + login["access_token"]}
        self.request("abcdyi", "POST", f"/api/orders/{self.order_id}/buyer-sign-off", headers=self.buyer_headers, expected=(409,))
        monitoring = self.request("abcdyi", "GET", f"/api/orders/{self.order_id}/production-monitoring")
        required = {"FABRIC_BOOKING", "TRIM_BOOKING", "CUTTING", "SEWING", "PACKING"}
        assert required <= {m["milestone_type"] for m in monitoring["milestones"]}
        for milestone in monitoring["milestones"]:
            if milestone["milestone_type"] in required:
                self.request("abcdyi", "PATCH", f"/api/milestones/{milestone['id']}", body={"status": "COMPLETED",
                             "actual_date": now(), "notes": "Synthetic operator observed completed apparel work."})
        self.request("abcdyi", "POST", f"/api/orders/{self.order_id}/request-qc")
        failed = self.request("abcdyi", "POST", f"/api/orders/{self.order_id}/qc-records",
                              body={"label_compliance": False, "packaging_compliance": True}, expected=(201,))
        assert failed["result"] == "QC_FAILED"
        self.request("abcdyi", "POST", f"/api/orders/{self.order_id}/shipments", body={"carrier": self.args.carrier_label}, expected=(409,))
        self.request("abcdyi", "POST", f"/api/qc-records/{failed['id']}/resolve",
                     body={"reason": "Replace incorrect labels and reinspect the entire synthetic batch."})
        self.request("abcdyi", "POST", f"/api/orders/{self.order_id}/request-qc")
        passed = self.request("abcdyi", "POST", f"/api/orders/{self.order_id}/qc-records",
                              body={"label_compliance": True, "packaging_compliance": True}, expected=(201,))
        assert passed["result"] == "QC_PASSED"
        self.checkpoint("production_failed_qc_rework_reinspection", order_id=self.order_id)
        shipment = self.request("abcdyi", "POST", f"/api/orders/{self.order_id}/shipments", expected=(201,),
                                body={"carrier": self.args.carrier_label, "tracking_number": f"TEST-{self.run_id}",
                                      "origin": "Shenzhen", "destination": "Vancouver", "trade_term": "FOB"})
        self.request("abcdyi", "POST", f"/api/shipments/{shipment['id']}/tracking-events", expected=(201,),
                     body={"event_type": "DELIVERED", "description": "Synthetic carrier reports delivery; buyer review is pending.", "occurred_at": now()})
        delivered = self.request("abcdyi", "GET", f"/api/orders/{self.order_id}")
        assert delivered["status"] == "DELIVERED" and delivered["buyer_signed_off_at"] is None
        self.checkpoint("delivery_separate_from_buyer_acceptance")
        signed = self.request("abcdyi", "POST", f"/api/orders/{self.order_id}/buyer-sign-off", headers=self.buyer_headers)
        assert signed["status"] == "BUYER_SIGNED_OFF" and signed["buyer_signed_off_at"]
        self.signed_at = signed["buyer_signed_off_at"]
        self.request("abcdyi", "POST", f"/api/orders/{self.order_id}/buyer-sign-off", headers=self.buyer_headers)
        events = self.request("abcdyi", "GET", f"/api/execution-graph/orders/{self.order_id}")
        types = {e["event_type"] for e in events}
        assert {"QC_FAILURE_RESOLVED", "QC_PASSED", "BUYER_SIGNED_OFF", "SHIPMENT_UPDATED"} <= types, types
        self.provider_state = self.request("database", "GET", f"/api/data/purchase-orders/{self.po['purchase_order_id']}/execution-state")
        self.save("authoritative-provider-lifecycle", self.provider_state)
        lifecycle = self.provider_state["state"]["projection"]["lifecycle"]
        assert lifecycle["order"]["status"] == "BUYER_SIGNED_OFF"
        assert len(lifecycle["records"]["qc_records"]) == 2
        assert len(lifecycle["records"]["supplier_memory_records"]) == 1
        self.checkpoint("separate_buyer_signoff_and_supplier_memory", buyer_actor_id=self.buyer["id"],
                        operator_actor_id=self.config["fulfillment"]["tenants"]["tenant-a"]["operator_id"],
                        provider_revision=self.provider_state["revision"])
        def export_case():
            export = self.request("web", "GET", f"/api/workbench/cases/{self.case_id}/export")
            (self.evidence / "case-export.md").write_bytes(export.content)
            assert self.draft_id.encode() in export.content
            self.checkpoint("case_markdown_export")
        self.independent_check("case_markdown_export", export_case)

    def scan_database(self):
        scan = verify_mysql_and_no_cjk(self.prefix)
        self.save("mysql-durability-and-language-scan", scan)
        assert not any(v["cjk_violations"] for v in scan.values()), scan
        self.checkpoint("three_mysql_schemas_no_chinese_business_text", schemas=len(scan))

    def restart_and_recover(self):
        for client in self.clients.values():
            client.close()
        completed = subprocess.run([str(self.prefix / "myaivan"), "restart"], capture_output=True, timeout=180)
        self.results["restart"] = {"exit_code": completed.returncode, "stdout_sha256": sha(completed.stdout),
                                   "stderr_sha256": sha(completed.stderr)}
        self.flush()
        if completed.returncode:
            raise AssertionError("Installed service restart failed; inspect private installation logs")
        self.clients = {name: httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60,
                                          follow_redirects=False, trust_env=False)
                        for name, port in self.config["ports"].items()}
        self.tokens = {}
        self.login("tenant-a")
        case = self.request("web", "GET", f"/api/workbench/cases/{self.case_id}")
        assert case["case"]["status"] == "order_confirmed"
        recovered = self.request("web", "GET", f"/api/workbench/cases/{self.case_id}/order-confirmation")
        assert recovered["purchase_order_id"] == self.po["purchase_order_id"]
        order = self.request("abcdyi", "POST", "/api/orders/from-provider-confirmed",
                             body={"purchase_order_id": self.po["purchase_order_id"]})
        assert order["id"] == self.order_id and order["status"] == "BUYER_SIGNED_OFF"
        assert order["buyer_signed_off_at"] == self.signed_at
        state = self.request("database", "GET", f"/api/data/purchase-orders/{self.po['purchase_order_id']}/execution-state")
        assert state == self.provider_state
        self.request("gpm", "GET", f"/api/gpm/quote-guidance/{self.gpm_id}")
        if self.attachment_ids:
            attachments = self.request("web", "GET", f"/api/workbench/cases/{self.case_id}/attachments")
            assert set(self.attachment_ids) <= {item["attachment_id"] for item in attachments["items"]}
        self.checkpoint("managed_service_restart_and_db_recovery_without_chat_state",
                        managed_services=len(self.config["ports"]) - len(self.config.get("external", {})))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("run%H%M%S"))
    parser.add_argument("--fabric-material", default="100% cotton")
    parser.add_argument("--carrier-label", default="The synthetic logistics company for this acceptance test")
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--allow-test-identity-fixtures", action="store_true")
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--email-recorder", action="store_true")
    parser.add_argument("--mixed-language-source", type=Path)
    args = parser.parse_args()
    run = Acceptance(args)
    try:
        run.workflow()
        if run.results["blockers"]:
            raise AssertionError("Independent checks failed; see retained blockers and HTTP evidence")
        run.results["status"] = "diagnostic_passed" if args.mixed_language_source else "passed"
        return_code = 0
    except Exception as exc:
        run.results["status"] = "failed"
        run.results["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        print(f"FAIL {type(exc).__name__}: {exc}", flush=True)
        return_code = 1
    finally:
        run.results["finished_at"] = now()
        run.flush()
        for client in run.clients.values():
            client.close()
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
