"""Explicit synthetic unit/transport fixtures, not installed CTYun acceptance."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest


@pytest.fixture
def runner_module():
    path = Path(__file__).resolve().parents[1] / "scripts/verify_installed_business_workflow.py"
    spec = importlib.util.spec_from_file_location("bounded_acceptance_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def options(**changes):
    values = dict(scope="aivan-bounded", synthetic_only=True, restart=True,
                  tenant="synthetic-primary", other_tenant="synthetic-secondary",
                  mixed_language_source=None, email_recorder=False,
                  allow_test_identity_fixtures=False)
    return SimpleNamespace(**{**values, **changes})


def configuration(**changes):
    return {"tenants": {"synthetic-primary": "synthetic-primary-key",
                        "synthetic-secondary": "synthetic-secondary-key"},
            "database_mode": "external", "external": {},
            "channels": {"email_enabled": False, "openclaw_url": ""}, **changes}


def test_cli_default_preserves_full_mode_and_explicit_bounded_selection(runner_module):
    parser = runner_module.build_parser()
    required = ["--prefix", "/synthetic/install", "--package", "/synthetic/candidate.run",
                "--evidence", "/synthetic/evidence"]
    assert parser.parse_args(required).scope == "full"
    selected = parser.parse_args(required + ["--scope", "aivan-bounded", "--tenant", "synthetic-primary",
                                           "--other-tenant", "synthetic-secondary", "--restart"])
    assert selected.scope == "aivan-bounded" and selected.restart


def test_bounded_options_do_not_require_unrelated_buyer_fixture_permission(runner_module):
    assert runner_module.validate_bounded_options(options(), configuration()) == (
        "synthetic-primary", "synthetic-secondary")


@pytest.mark.parametrize("change", [{"synthetic_only": False}, {"restart": False},
                                    {"tenant": None}, {"other_tenant": None},
                                    {"tenant": "not-configured"}, {"other_tenant": "synthetic-primary"},
                                    {"mixed_language_source": Path("/synthetic/source")},
                                    {"email_recorder": True}])
def test_bounded_options_fail_before_any_business_operation(runner_module, change):
    with pytest.raises(ValueError):
        runner_module.validate_bounded_options(options(**change), configuration())


@pytest.mark.parametrize("change", [{"database_mode": "isolated"},
                                    {"external": {"database": "https://synthetic.invalid"}},
                                    {"channels": {"email_enabled": True}},
                                    {"channels": {"openclaw_url": "https://synthetic.invalid"}}])
def test_bounded_profile_does_not_silently_substitute_data_or_enable_delivery(runner_module, change):
    with pytest.raises(ValueError):
        runner_module.validate_bounded_options(options(), configuration(**change))


def test_existing_language_endpoint_is_allowed_without_mixed_source_claim(runner_module):
    assert runner_module.validate_bounded_options(options(), configuration(
        external={"language": "http://127.0.0.1:8788"})) == (
            "synthetic-primary", "synthetic-secondary")


def runtime(module, transport):
    obj = object.__new__(module.BoundedAcceptance)
    obj.config = configuration()
    obj.primary_tenant = "synthetic-primary"
    obj.secondary_tenant = "synthetic-secondary"
    obj.run_id = "unit-contract"
    obj.clients = {name: httpx.Client(base_url="http://synthetic-contract.invalid", transport=transport)
                   for name in ("web", "database", "gpm", "gltg", "language")}
    obj.results = {"checks": [], "milestones": {}, "blockers": []}
    obj.flush = lambda: None
    obj.saved = {}
    obj.save = lambda name, data: obj.saved.update({name: data})
    return obj


def test_bounded_request_rejects_frozen_component_before_transport(runner_module):
    calls = []
    obj = runtime(runner_module, httpx.MockTransport(lambda request: calls.append(request)))
    with pytest.raises(ValueError):
        obj.request("abcdyi", "POST", "/api/orders/from-provider-confirmed", body={})
    assert calls == []


def test_http_failure_keeps_status_and_digest_without_remote_sensitive_text(runner_module):
    obj = runtime(runner_module, httpx.MockTransport(lambda request: httpx.Response(
        503, json={"detail": "synthetic-do-not-record-password"})))
    with pytest.raises(AssertionError) as exc:
        obj.request("web", "POST", "/api/drafts/example/reject", expected=(200,))
    assert "503" in str(exc.value)
    assert "synthetic-do-not-record-password" not in str(exc.value)
    assert obj.results["checks"][-1]["passed"] is False
    assert obj.results["checks"][-1]["response_sha256"]
    assert obj.saved == {}


def test_transport_failure_is_retained_without_credentials_or_fake_success(runner_module):
    def unavailable(request):
        raise httpx.ConnectError("synthetic-private-url-and-key", request=request)
    obj = runtime(runner_module, httpx.MockTransport(unavailable))
    with pytest.raises(AssertionError) as exc:
        obj.request("web", "GET", "/api/workbench/cases")
    assert "ConnectError" in str(exc.value)
    assert "synthetic-private-url-and-key" not in str(exc.value)
    assert obj.results["checks"][-1]["passed"] is False


def test_bounded_auth_checks_use_configured_tenants_and_never_fulfillment(runner_module):
    calls = []
    def denied(request):
        calls.append((request.url.path, dict(request.headers)))
        return httpx.Response(403, json={"detail": "synthetic rejection"})
    obj = runtime(runner_module, httpx.MockTransport(denied))
    obj.config["secrets"] = {"database": "synthetic-service-key"}
    obj.auth_checks()
    assert len(calls) == 10
    assert all(not path.startswith("/api/installation") for path, _ in calls)
    assert {headers.get("x-aivan-tenant-id") for _, headers in calls if "x-aivan-tenant-id" in headers} <= {
        "synthetic-primary", "synthetic-secondary"}
    assert all(check["passed"] for check in obj.results["checks"])
    assert obj.results["checks"][-1]["tenant"] == "synthetic-secondary"


def test_bounded_workflow_does_not_provision_buyer_or_call_industry_lifecycle(runner_module):
    # Its shared workflow is intentionally retained; the selected scope controls
    # execution, not monkeypatching a business API into a successful response.
    assert runner_module.BoundedAcceptance.bounded_scope is True
    assert runner_module.Acceptance.bounded_scope is False
    assert runner_module.BoundedAcceptance.restart_and_recover is not runner_module.Acceptance.restart_and_recover


def test_main_selects_only_the_explicit_scope(runner_module, monkeypatch):
    calls = []
    class FixtureRun:
        def __init__(self, args):
            self.args = args
            self.results = {"blockers": []}
            self.clients = {}
        def workflow(self): calls.append("bounded")
        def flush(self): pass
    class FullFixture(FixtureRun):
        def workflow(self): calls.append("full")
    monkeypatch.setattr(runner_module, "BoundedAcceptance", FixtureRun)
    monkeypatch.setattr(runner_module, "Acceptance", FullFixture)
    for scope in ("full", "aivan-bounded"):
        monkeypatch.setattr("sys.argv", ["runner", "--prefix", "/synthetic/install", "--package", "/synthetic/run",
                                         "--evidence", "/synthetic/evidence", "--scope", scope])
        assert runner_module.main() == 0
    assert calls == ["full", "bounded"]


@pytest.mark.parametrize("bounded", [False, True])
def test_shared_workflow_preserves_full_buyer_path_but_bounded_never_enters_it(runner_module, monkeypatch, bounded):
    calls = []
    class ReachedSupplierWrite(Exception):
        pass
    def transport(request):
        if request.url.path == "/v1/outbound/render":
            return httpx.Response(503, json={"detail": {"error": "TRANSLATION_FIDELITY_UNVERIFIED", "action": "pending_translation"}})
        assert request.url.path == "/api/data/suppliers"
        raise ReachedSupplierWrite()
    obj = runtime(runner_module, httpx.MockTransport(transport))
    if not bounded:
        obj.__class__ = runner_module.Acceptance
    obj.args = options()
    obj.prefix = Path("/synthetic/install")
    obj.release = Path("/synthetic/release")
    obj.config["secrets"] = {"database": "synthetic-service-key"}
    obj.scan_database = lambda: calls.append("sql-metadata")
    obj.auth_checks = lambda: calls.append("auth")
    obj.login = lambda tenant: calls.append("login-" + tenant)
    def buyer(*args):
        calls.append("buyer-provision")
        return {"id": "synthetic-buyer", "password": "synthetic-password"}
    monkeypatch.setattr(runner_module, "provision_buyer", buyer)
    with pytest.raises(ReachedSupplierWrite):
        obj.workflow()
    assert ("buyer-provision" in calls) is not bounded
    assert [value for value in calls if value.startswith("login-")] == ([] if bounded else ["login-tenant-a", "login-tenant-b"])


@pytest.fixture
def revision_contract(runner_module):
    calls = []
    fault = {}
    stage = {"replied": False}
    old = {"draft_id": "old", "status": "rejected", "delivered_at": None}
    base = {"case": {"customer_id": "buyer-source", "case_state": "supplier_replied", "selected_option": None},
            "drafts": [old], "receipts": [], "conversations": []}
    replacement = {"draft_id": "new", "status": "pending_approval", "delivered_at": None}
    updated = {**base, "case": {**base["case"], "selected_option": {
        "option_id": "selected-new", "supplier_id": "supplier-source",
        "quote": {"currency": "USD", "unit_price": "8.750000"},
        "lead_time_estimate": {"declared_lead_time_days": 30.5, "p50_days": 34.25, "p80_days": 40.75, "p90_days": 44.5}},
        "requirement": {"gpm_guidance": {"packet_id": "guidance-new"}}},
        "drafts": [old, replacement]}
    def handler(request):
        calls.append((request.method, request.url.path, request))
        assert request.headers["X-AIVAN-Tenant-ID"] == "synthetic-primary"
        path = request.url.path
        if path == "/api/drafts/old/reject":
            return httpx.Response(200, json={"draft_id": "old", "status": "rejected"})
        if path == "/api/drafts/old/approve":
            return httpx.Response(200 if fault.get("reapprove") else 409, json={})
        if path.endswith("/order-confirmation"):
            return httpx.Response(409, json={})
        if path == "/invoke":
            body = json.loads(request.content)
            assert body["project_id"] == "case-source" and body["sender_id"] == "buyer-source"
            assert request.headers["X-AIVAN-Participant-ID"] == "buyer-source"
            return httpx.Response(200, json={"status": "ok", "project_id": "case-source",
                "action": "pending_dependency_recovery" if fault.get("revision") else "pending_email_approval",
                "drafts_created": ["inquiry-revision"]})
        if path == "/api/rfq/create-from-event":
            body = json.loads(request.content)
            assert body["sender_id"] == "supplier-source" and "8.75" in body["message_text"]
            stage["replied"] = True
            return httpx.Response(200, json={"action": "buyer_options_ready", "drafts_created": ["new"]})
        assert path == "/api/workbench/cases/case-source"
        return httpx.Response(200, json=updated if stage["replied"] else base)
    obj = runtime(runner_module, httpx.MockTransport(handler))
    obj.case_id = "case-source"
    obj.option_id = "selected-old"
    obj.supplier_id = "supplier-source"
    return obj, calls, fault, base, updated


def test_real_route_contract_rejects_revises_and_generates_fresh_pending_quote(revision_contract):
    obj, calls, _, _, _ = revision_contract
    result, draft = obj.reject_revise_regenerate({"receipts": []}, {"draft_id": "old"})
    assert draft["draft_id"] == "new" and obj.option_id == "selected-new"
    assert obj.gpm_id == "guidance-new" and obj.draft_id == "new"
    assert any(path == "/invoke" for _, path, _ in calls)
    assert not any(path.startswith(("/api/orders", "/api/installation")) for _, path, _ in calls)
    assert not any(path == "/api/drafts/new/approve" for _, path, _ in calls)
    assert result["receipts"] == []


@pytest.mark.parametrize("fault", ["reapprove", "revision", "history", "replacement", "receipt", "currency", "fraction", "quantiles"])
def test_rejection_revision_contract_never_accepts_inconsistent_or_actionable_history(revision_contract, fault):
    obj, calls, faults, base, updated = revision_contract
    if fault in {"reapprove", "revision"}:
        faults[fault] = True
    elif fault == "history":
        updated["drafts"][0]["status"] = "pending_approval"
    elif fault == "replacement":
        updated["drafts"][1]["status"] = "approved"
    elif fault == "receipt":
        base["receipts"].append({"receipt_id": "unexpected-external-action"})
    elif fault == "currency":
        updated["case"]["selected_option"]["quote"]["currency"] = "EUR"
    elif fault == "fraction":
        updated["case"]["selected_option"]["lead_time_estimate"]["declared_lead_time_days"] = 30
    else:
        updated["case"]["selected_option"]["lead_time_estimate"]["p80_days"] = 20
    with pytest.raises(AssertionError):
        obj.reject_revise_regenerate({"receipts": []}, {"draft_id": "old"})
    assert not any(path == "/api/drafts/new/approve" for _, path, _ in calls)


@pytest.fixture
def restart_contract(runner_module, tmp_path, monkeypatch):
    release = tmp_path / "releases/candidate"
    release.mkdir(parents=True)
    (tmp_path / "current").symlink_to(release, target_is_directory=True)
    manifest = release / "manifest.json"
    manifest.write_text('{"release":"synthetic-candidate"}')
    config = configuration(secrets={"database": "synthetic-service-key"}, ports={
        name: 17000 + index for index, name in enumerate(("web", "database", "gpm", "gltg", "language", "abcdyi"))})
    (tmp_path / "config.json").write_text(json.dumps(config))
    calls = []
    faults = {}
    guidance = {"packet_id": "guidance-new", "tenant_id": "synthetic-primary",
                "case_id": "case-source", "recommendation": "review",
                "model_result": {"runtime_status": "disabled", "recommendation": "review"},
                "lineage": {"case_id": "case-source", "gltg_run_id": "lead-time-source"}}
    def handler(request):
        calls.append((request.method, request.url.path, request))
        assert request.url.port != config["ports"]["abcdyi"]
        path = request.url.path
        if path.endswith("/order-confirmation"):
            if request.method == "POST":
                assert request.headers["Idempotency-Key"] == "unit-contract-confirm-po"
            return httpx.Response(200, json={"purchase_order_id": "wrong" if faults.get("po") else "po-source", "recovered": True})
        if path.endswith("/attachments"):
            return httpx.Response(200, json={"items": [{"attachment_id": "attachment-source"}]})
        if path == "/api/drafts/old":
            rejected = {"status": "rejected", "sent_at": "2026-01-01T00:00:00Z" if faults.get("rejected-sent") else None}
            if faults.get("rejected-missing-timestamp"):
                rejected.pop("sent_at")
            return httpx.Response(200, json=rejected)
        if path == "/api/gpm/quote-guidance/guidance-new":
            recovered = json.loads(json.dumps(guidance))
            for fault, field, value in (("guidance-id", "packet_id", "other"),
                                        ("guidance-tenant", "tenant_id", "other"),
                                        ("guidance-case", "case_id", "other"),
                                        ("guidance-changed", "recommendation", "changed"),
                                        ("guidance-model", "model_result", {}),
                                        ("guidance-lineage", "lineage", {})):
                if faults.get(fault):
                    recovered[field] = value
            return httpx.Response(200, json={} if faults.get("guidance-empty") else recovered)
        if path == "/api/workbench/cases/case-source":
            return httpx.Response(200, json={"case": {"status": "order_confirmed", "selected_option": {"option_id": "changed" if faults.get("selected") else "selected-new"}},
                "receipts": [{"draft_id": "old", "receipt_id": "unexpected-delivery"}] if faults.get("rejected-receipt") else []})
        if path == "/api/data/purchase-orders/po-source" and request.headers["X-Service-Tenant-ID"] == "synthetic-secondary":
            return httpx.Response(404, json={})
        return httpx.Response(200, json={})
    obj = runtime(runner_module, httpx.MockTransport(handler))
    obj.args = options()
    obj.config["secrets"] = {"database": "synthetic-service-key"}
    obj.prefix, obj.release = tmp_path, release
    obj.results["manifest_sha256"] = runner_module.file_sha(manifest)
    obj.case_id, obj.option_id, obj.gpm_id = "case-source", "selected-new", "guidance-new"
    obj.po = {"purchase_order_id": "po-source"}
    obj.selected_snapshot = {"option_id": "selected-new"}
    obj.guidance_snapshot = json.loads(json.dumps(guidance))
    obj.rejected_draft_id = "old"
    obj.attachment_ids = ["attachment-source"]
    real_client = httpx.Client
    def client(*args, **kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return real_client(*args, **kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(runner_module.httpx, "Client", client)
    obj.command_calls = []
    def restart(argv, **kwargs):
        obj.command_calls.append(argv[-1])
        assert argv in ([str(tmp_path / "myaivan"), "restart"], [str(tmp_path / "myaivan"), "verify"])
        if argv[-1] == "verify":
            return SimpleNamespace(returncode=1 if faults.get("inventory") else 0,
                                   stdout=b"synthetic-private-verifier-log", stderr=b"")
        if faults.get("manifest"):
            manifest.write_text('{"release":"unexpected-rollback"}')
        return SimpleNamespace(returncode=1 if faults.get("restart") else 0, stdout=b"synthetic-private-log", stderr=b"")
    monkeypatch.setattr(runner_module.subprocess, "run", restart)
    return obj, calls, faults


def test_restart_recovers_order_and_history_through_fresh_authorized_http_clients(restart_contract):
    obj, calls, _ = restart_contract
    obj.restart_and_recover()
    assert obj.results["restart"]["exit_code"] == 0
    assert obj.command_calls == ["restart", "verify"]
    assert obj.results["restart_inventory"]["exit_code"] == 0
    assert "synthetic-private-log" not in json.dumps(obj.results)
    assert obj.results["milestones"]["bounded_restart_and_authoritative_readback"]
    assert any(method == "POST" and path.endswith("/order-confirmation") for method, path, _ in calls)
    assert {request.headers.get("X-AIVAN-Tenant-ID", request.headers.get("X-Service-Tenant-ID"))
            for _, _, request in calls} == {"synthetic-primary", "synthetic-secondary"}


@pytest.mark.parametrize("fault", ["manifest", "restart", "po", "selected", "inventory",
                                    "guidance-empty", "guidance-id", "guidance-tenant", "guidance-case",
                                    "guidance-changed", "guidance-model", "guidance-lineage",
                                    "rejected-sent", "rejected-missing-timestamp", "rejected-receipt"])
def test_restart_or_readback_failure_never_counts_as_recovery(restart_contract, fault):
    obj, calls, faults = restart_contract
    faults[fault] = True
    with pytest.raises(AssertionError):
        obj.restart_and_recover()
    assert "bounded_restart_and_authoritative_readback" not in obj.results["milestones"]
    if fault in {"manifest", "restart", "inventory"}:
        assert calls == []


def test_sql_preflight_failure_happens_before_auth_or_business_http(runner_module):
    obj = object.__new__(runner_module.BoundedAcceptance)
    calls = []
    def failed():
        calls.append("sql-metadata")
        raise AssertionError("synthetic unavailable database")
    obj.scan_database = failed
    obj.auth_checks = lambda: calls.append("unexpected-http")
    with pytest.raises(AssertionError):
        obj.workflow()
    assert calls == ["sql-metadata"]


def test_bounded_evidence_redacts_nested_credential_fields(runner_module, tmp_path):
    obj = object.__new__(runner_module.BoundedAcceptance)
    obj.evidence = tmp_path
    obj.save("response", {"result": [{"access_token": "synthetic-private-token", "status": "observed"}],
                          "password": "synthetic-private-password"})
    text = (tmp_path / "response.json").read_text()
    assert "synthetic-private" not in text and "observed" in text


def test_bounded_main_failure_keeps_error_site_not_remote_secret(runner_module, monkeypatch, capsys):
    instances = []
    class FailureFixture:
        def __init__(self, args):
            self.results, self.clients = {"blockers": []}, {}
            instances.append(self)
        def workflow(self): raise RuntimeError("synthetic-private-remote-response")
        def flush(self): pass
    monkeypatch.setattr(runner_module, "BoundedAcceptance", FailureFixture)
    monkeypatch.setattr("sys.argv", ["runner", "--prefix", "/synthetic", "--package", "/synthetic/run", "--evidence", "/synthetic/evidence", "--scope", "aivan-bounded"])
    assert runner_module.main() == 1
    assert "synthetic-private-remote-response" not in capsys.readouterr().out
    failure = instances[0].results["failure"]
    assert failure["type"] == "RuntimeError" and failure["site"]["function"] == "workflow"
    assert "synthetic-private" not in json.dumps(failure)


@pytest.mark.parametrize("fault", ["helper-identity", "non-mysql"])
def test_sql_probe_rejects_unbound_helper_or_non_mysql_before_connecting(runner_module, tmp_path, monkeypatch, fault):
    import sqlalchemy
    helper = tmp_path / "database_config.py"
    helper.write_text("def configured_targets(config, prefix):\n    return {'aivan': {'engine': 'sqlite'}}\n")
    obj = object.__new__(runner_module.BoundedAcceptance)
    obj.release = obj.prefix = tmp_path
    obj.config = configuration()
    obj.manifest = {"files": {"database_config.py": "0" * 64 if fault == "helper-identity" else runner_module.file_sha(helper)}}
    calls = []
    def unexpected_connect(*args, **kwargs):
        calls.append("unexpected SQL connection")
        raise RuntimeError("A rejected profile must not connect")
    monkeypatch.setattr(sqlalchemy, "create_engine", unexpected_connect)
    with pytest.raises(ValueError):
        obj.scan_database()
    assert calls == []
