"""Opt-in real HTTP component regression, not target MySQL/full-flow acceptance."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time

import httpx
import pytest

from aivan.integrations.gltg_client import GLTGClient
from aivan.integrations.gpm_guidance_client import GPMGuidanceClient, GPMGuidanceUnavailableError


def test_gpm_selected_provider_http_replay_restart_and_failure(tmp_path, monkeypatch):
    """Run actual services with isolated synthetic records and no outward send."""
    selected = os.environ.get("AIVAN_GPM_COMPONENT_RUNTIME", "")
    if not selected:
        pytest.skip("selected runtime is not configured; no real integration claim")
    # These flags must be set before pytest's autouse fixtures are entered.
    for flag in ("RUN_GLTG_INTEGRATION_TESTS", "RUN_GPM_INTEGRATION_TESTS",
                 "RUN_LANGUAGE_SKILL_INTEGRATION_TESTS"):
        assert os.environ.get(flag) == "1", "live fixture flags must disable suite transports"
    assert os.environ.get("GIRAFFE_LANGUAGE_SKILL_URL"), "real canonical-language API required"
    assert os.environ.get("GLTG_API_BASE_URL"), "real GLTG API required"
    payload = Path(selected).resolve()
    runtime = payload / "runtime/bin/python3"
    provider = payload / "provider-assets/giraffe-db"
    assert runtime.is_file() and (provider / "alembic.ini").is_file()
    source = Path(__file__).resolve().parents[2] / "src"
    tenants = ("synthetic_gpm_a", "synthetic_gpm_b")
    db_keys = {tenant: secrets.token_hex(32) for tenant in tenants}
    api_keys = {tenant: secrets.token_hex(32) for tenant in tenants}
    environment = {key: value for key, value in os.environ.items() if not key.startswith(
        ("AIVAN_", "GIRAFFE_DB_", "GPM_", "OPENCLAW_"))}
    environment.update(
        NO_PROXY="127.0.0.1,localhost,::1", no_proxy="127.0.0.1,localhost,::1",
        GIRAFFE_DB_ENVIRONMENT="production", GIRAFFE_DB_REQUIRE_LANGUAGE_SKILL="true",
        GIRAFFE_DB_DATABASE_URL=f"sqlite+pysqlite:///{(tmp_path / 'provider.sqlite').as_posix()}",
        GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON=json.dumps(db_keys),
        AIVAN_ENV="production", AIVAN_TENANT_API_KEYS=json.dumps(api_keys),
        AIVAN_LLM_API_ENABLED="false", PYTHONDONTWRITEBYTECODE="1",
    )
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost,::1")
    monkeypatch.setenv("GPM_TENANT_API_KEYS", json.dumps(api_keys))
    monkeypatch.setenv("AIVAN_TENANT_ID", tenants[0])

    def free_port():
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            return listener.getsockname()[1]

    ports = {name: free_port() for name in ("database", "gpm")}
    urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
    environment["GIRAFFE_DB_BASE_URL"] = urls["database"]
    monkeypatch.setenv("GPM_API_BASE_URL", urls["gpm"])
    migrated = subprocess.run([str(runtime), "-B", "-m", "alembic", "upgrade", "head"],
        cwd=provider, env={**environment, "PYTHONPATH": str(provider / "src")},
        capture_output=True, timeout=60)
    assert migrated.returncode == 0, "isolated provider migration failed (output withheld)"
    # Match the shipped installer control bootstrap. No business fact is seeded
    # through SQL; all buyer/case/supplier/packet actions below use the Data API.
    bootstrap = """from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from giraffe_db.db.models.core import Tenant
import json,os
with Session(create_engine(os.environ['GIRAFFE_DB_DATABASE_URL'])) as session:
 for tenant in json.loads(os.environ['GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON']):
  session.add(Tenant(id=tenant,name=tenant,tenant_id=tenant,
                    source_type='installer',created_by='isolated-test-operator'))
 session.commit()
