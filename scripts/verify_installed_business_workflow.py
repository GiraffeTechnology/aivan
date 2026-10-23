#!/usr/bin/env python3
"""Real HTTP acceptance of an installed MyAivan six-service MySQL package.

Run inside the same process/network namespace as the installed services. This
runner uses no fake transport or direct business-state writes. The optional
identity fixture creates only a synthetic buyer login and role. All membership
and workflow changes use normal authenticated HTTP APIs. No external channel
delivery is attempted or claimed. Evidence excludes credentials and tokens.

The default full mode retains industry lifecycle checks. Explicitly select
--scope aivan-bounded for inquiry through order confirmation without those writes.

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
import importlib.util
import json
import re
import subprocess
import sys
import tarfile
import time
import traceback
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from installed_business_fixture import provision_buyer, verify_mysql_and_no_cjk
from installed_email_acceptance import run_email_acceptance


def validate_bounded_options(args, config):
    """Validate this synthetic runner profile, not a new product release gate."""
    if not args.synthetic_only or not args.restart:
        raise ValueError("Bounded acceptance requires explicit --synthetic-only and --restart")
    primary, secondary = args.tenant, args.other_tenant
    tenants = config.get("tenants", {})
    if not primary or not secondary or primary == secondary or any(
            name not in tenants or not tenants[name] for name in (primary, secondary)):
        raise ValueError("Select two distinct existing synthetic tenants from the installation")
    if config.get("database_mode") != "external":
        raise ValueError("This target acceptance profile requires configured MySQL, not SQLite")
    if set(config.get("external", {})) - {"language"}:
        raise ValueError("This runner profile uses bundled DB/GLTG/GPM APIs; other profiles are not tested")
    if args.mixed_language_source or args.email_recorder:
        raise ValueError("Mixed-source diagnosis and email-recorder testing remain separate full-mode options")
    if any(config.get("channels", {}).get(name) for name in ("email_enabled", "openclaw_url")):
        raise ValueError("Bounded synthetic acceptance requires disabled external business channels")
    return primary, secondary


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
    bounded_scope = False
    primary_tenant = "tenant-a"
    secondary_tenant = "tenant-b"

    def __init__(self, args):
        self.args = args
        self.prefix = args.prefix.resolve()
        self.config = json.loads((self.prefix / "config.json").read_text())
        if self.bounded_scope:
            self.primary_tenant, self.secondary_tenant = validate_bounded_options(args, self.config)
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
        if (external and not mixed and not self.bounded_scope) or any(self.config.get("channels", {}).get(k)
                                           for k in ("email_enabled", "openclaw_url")):
            raise ValueError("This runner requires bundled APIs and disabled external channels")
        if not args.synthetic_only or (not self.bounded_scope and not args.allow_test_identity_fixtures):
            raise ValueError("Explicit isolated synthetic-data and identity-fixture approval is required")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,24}", args.run_id):
            raise ValueError("Run ID must be 1-24 ASCII identifier characters")
        self.run_id = args.run_id
        self.evidence = args.evidence.resolve()
        if self.evidence.exists() and any(self.evidence.iterdir()):
            raise ValueError("Use a new empty evidence directory; prior failures must be retained")
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.clients = {name: httpx.Client(base_url=(external.get(name) if self.bounded_scope and name == "language"
                                                   and external.get(name) else f"http://127.0.0.1:{port}"), timeout=60,
                                          follow_redirects=False, trust_env=False)
                        for name, port in self.config["ports"].items()
                        if not self.bounded_scope or name != "abcdyi"}
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
        if self.bounded_scope:
            self.results.update(scope="aivan-bounded", evidence_class="Real installed Aivan HTTP/MySQL; synthetic inputs; not browser or industry execution acceptance",
                                industry_execution="not_run", identity_fixture="not_run", ui_browser="not_run",
                                external_messages_sent=None,
                                external_delivery_evidence="Not measured; configured business channels are disabled")
            self.results["components"] = {name: {key: item[key] for key in (
                "revision", "upstream_tree", "modified", "selected_source_candidate") if key in item}
                for name, item in self.manifest["components"].items() if name != "abcdyi"}
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

    def headers(self, service, tenant=None, key=None):
        tenant = self.primary_tenant if tenant is None else tenant
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

    def request(self, service, method, path, *, tenant=None, body=None, key=None,
                expected=(200,), headers=None, label=None, capture=True, data=None):
        tenant = self.primary_tenant if tenant is None else tenant
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
            if self.bounded_scope:
                raise AssertionError(f"{service} {method} {path}: HTTP {response.status_code}; response digest retained")
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
        if not self.bounded_scope:
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
        self.request("database", "GET", f"/api/data/suppliers/{supplier['supplier_id']}", tenant=self.secondary_tenant, expected=(404,))
        other_supplier = {**supplier, "supplier_name": "Synthetic Tenant B Factory"}
        other_supplier.pop("supplier_id")
        other_stored = self.request("database", "POST", "/api/data/suppliers", body=other_supplier, tenant=self.secondary_tenant)
        other_supplier["supplier_id"] = other_stored["supplier_id"]
        self.request("database", "GET", f"/api/data/suppliers/{other_supplier['supplier_id']}", expected=(404,))
        for tenant, own_id, foreign_id in ((self.primary_tenant, supplier["supplier_id"], other_supplier["supplier_id"]),
                                           (self.secondary_tenant, other_supplier["supplier_id"], supplier["supplier_id"])):
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
        self.request("web", "GET", f"/api/workbench/cases/{self.case_id}", tenant=self.secondary_tenant, expected=(404,))
        self.checkpoint("human_clarification_and_provider_readback")
        if self.bounded_scope:
            self.inquiry_drafts()
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
        denied = self.request("gpm", "GET", f"/api/gpm/quote-guidance/{self.gpm_id}", tenant=self.secondary_tenant, expected=(403, 404))
        assert "packet_id" not in denied and "recommendation" not in denied
        self.request("web", "POST", f"/api/workbench/cases/{self.case_id}/order-confirmation",
                     body={"selected_option_id": self.option_id}, key="premature-po", expected=(409,))
        draft = next(d for d in detail["drafts"] if d["draft_id"] in replied["drafts_created"])
        self.draft_id = draft["draft_id"]
        if self.bounded_scope:
            detail, draft = self.reject_revise_regenerate(detail, draft)
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
                     tenant=self.secondary_tenant, expected=(404,))
        self.checkpoint("human_confirmed_order_durable_readback", purchase_order_id=self.po["purchase_order_id"])
        if self.bounded_scope:
            self.bounded_readback()
        else:
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
            self.request("web", "GET", saved["download_path"], tenant=self.secondary_tenant, expected=(404,))
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


class BoundedAcceptance(Acceptance):
    """The same real Aivan flow, without industry lifecycle or buyer writes."""

    bounded_scope = True

    def workflow(self):
        self.scan_database()  # Metadata-only verification before any business write.
        super().workflow()

    def request(self, service, method, path, **kwargs):
        if service not in {"web", "database", "gltg", "gpm", "language"}:
            raise ValueError("Service is outside the selected Aivan acceptance scope")
        try:
            return super().request(service, method, path, **kwargs)
        except httpx.HTTPError as exc:
            self.results["checks"].append({"service": service, "method": method, "path": path,
                                           "tenant": kwargs.get("tenant") or self.primary_tenant,
                                           "error_type": type(exc).__name__, "passed": False})
            self.flush()
            raise AssertionError(f"{service} {method} {path}: {type(exc).__name__}; inspect private service logs") from None

    def save(self, name, value):
        def redact(item):
            if isinstance(item, dict):
                return {key: ("[REDACTED]" if key.lower() in {
                    "password", "api_key", "access_token", "refresh_token", "authorization",
                    "cookie", "set-cookie", "secret", "secrets", "database_url"} else redact(child))
                    for key, child in item.items()}
            if isinstance(item, list):
                return [redact(child) for child in item]
            return item
        super().save(name, redact(value))

    def independent_check(self, name, operation):
        try:
            return operation()
        except Exception as exc:
            self.results["blockers"].append({"check": name, **bounded_failure(exc)})
            self.flush()
            print(f"BLOCKED {name}: {type(exc).__name__}; see sanitized check evidence", flush=True)
            return None

    def auth_checks(self):
        for service, path, header_name in (
            ("web", "/api/workbench/cases", "X-AIVAN-API-Key"),
            ("database", "/api/data/suppliers", "X-Service-Auth"),
            ("gpm", "/api/gpm/packets", "X-AIVAN-API-Key"),
        ):
            for value in (None, "invalid-synthetic-credential", b"\xff\xfe"):
                headers = self.headers(service)
                headers.pop(header_name, None)
                if value is not None:
                    headers[header_name] = value
                self.request(service, "GET", path, headers=headers, expected=(400, 401, 403),
                             label=f"{service} rejects missing/wrong/non-ASCII credential")
        crossed = self.headers("web", self.secondary_tenant)
        crossed["X-AIVAN-API-Key"] = self.config["tenants"][self.primary_tenant]
        self.request("web", "GET", "/api/workbench/cases", tenant=self.secondary_tenant, headers=crossed, expected=(403,))
        self.checkpoint("malformed_credentials_fail_closed")

    def scan_database(self):
        """Probe selected SQL identities, not another service's business tables."""
        from sqlalchemy import create_engine, text
        path = self.release / "database_config.py"
        if file_sha(path) != self.manifest["files"].get("database_config.py"):
            raise ValueError("Installed SQL configuration helper differs from the selected package")
        spec = importlib.util.spec_from_file_location("bounded_verified_database_config", path)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        targets = helper.configured_targets(self.config, self.prefix)
        observed = {}
        for name in ("aivan", "database"):
            target = targets[name]
            if target["engine"] != "mysql":
                raise ValueError("This target acceptance profile requires actual MySQL")
            engine = None
            try:
                engine = create_engine(helper.sync_url(target["url"]))
                with engine.connect() as connection:
                    version, mode = connection.execute(text("SELECT VERSION(), @@sql_mode")).one()
                    helper.verify_namespace(engine, target["schema"])
                    assert {"STRICT_TRANS_TABLES", "STRICT_ALL_TABLES"} & set(mode.split(",")), "Strict MySQL mode is required"
                observed[name] = {"engine": "mysql", "version": version,
                                  "target_sha256": target["target_sha256"], "metadata_only": True}
            except Exception as exc:
                raise AssertionError(f"{name} MySQL metadata verification failed ({type(exc).__name__}); inspect private configuration") from None
            finally:
                if engine is not None:
                    engine.dispose()
        self.results["mysql_identity"] = observed
        self.save("selected-mysql-identities", observed)
        self.checkpoint("selected_mysql_identities_verified", components=list(observed))

    def revise(self, text, message):
        detail = self.request("web", "GET", f"/api/workbench/cases/{self.case_id}")
        buyer = detail["case"]["customer_id"]
        conversation = next((entry["external_conversation_id"] for entry in detail["conversations"]
                             if entry["role"] == "buyer_thread" and entry["channel"] == "myaivan"), f"revision-{self.run_id}")
        headers = self.headers("web", key=message)
        headers.update({"X-AIVAN-Participant-ID": buyer, "X-AIVAN-Participant-Role": "buyer",
                        "X-AIVAN-Participant-Conversation-Role": "buyer_thread"})
        body = {"source": "myaivan", "channel": "myaivan", "project_id": self.case_id,
                "conversation_id": conversation, "message_id": f"{message}-{self.run_id}",
                "sender_id": buyer, "sender_display_name": "Synthetic buyer", "message_text": text}
        result = self.request("web", "POST", "/invoke", headers=headers, body=body)
        assert result.get("status") == "ok" and result["project_id"] == self.case_id
        return result

    def inquiry_drafts(self):
        result = self.revise("Use the confirmed requirement to prepare supplier inquiries. Do not send any message.", "supplier-inquiry")
        assert result["action"] == "pending_email_approval" and result["drafts_created"]
        detail = self.request("web", "GET", f"/api/workbench/cases/{self.case_id}")
        drafts = [item for item in detail["drafts"] if item["target_role"] == "supplier"
                  and item["draft_id"] in result["drafts_created"]]
        assert drafts and all(item["status"] == "pending_approval" and item["delivered_at"] is None for item in drafts)
        self.checkpoint("supplier_inquiry_drafts_pending_human_review", draft_ids=[item["draft_id"] for item in drafts])

    def reject_revise_regenerate(self, detail, draft):
        self.rejected_draft_id = draft["draft_id"]
        rejected = self.request("web", "POST", f"/api/drafts/{self.rejected_draft_id}/reject")
        assert rejected["status"] == "rejected"
        after = self.request("web", "GET", f"/api/workbench/cases/{self.case_id}")
        assert after["case"]["case_state"] == "supplier_replied" and after["case"]["selected_option"] is None
        assert after["receipts"] == detail["receipts"]
        self.request("web", "POST", f"/api/drafts/{self.rejected_draft_id}/approve", body={}, expected=(409,))
        self.request("web", "POST", f"/api/workbench/cases/{self.case_id}/order-confirmation",
                     body={"selected_option_id": self.option_id}, key="rejected-order", expected=(409,))
        revised = self.revise("Keep the confirmed quantity and material. Revise packaging to individually bagged shirts in export cartons. Regenerate drafts for review; do not send.", "buyer-revision")
        assert revised["action"] == "pending_email_approval" and revised["drafts_created"]
        reply = self.event("We quote unit price USD 8.75; MOQ 100 pcs; production lead time 30.5 days. Individually bagged in export cartons. These are synthetic revised quotation facts.",
                           role="supplier", message="revised-reply", case_id=self.case_id)
        assert reply["action"] == "buyer_options_ready" and reply["drafts_created"]
        updated = self.request("web", "GET", f"/api/workbench/cases/{self.case_id}")
        replacement = next(item for item in updated["drafts"] if item["draft_id"] in reply["drafts_created"])
        assert replacement["draft_id"] != self.rejected_draft_id and replacement["status"] == "pending_approval"
        original = next(item for item in updated["drafts"] if item["draft_id"] == self.rejected_draft_id)
        assert original["status"] == "rejected" and original["delivered_at"] is None
        assert updated["receipts"] == detail["receipts"]
        selected = updated["case"]["selected_option"]
        assert selected["supplier_id"] == self.supplier_id and selected["quote"]["currency"] == "USD"
        assert Decimal(str(selected["quote"]["unit_price"])) == Decimal("8.75")
        lead = selected["lead_time_estimate"]
        assert Decimal(str(lead["declared_lead_time_days"])) == Decimal("30.5")
        quantiles = [Decimal(str(lead[field])) for field in ("p50_days", "p80_days", "p90_days")]
        assert all(value.is_finite() for value in quantiles) and Decimal(0) <= quantiles[0] <= quantiles[1] <= quantiles[2]
        self.selected_snapshot = json.loads(json.dumps(selected))
        self.option_id = selected["option_id"]
        self.gpm_id = updated["case"]["requirement"]["gpm_guidance"]["packet_id"]
        self.draft_id = replacement["draft_id"]
        self.checkpoint("rejected_quote_revision_and_fresh_review", rejected_draft_id=self.rejected_draft_id,
                        replacement_draft_id=self.draft_id, actual_option_id=self.option_id)
        return updated, replacement

    def bounded_readback(self):
        detail = self.request("web", "GET", f"/api/workbench/cases/{self.case_id}")
        assert detail["case"]["status"] == "order_confirmed"
        assert detail["case"]["selected_option"] == self.selected_snapshot
        events = {item["event_type"] for item in detail["audit"]}
        assert {"DRAFT_REJECTED", "REQUIREMENT_CLARIFIED", "DRAFT_APPROVED", "ORDER_CONFIRMED"} <= events
        selected = {key: detail[key] for key in ("case", "messages", "drafts", "audit")}
        assert not re.search("[\u3400-\u9fff]", json.dumps(selected, ensure_ascii=False))
        export = self.request("web", "GET", f"/api/workbench/cases/{self.case_id}/export")
        assert self.draft_id.encode() in export.content and self.rejected_draft_id.encode() in export.content
        (self.evidence / "case-export.md").write_bytes(export.content)
        self.guidance_snapshot = self.guidance_readback()
        self.rejected_readback(detail)
        self.results["external_messages_sent"] = None
        self.results["external_delivery_evidence"] = "Not measured; external channels disabled and manual approval returned sent=false"
        self.checkpoint("bounded_audit_export_and_selected_english_readback", industry_execution="not_run")

    def guidance_readback(self):
        guidance = self.request("gpm", "GET", f"/api/gpm/quote-guidance/{self.gpm_id}")
        assert isinstance(guidance, dict)
        assert guidance.get("packet_id") == self.gpm_id
        assert guidance.get("tenant_id") == self.primary_tenant
        assert guidance.get("case_id") == self.case_id
        assert isinstance(guidance.get("recommendation"), str) and guidance["recommendation"].strip()
        assert isinstance(guidance.get("model_result"), dict) and guidance["model_result"]
        assert isinstance(guidance.get("lineage"), dict) and guidance["lineage"].get("case_id") == self.case_id
        return guidance

    def rejected_readback(self, detail):
        rejected = self.request("web", "GET", f"/api/drafts/{self.rejected_draft_id}")
        assert rejected["status"] == "rejected"
        assert "sent_at" in rejected and rejected["sent_at"] is None
        assert isinstance(detail.get("receipts"), list)
        assert all(isinstance(item, dict) and item.get("draft_id") != self.rejected_draft_id
                   for item in detail["receipts"])

    def restart_and_recover(self):
        for client in self.clients.values():
            client.close()
        completed = subprocess.run([str(self.prefix / "myaivan"), "restart"], capture_output=True, timeout=180)
        self.results["restart"] = {"exit_code": completed.returncode, "stdout_sha256": sha(completed.stdout),
                                   "stderr_sha256": sha(completed.stderr)}
        self.flush()
        if completed.returncode:
            raise AssertionError("Installed service restart failed; inspect private installation logs")
        if ((self.prefix / "current").resolve() != self.release or
                file_sha(self.release / "manifest.json") != self.results["manifest_sha256"]):
            raise AssertionError("Restart did not preserve the selected installed candidate")
        verified = subprocess.run([str(self.prefix / "myaivan"), "verify"], capture_output=True, timeout=90)
        self.results["restart_inventory"] = {"exit_code": verified.returncode,
                                             "stdout_sha256": sha(verified.stdout),
                                             "stderr_sha256": sha(verified.stderr)}
        self.flush()
        if verified.returncode:
            raise AssertionError("Restarted candidate inventory verification failed; inspect private installation logs")
        self.config = json.loads((self.prefix / "config.json").read_text())
        validate_bounded_options(self.args, self.config)
        self.clients = {name: httpx.Client(base_url=self.config.get("external", {}).get(name, f"http://127.0.0.1:{port}"),
                                          timeout=60, follow_redirects=False, trust_env=False)
                        for name, port in self.config["ports"].items() if name != "abcdyi"}
        self.tokens = {}
        detail = self.request("web", "GET", f"/api/workbench/cases/{self.case_id}")
        assert detail["case"]["status"] == "order_confirmed"
        assert detail["case"]["selected_option"] == self.selected_snapshot
        recovered = self.request("web", "GET", f"/api/workbench/cases/{self.case_id}/order-confirmation")
        assert recovered["purchase_order_id"] == self.po["purchase_order_id"]
        replayed = self.request("web", "POST", f"/api/workbench/cases/{self.case_id}/order-confirmation",
                                body={"selected_option_id": self.option_id}, key="confirm-po")
        assert replayed["recovered"] is True and replayed["purchase_order_id"] == self.po["purchase_order_id"]
        self.request("database", "GET", f"/api/data/purchase-orders/{self.po['purchase_order_id']}")
        self.request("database", "GET", f"/api/data/purchase-orders/{self.po['purchase_order_id']}",
                     tenant=self.secondary_tenant, expected=(404,))
        assert self.guidance_readback() == self.guidance_snapshot
        self.rejected_readback(detail)
        attachments = self.request("web", "GET", f"/api/workbench/cases/{self.case_id}/attachments")
        assert set(self.attachment_ids) <= {item["attachment_id"] for item in attachments["items"]}
        self.checkpoint("bounded_restart_and_authoritative_readback", industry_execution="not_run")


