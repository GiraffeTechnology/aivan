"""Opt-in actual Gateway/plugin/Core transport test, not IM or MySQL acceptance."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

import httpx
import pytest


def test_openclaw_gateway_loads_plugin_and_reports_core_failure(tmp_path):
    """Run real processes with private state, no channel accounts or model turn."""
    if os.environ.get("RUN_OPENCLAW_GATEWAY_INTEGRATION_TESTS") != "1":
        pytest.skip("real Gateway runtime not selected; no live integration claim")
    source = Path(__file__).resolve().parents[2]
    plugin = Path(os.environ.get("AIVAN_OPENCLAW_PLUGIN_DIR",
        str(source / "integrations/openclaw-aivan-plugin"))).resolve()
    sdk = plugin / "node_modules/openclaw"
    node = Path(os.environ["AIVAN_OPENCLAW_NODE"]).resolve()
    python = Path(os.environ.get("AIVAN_OPENCLAW_PYTHON", sys.executable)).resolve()
    assert node.is_file() and python.is_file()
    assert (plugin / "dist/index.js").is_file(), "build the plugin before the live test"
    assert (sdk / "openclaw.mjs").is_file(), "install the locked peer runtime first"
    package = json.loads((sdk / "package.json").read_text())
    lock = json.loads((source / "integrations/openclaw-aivan-plugin/package-lock.json").read_text())
    assert package["version"] == lock["packages"]["node_modules/openclaw"]["version"]

    def free_port():
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            return listener.getsockname()[1]

    ports = {name: free_port() for name in ("core", "gateway")}
    urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
    token = secrets.token_hex(32)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    config = tmp_path / "openclaw.json"
    config.write_text(json.dumps({
        "gateway": {"mode": "local", "bind": "loopback", "port": ports["gateway"],
                    "auth": {"mode": "token", "token": token}},
        "plugins": {"enabled": True, "allow": ["openclaw-aivan"],
                    "load": {"paths": [str(plugin)]}, "slots": {"memory": "none"},
                    "entries": {"openclaw-aivan": {"enabled": True, "config": {
                        "aivanBaseUrl": urls["core"], "connectTimeoutMs": 300,
                        "readTimeoutMs": 1000, "maxRetries": 0}}}},
        "tools": {"allow": ["aivan.health", "aivan.openDashboard"]},
    }), encoding="utf-8")
    config.chmod(0o600)
    # Do not inherit existing channel accounts, provider keys, proxy destinations
    # or the unit suite's mock/test-mode environment into either real process.
    environment = {key: os.environ[key] for key in
        ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT") if key in os.environ}
    environment.update(
        NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
        OPENCLAW_CONFIG_PATH=str(config), OPENCLAW_STATE_DIR=str(state),
        OPENCLAW_HOME=str(tmp_path / "openclaw-home"),
        OPENCLAW_WORKSPACE_DIR=str(tmp_path / "workspace"),
        AIVAN_ENV="local", AIVAN_DB_URL=f"sqlite:///{(tmp_path / 'control.sqlite').as_posix()}",
        PYTHONDONTWRITEBYTECODE="1",
    )
    processes = {}
    streams = []

    def start(name, argv):
        stream = (tmp_path / f"{name}.log").open("ab")
        streams.append(stream)
        processes[name] = subprocess.Popen(argv, cwd=tmp_path, env=environment,
                                          stdout=stream, stderr=stream)

    def wait_http(name, path):
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            assert processes[name].poll() is None, f"{name} startup exited (logs withheld)"
            try:
                response = httpx.get(urls[name] + path, timeout=1, trust_env=False)
                if response.status_code < 500:
                    return response
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        pytest.fail(f"{name} did not become reachable")

    def invoke(tool, authenticated=True):
        return httpx.post(urls["gateway"] + "/tools/invoke",
            headers={"Authorization": "Bearer " + token} if authenticated else {},
            json={"tool": tool, "args": {}}, timeout=12, trust_env=False)

    def stop(name):
        process = processes[name]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=8)

    try:
        # Explicitly load the candidate source, rather than an ambient installed
        # package. This local control store does not validate a business provider.
        launcher = ("import sys,uvicorn;sys.path.insert(0,sys.argv[1]);"
                    "uvicorn.run('aivan.api.main:app',host='127.0.0.1',"
                    "port=int(sys.argv[2]),log_level='warning')")
        start("core", [str(python), "-B", "-I", "-c", launcher,
                       str(source / "src"), str(ports["core"])])
        core = wait_http("core", "/api/health")
        assert core.status_code == 200 and core.json()["product"] == "AIVAN"
        start("gateway", [str(node), str(sdk / "openclaw.mjs"), "gateway", "run",
                          "--bind", "loopback", "--port", str(ports["gateway"])])
        wait_http("gateway", "/health")
        assert invoke("aivan.health", authenticated=False).status_code == 401
        response = invoke("aivan.health")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["result"]["details"]["healthy"] is True
        assert body["result"]["details"]["version"] == core.json()["version"]
        dashboard = invoke("aivan.openDashboard")
        assert dashboard.status_code == 200 and dashboard.json()["ok"] is True
        assert invoke("aivan.approveDraft").status_code in (403, 404)
        stop("core")
        response = invoke("aivan.health")
        assert response.status_code == 200 and response.json()["ok"] is True
        details = response.json()["result"]["details"]
        assert details["healthy"] is False
        assert details["error_code"] == "AIVAN_UNREACHABLE"
    finally:
        for name in reversed(processes):
            stop(name)
        for stream in streams:
            stream.close()
        config.unlink(missing_ok=True)
    assert all(process.poll() is not None for process in processes.values())
    assert not config.exists()