"""
    bootstrapped = subprocess.run([str(runtime), "-B", "-I", "-c", bootstrap],
        cwd=tmp_path, env=environment, capture_output=True, timeout=20)
    assert bootstrapped.returncode == 0, "isolated control bootstrap failed (output withheld)"
    processes = []

    def db_headers(tenant):
        return {"X-Service-Tenant-ID": tenant, "X-Service-Auth": db_keys[tenant],
                "X-AIVAN-Correlation-ID": "synthetic-gpm-http"}

    def start(name):
        module = "giraffe_db.api.main:app" if name == "database" else "aivan.gpm.server:app"
        launcher = ("import sys,uvicorn;sys.path.insert(0,sys.argv[1]);"
                    "uvicorn.run(sys.argv[2],host='127.0.0.1',port=int(sys.argv[3]),log_level='warning')")
        process = subprocess.Popen([str(runtime), "-B", "-I", "-c", launcher,
            str(source), module, str(ports[name])], cwd=tmp_path, env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(process)
        deadline = time.monotonic() + 30
        path = "/api/data/schema-version" if name == "database" else "/api/gpm/healthz"
        while time.monotonic() < deadline:
            assert process.poll() is None, "isolated component exited before readiness"
            try:
                response = httpx.get(urls[name] + path, headers=db_headers(tenants[0]),
                                     timeout=1, trust_env=False)
                if response.status_code == 200:
                    return process
            except httpx.TransportError:
                pass
            time.sleep(0.1)
        pytest.fail("isolated component readiness timed out")

    def stop(process):
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

    with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as http:
        def request(method, service, path, *, expected=200, **kwargs):
            response = http.request(method, urls[service] + path, **kwargs)
            assert response.status_code == expected, f"{method} {path}: status {response.status_code}"
            return response

        try:
            database_process = start("database")
            gpm_process = start("gpm")
            tenant = tenants[0]
            trusted = GPMGuidanceClient._trusted_headers(tenant_id=tenant,
                actor_id="synthetic_operator", actor_role="sales", trace_id="synthetic-gpm-create",
                idempotency_key="synthetic-gpm-one")
            request("GET", "gpm", "/api/gpm/readiness", headers=trusted)
            capabilities = request("GET", "gpm", "/api/gpm/capabilities").json()
            assert capabilities["features"]["approval_workflow"] is False
            assert capabilities["features"]["rejection_workflow"] is False
            assert capabilities["features"]["durable_packet_persistence"] is True
            buyer = request("POST", "database", "/api/data/buyers", headers=db_headers(tenant),
                json={"buyer_name": "Synthetic Cotton Clothing Buyer"}).json()
            case = request("POST", "database", "/api/data/procurement-cases", headers=db_headers(tenant),
                json={"buyer_id": buyer["buyer_id"], "status": "inquiry_received"}).json()
            supplier = request("POST", "database", "/api/data/suppliers", headers=db_headers(tenant),
                json={"supplier_name": "Synthetic Component Supplier", "is_synthetic": True}).json()
            lead = GLTGClient().simulate_lead_time_v2({"request_id": "synthetic-gpm-component-lead",
                "tenant_id": tenant, "order": {"product_type": "apparel", "quantity": 100},
                "supplier": {"supplier_id": supplier["supplier_id"], "capacity_per_day": 80},
                "evidence": {"use_giraffe_db": False}, "source_observation_ids": []})
            assert lead.ok, "real GLTG component request failed"
            quantiles = lead.data["quantiles"]
            assert 0 <= quantiles["p50_days"] <= quantiles["p80_days"] <= quantiles["p90_days"]
            note = ("Our synthetic supplier has confirmed that one hundred cotton shirts are available. "
                    "The quoted unit price is ten United States dollars and the total supplier price is "
                    "one thousand United States dollars. Please review these test purchase requirements "
                    "before making any decision. This is isolated synthetic business data, not a real order.")
            args = dict(tenant_id=tenant, actor_id="synthetic_operator", actor_role="sales",
                trace_id="synthetic-gpm-create", idempotency_key="synthetic-gpm-one",
                case_id=case["procurement_case_id"],
                quote_id="aivan-source-quote-sha256-" + hashlib.sha256(note.encode()).hexdigest(),
                sku="SYNTHETIC-COTTON-SHIRT", supplier_id=supplier["supplier_id"],
                supplier_quote=10.0, currency="USD", quantity=100, buyer_unit_price=12.5,
                buyer_total=1250.0, supplier_total=1000.0, margin_rate=0.2,
                gltg_run_id=lead.data["gltg_run_id"], gltg_api_version="v2", evidence_ids=[], notes=note)
            client = GPMGuidanceClient()
            packet = client.create_guidance(**args)
            assert packet["human_approval_required"] is True
            assert packet["approval_status"] == "pending" and packet["dispatched"] is False
            assert packet["model_result"]["runtime_status"] == "disabled"
            assert client.create_guidance(**{**args, "trace_id": "synthetic-gpm-replay"}) == packet
            with pytest.raises(GPMGuidanceUnavailableError, match="^GPM_HTTP_409$"):
                client.create_guidance(**{**args, "quantity": 101})
            path = "/api/gpm/quote-guidance/" + packet["packet_id"]
            request("GET", "gpm", path, expected=401)
            request("GET", "gpm", path, headers={**trusted, "X-AIVAN-API-Key": api_keys[tenants[1]]}, expected=403)
            other = GPMGuidanceClient._trusted_headers(tenant_id=tenants[1],
                actor_id="synthetic_operator", actor_role="sales", trace_id="synthetic-gpm-other",
                idempotency_key="synthetic-gpm-other")
            request("GET", "gpm", path, headers=other, expected=403)
            assert request("GET", "database", "/api/data/gpm/packets/" + packet["packet_id"],
                           headers=db_headers(tenant)).json()["packet_id"] == packet["packet_id"]
            stop(gpm_process)
            stop(database_process)
            database_process = start("database")
            gpm_process = start("gpm")
            assert request("GET", "gpm", path, headers=trusted).json() == packet
            stop(database_process)
            request("GET", "gpm", path, headers=trusted, expected=503)
        finally:
            for process in processes:
                stop(process)