def bounded_failure(exc):
    site = traceback.extract_tb(exc.__traceback__)[-1]
    return {"type": type(exc).__name__, "message": "Bounded workflow failed; inspect retained check digests and private service logs",
            "site": {"function": site.name, "line": site.lineno}}


def build_parser():
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
    parser.add_argument("--scope", choices=("full", "aivan-bounded"), default="full")
    parser.add_argument("--tenant", help="Existing primary synthetic tenant for bounded acceptance")
    parser.add_argument("--other-tenant", help="Existing distinct synthetic tenant for isolation checks")
    return parser


def main():
    args = build_parser().parse_args()
    run = (BoundedAcceptance if args.scope == "aivan-bounded" else Acceptance)(args)
    try:
        run.workflow()
        if run.results["blockers"]:
            raise AssertionError("Independent checks failed; see retained blockers and HTTP evidence")
        run.results["status"] = "diagnostic_passed" if args.mixed_language_source else "passed"
        return_code = 0
    except Exception as exc:
        run.results["status"] = "failed"
        run.results["failure"] = (bounded_failure(exc) if args.scope == "aivan-bounded"
                                  else {"type": type(exc).__name__, "message": str(exc)})
        print(f"FAIL {type(exc).__name__}: {run.results['failure']['message']}", flush=True)
        return_code = 1
    finally:
        run.results["finished_at"] = now()
        run.flush()
        for client in run.clients.values():
            client.close()
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
