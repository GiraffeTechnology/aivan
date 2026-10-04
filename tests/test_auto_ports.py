from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from aivan.api.cors import cors_origins
from aivan.observability.public_origin import resolved_public_origin
from aivan.utils.ports import RESERVED_PORT, bind_listening_socket, record_port, usable_port


def test_usable_port_rejects_443_and_invalid_values():
    assert usable_port("443") is None
    assert usable_port("") is None
    assert usable_port("0") is None
    assert usable_port("70000") is None
    assert usable_port("8443") == 8443


def test_auto_selection_binds_a_free_non_443_port():
    with bind_listening_socket("127.0.0.1") as sock:
        assert sock.getsockname()[1] not in (0, RESERVED_PORT)


def test_requested_443_is_never_bound():
    with bind_listening_socket("127.0.0.1", "443") as sock:
        assert sock.getsockname()[1] != RESERVED_PORT


def test_busy_requested_port_falls_back_to_another_free_port():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        with bind_listening_socket("127.0.0.1", taken) as sock:
            assert sock.getsockname()[1] not in (taken, RESERVED_PORT)


def test_free_requested_port_is_honoured():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        wanted = probe.getsockname()[1]
    with bind_listening_socket("127.0.0.1", wanted) as sock:
        assert sock.getsockname()[1] == wanted


def test_record_port_publishes_environment_and_file(tmp_path, monkeypatch):
    port_file = tmp_path / "run" / "aivan.port"
    monkeypatch.setenv("AIVAN_PORT_FILE", str(port_file))
    monkeypatch.delenv("AIVAN_PORT", raising=False)
    record_port(40123, env_var="AIVAN_PORT", file_env_var="AIVAN_PORT_FILE")
    assert os.environ["AIVAN_PORT"] == "40123"
    assert port_file.read_text(encoding="utf-8").strip() == "40123"


def test_public_origin_and_cors_follow_the_selected_port(monkeypatch):
    monkeypatch.delenv("AIVAN_PUBLIC_ORIGIN", raising=False)
    monkeypatch.delenv("AIVAN_PUBLIC_SCHEME", raising=False)
    monkeypatch.setenv("AIVAN_PUBLIC_HOST", "myaivan.test")
    monkeypatch.setenv("AIVAN_PORT", "40123")
    monkeypatch.setenv("AIVAN_CORS_ORIGINS", "")
    monkeypatch.setenv("AIVAN_ENV", "production")
    assert resolved_public_origin() == "http://myaivan.test:40123"
    assert cors_origins() == ["http://myaivan.test:40123"]


def test_serve_starts_on_an_automatically_selected_port(tmp_path):
    port_file = tmp_path / "aivan.port"
    env = {
        **os.environ,
        "AIVAN_ENV": "local",
        "AIVAN_PORT": "",
        "AIVAN_PORT_FILE": str(port_file),
        "AIVAN_DB_URL": f"sqlite:///{(tmp_path / 'aivan.db').as_posix()}",
    }
    process = subprocess.Popen(
        [sys.executable, "-c", "from aivan.cli.main import cmd_serve; cmd_serve(None)"],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        port = _wait_for_port(port_file, process)
        assert port != RESERVED_PORT
        response = _wait_for_health(port, process)
        assert response.status_code == 200
    finally:
        process.terminate()
        process.wait(timeout=10)


def _wait_for_port(port_file: Path, process: subprocess.Popen) -> int:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if port_file.exists() and port_file.read_text(encoding="utf-8").strip():
            return int(port_file.read_text(encoding="utf-8"))
        assert process.poll() is None, "server exited before choosing a port"
        time.sleep(0.1)
    raise AssertionError("server did not record a port")


def _wait_for_health(port: int, process: subprocess.Popen) -> httpx.Response:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            return httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=2)
        except httpx.TransportError:
            assert process.poll() is None, "server exited before serving"
            time.sleep(0.2)
    raise AssertionError("server did not become healthy")
