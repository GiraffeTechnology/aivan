#!/usr/bin/env python3
"""Offline MyAivan release controller. Requires only the bundled Python stdlib."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import tempfile
import urllib.error
import urllib.parse
import urllib.request

SERVICES = {
    "language": ("giraffe_language_skill.api.main:app", "/healthz"),
    "database": ("giraffe_db.api.main:app", "/healthz"),
    "gltg": ("gltg.api.main:app", "/health"),
    "gpm": ("aivan.gpm.server:app", "/api/gpm/healthz"),
    "web": ("aivan.api.main:app", "/healthz"),
}
NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
CONFIG_VERSION = 1


def read_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".new")
    with open(temporary, "w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def release(root: Path) -> Path:
    candidate = (root / "current").resolve(strict=True)
    if candidate.parent != (root / "releases").resolve():
        raise ValueError("Invalid installed release pointer")
    return candidate


def python(release_path: Path) -> str:
    return str(release_path / "runtime/bin/python3")


def process_identity(pid: int) -> str | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else fields[19]
    except (OSError, IndexError):
        return None


def owned_process(record: dict | None, root: Path | None = None) -> bool:
    if not isinstance(record, dict):
        return False
    pid, identity = record.get("pid"), record.get("identity")
    if type(pid) is not int or pid <= 1 or not isinstance(identity, str) or not identity.isdigit():
        return False
    live_identity = process_identity(pid)
    if live_identity is None or live_identity != identity:
        return False
    if root is not None:
        try:
            if Path(f"/proc/{pid}/cwd").resolve() != root.resolve():
                return False
            command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            executable = Path(os.fsdecode(command[0]))
            if not executable.is_relative_to(root / "releases"):
                return False
        except (OSError, ValueError):
            return False
    return True


def status(root: Path) -> dict:
    path = root / "run/processes.json"
    state = read_json(path) if path.exists() else {}
    return {"running": owned_process(state.get("supervisor"), root), "processes": state}


@contextlib.contextmanager
def operation_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(root / ".operation.lock", "a") as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another installation operation is in progress") from exc
        yield


def check_root(root: Path, initialize=False):
    if root == Path("/") or root.is_symlink() or ":" in str(root):
        raise ValueError("Installation prefix must be a dedicated, non-symlink directory without colon characters")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.stat().st_uid != os.geteuid() or root.stat().st_mode & 0o077:
        raise ValueError("Installation prefix must be owned by this user and mode 0700")
    marker = root / ".myaivan-installation.json"
    if not marker.exists():
        if not initialize or any(root.iterdir()):
            raise ValueError("Refusing an unrecognized or nonempty installation prefix")
        write_json(marker, {"format": 1, "owner": os.geteuid()})
    if marker.is_symlink() or read_json(marker) != {"format": 1, "owner": os.geteuid()}:
        raise ValueError("Invalid installation ownership marker")
    for name in ("releases", "data", "logs", "run", "backups"):
        path = root / name
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError("Managed directory must not be a symlink or foreign file")
    for name in ("config.json", "previous.json", ".operation.lock", "myaivan", "systemd.json"):
        if (root / name).is_symlink():
            raise ValueError("Managed file must not be a symlink")


def endpoint(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Service endpoints must be HTTP(S) URLs without embedded credentials, query or fragment")
    return value.rstrip("/")


def reserve_port(port: int = 0) -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))
        return sock.getsockname()[1]


def new_config(tenants: list[str], port: int = 0) -> dict:
    if type(port) is not int or (port != 0 and not 1024 <= port <= 65535):
        raise ValueError("Web port must be zero for automatic allocation or an unprivileged port")
    if not tenants or any(not NAME.fullmatch(tenant) or len(tenant) > 36 for tenant in tenants):
        raise ValueError("Tenant IDs must be unique ASCII identifiers of 1 to 36 characters")
    if len(set(tenants)) != len(tenants):
        raise ValueError("Duplicate tenant ID")
    ports = {}
    for name in SERVICES:
        selected = reserve_port(port if name == "web" else 0)
        while selected in ports.values():
            selected = reserve_port()
        ports[name] = selected
    return {
        "version": CONFIG_VERSION,
        "host_profile": "isolated",
        "origin": "https://myaivan.com",
        "ports": ports,
        "tenants": {tenant: secrets.token_urlsafe(32) for tenant in tenants},
        "secrets": {name: secrets.token_urlsafe(48) for name in ("session", "database", "gltg")},
        "external": {},
        "language": {"url": "", "provider": "ctranslate2", "model": "", "model_dir": ""},
        "model": {"url": "", "name": ""},
    }


def validate_config(config: dict):
    if config.get("version") != CONFIG_VERSION:
        raise ValueError("Unsupported configuration version")
    if not config.get("tenants") or any(not NAME.fullmatch(k) or len(k) > 36 or not isinstance(v, str) or len(v) < 32 for k, v in config["tenants"].items()):
        raise ValueError("Tenant IDs and credentials are invalid")
    if len(set(config["tenants"].values())) != len(config["tenants"]):
        raise ValueError("Every tenant must have a distinct frontend credential")
    ports = config.get("ports", {})
    if set(ports) != set(SERVICES) or any(type(p) is not int or not 1024 <= p <= 65535 for p in ports.values()) or len(set(ports.values())) != len(ports):
        raise ValueError("Distinct unprivileged ports are required for each bundled service")
    if config.get("host_profile") not in {"isolated", "ctyun", "sin", "other"}:
        raise ValueError("Unknown host profile")
    if config["host_profile"] == "ctyun" and 8443 in ports.values():
        raise ValueError("CTYun ports 443 and 8443 are reserved")
    for name in ("session", "database", "gltg"):
        if len(config.get("secrets", {}).get(name, "")) < 32:
            raise ValueError("Missing local service secret")
    external = config.get("external", {})
    if set(external) - {"database", "gltg", "gpm", "language", "aivan_database_url"}:
        raise ValueError("Unknown external dependency")
    for name, value in external.items():
        if name != "aivan_database_url":
            endpoint(value)
    endpoint(config["origin"])
    for group in ("language", "model"):
        if config.get(group, {}).get("url"):
            endpoint(config[group]["url"])


def environment(root: Path, rel: Path, config: dict) -> dict:
    env = {"PATH": f"{rel}/runtime/bin:/usr/bin:/bin", "HOME": str(root), "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    urls = {name: f"http://127.0.0.1:{port}" for name, port in config["ports"].items()}
    urls.update({key: value for key, value in config["external"].items() if key in SERVICES})
    library_dirs = [rel / "runtime/lib", *sorted((rel / "runtime/lib/python3.12/site-packages").glob("*.libs"))]
    env["LD_LIBRARY_PATH"] = ":".join(str(directory) for directory in library_dirs)
    env.update({
        "AIVAN_ENV": "production",
        "AIVAN_CANDIDATE_SHA": read_json(rel / "manifest.json")["components"]["aivan"]["revision"],
        "AIVAN_DB_URL": config["external"].get("aivan_database_url", f"sqlite:///{root}/data/aivan.db"),
        "AIVAN_TENANT_API_KEYS": json.dumps(config["tenants"]),
        "AIVAN_UI_SESSION_SECRET": config["secrets"]["session"],
        "AIVAN_UI_ACTOR_ID": "installation-operator",
        "AIVAN_UI_ALLOWED_ROLES": "admin",
        "AIVAN_UI_DEFAULT_ROLE": "admin",
        "AIVAN_REQUIRE_HUMAN_APPROVAL": "true",
        "AIVAN_CORS_ORIGINS": config["origin"],
        "AIVAN_PORT": str(config["ports"]["web"]),
        "AIVAN_EXTERNAL_MODEL_API_ENABLED": "false",
        "AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED": "false",
        "AIVAN_ALLOW_STUB_SUPPLIERS": "false",
        "AIVAN_LLM_API_ENABLED": "true" if config["model"]["url"] else "false",
        "AIVAN_LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": config["model"]["url"],
        "OLLAMA_MODEL": config["model"]["name"],
        "AIVAN_LANGUAGE_SKILL_ENABLED": "true",
        "AIVAN_LANGUAGE_SKILL_FAIL_SOFT": "false",
        "AIVAN_LANGUAGE_SKILL_BASE_URL": config["language"]["url"] or urls["language"],
        "GIRAFFE_LANGUAGE_SKILL_URL": config["language"]["url"] or urls["language"],
        "GIRAFFE_DB_REQUIRE_LANGUAGE_SKILL": "true",
        "GIRAFFE_DB_ENVIRONMENT": "production",
        "GIRAFFE_TRANSLATION_PROVIDER": "ctranslate2",
        "GIRAFFE_TRANSLATION_MODEL_DIR": config["language"].get("model_dir") or str(root / "models"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "AIVAN_LANGUAGE_SKILL_EXPECTED_PROVIDER": config["language"]["provider"],
        "AIVAN_LANGUAGE_SKILL_EXPECTED_MODEL": config["language"]["model"],
        "OPENCLAW_BASE_URL": "",
        "OPENCLAW_MOCK_MODE": "false",
        "AIVAN_EMAIL_SEND_MODE": "disabled",
        "GIRAFFE_DB_DATABASE_URL": f"sqlite+pysqlite:///{root}/data/giraffe.db",
        "GIRAFFE_DB_BASE_URL": urls["database"],
        "GIRAFFE_DB_SERVICE_AUTH_SECRET": config["secrets"]["database"],
        "GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON": json.dumps({tenant: config["secrets"]["database"] for tenant in config["tenants"]}),
        "GLTG_API_BASE_URL": urls["gltg"],
        "GLTG_SERVICE_AUTH_SECRET": config["secrets"]["gltg"],
        "GLTG_INBOUND_SERVICE_AUTH_SECRET": config["secrets"]["gltg"],
        "GLTG_GIRAFFE_DB_BASE_URL": urls["database"],
        "GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET": config["secrets"]["database"],
        "GLTG_PERSIST_RUNS": "true",
        "AIVAN_PERSIST_GIRAFFE_DB_GRAPH": "true",
        "GPM_API_BASE_URL": urls["gpm"],
        "GPM_TENANT_API_KEYS": json.dumps(config["tenants"]),
        "GPM_LLM_RUNTIME_MODE": "live",
    })
    return env


def active_services(config: dict):
    return [name for name in SERVICES if name not in config["external"]]


def health(root: Path) -> dict:
    config = read_json(root / "config.json")
    validate_config(config)
    report = {}
    for name, (_app, path) in SERVICES.items():
        url = config["external"].get(name, f"http://127.0.0.1:{config['ports'][name]}")
        try:
            with urllib.request.urlopen(url + path, timeout=3) as response:
                data = json.load(response)
            report[name] = {"ok": True, "response": data}
        except (OSError, ValueError, urllib.error.URLError):
            report[name] = {"ok": False}
    return {"ok": status(root)["running"] and all(item["ok"] for item in report.values()), "services": report,
            "workflow_acceptance": "not_measured_by_health", "public_entry": {"origin": config["origin"], "status": "authorized_HTTPS_ingress_required_and_unverified"}, "optional_dependencies": {"language": "configured_requires_validation" if config["language"]["url"] or config["language"].get("model_dir") else "canonical_validator_bundled_translation_models_missing", "model": "configured" if config["model"]["url"] else "disabled_deterministic_human_review_guidance", "email": "unconfigured_manual_copy_only"}}


def wait_healthy(root: Path, seconds: float = 45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        report = health(root)
        if report["ok"]:
            return report
        if not status(root)["running"]:
            break
        time.sleep(0.25)
    raise RuntimeError("Services did not become healthy; inspect private logs under the installation prefix")


def load_service_module():
    spec = importlib.util.spec_from_file_location("myaivan_service", Path(__file__).with_name("service.py"))
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    return service


def start(root: Path):
    if status(root)["running"]:
        return wait_healthy(root)
    # Reclaim only recorded, identity-verified children from a crashed supervisor.
    stop(root)
    if (root / "systemd.json").exists():
        try:
            load_service_module().start_registered(root)
            deadline = time.monotonic() + 45
            while not status(root)["running"] and time.monotonic() < deadline:
                time.sleep(0.1)
            return wait_healthy(root)
        except Exception:
            stop(root)
            raise
    rel = release(root)
    config = read_json(root / "config.json")
    validate_config(config)
    subprocess.run([python(rel), "-B", "-I", str(rel / "bootstrap.py"), str(root)], env=environment(root, rel, config), cwd=root, check=True)
    with open(root / "logs/supervisor.log", "ab") as log:
        child = subprocess.Popen([python(rel), "-B", "-I", str(rel / "runtime.py"), "--prefix", str(root), "supervise"], cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    state_path = root / "run/processes.json"
    for _ in range(100):
        if state_path.exists() and status(root)["running"]:
            break
        if child.poll() is not None:
            raise RuntimeError("Supervisor failed to start; inspect private supervisor log")
        time.sleep(0.05)
    try:
        return wait_healthy(root)
    except Exception:
        stop(root)
        raise


def stop(root: Path):
    state = status(root)["processes"]
    owner = state.get("supervisor")
    if owned_process(owner, root):
        os.kill(owner["pid"], signal.SIGTERM)
        deadline = time.monotonic() + 15
        while owned_process(owner, root) and time.monotonic() < deadline:
            time.sleep(0.1)
        if owned_process(owner, root):
            os.kill(owner["pid"], signal.SIGKILL)
    for record in state.get("children", {}).values():
        if owned_process(record, root):
            os.kill(record["pid"], signal.SIGTERM)
    deadline = time.monotonic() + 10
    records = list(state.get("children", {}).values())
    while any(owned_process(record, root) for record in records) and time.monotonic() < deadline:
        time.sleep(0.1)
    for record in records:
        if owned_process(record, root):
            os.kill(record["pid"], signal.SIGKILL)
    deadline = time.monotonic() + 5
    while any(owned_process(record, root) for record in records) and time.monotonic() < deadline:
        time.sleep(0.1)
    if any(owned_process(record, root) for record in records):
        raise RuntimeError("Owned child processes did not exit; data was not modified")
    (root / "run/processes.json").unlink(missing_ok=True)
    return {"stopped": True, "data_retained": True}


def supervise(root: Path):
    with open(root / "run/.supervisor.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("An existing supervisor owns this installation") from exc
        _supervise(root)


def _supervise(root: Path):
    rel = release(root)
    config = read_json(root / "config.json")
    env = environment(root, rel, config)
    stopping = False
    children = {}
    sockets = {}
    logs = {}
    state = {"supervisor": {"pid": os.getpid(), "identity": process_identity(os.getpid())}, "release": rel.name, "children": {}}
    def shutdown(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        # Reserve every managed port before starting anything. Never take over an occupied port.
        for name in active_services(config):
            sock = socket.socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sockets[name] = sock
            sock.bind(("127.0.0.1", config["ports"][name]))
            sock.listen(128)
            logs[name] = open(root / f"logs/{name}.log", "ab")
        write_json(root / "run/processes.json", state)
        failures = {name: 0 for name in sockets}
        started = {}
        retry_at = {}
        while not stopping:
            for name, sock in sockets.items():
                child = children.get(name)
                if child is not None and child.poll() is None:
                    continue
                if child is not None:
                    duration = time.monotonic() - started[name]
                    failures[name] = 0 if duration >= 60 else failures[name] + 1
                    if failures[name] > 5:
                        raise RuntimeError(f"{name} repeatedly failed; recovery stopped")
                    retry_at[name] = time.monotonic() + min(2 ** failures[name], 30)
                    children[name] = None
                if time.monotonic() < retry_at.get(name, 0):
                    continue
                command = [python(rel), "-B", "-I", "-m", "uvicorn", SERVICES[name][0], "--fd", str(sock.fileno()), "--no-access-log", "--no-proxy-headers"]
                child = subprocess.Popen(command, env=env, cwd=root, stdin=subprocess.DEVNULL, stdout=logs[name], stderr=logs[name], pass_fds=(sock.fileno(),))
                children[name] = child
                started[name] = time.monotonic()
                state["children"][name] = {"pid": child.pid, "identity": process_identity(child.pid)}
                write_json(root / "run/processes.json", state)
            time.sleep(0.2)
    finally:
        for child in children.values():
            if child is not None and child.poll() is None:
                child.terminate()
        for child in children.values():
            if child is not None:
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        for sock in sockets.values():
            sock.close()
        for stream in logs.values():
            stream.close()
        state_path = root / "run/processes.json"
        if state_path.exists() and read_json(state_path).get("supervisor") == state["supervisor"]:
            state_path.unlink()


def verify_payload(payload: Path):
    manifest = read_json(payload / "manifest.json")
    expected = manifest["files"]
    actual = set()
    for path in payload.rglob("*"):
        if path.is_symlink():
            raise ValueError("Package symlinks are not permitted")
        if path.is_file() and path != payload / "manifest.json":
            relative = str(path.relative_to(payload))
            actual.add(relative)
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected.get(relative):
                raise ValueError(f"Package integrity mismatch: {relative}")
    if actual != set(expected):
        raise ValueError("Package file inventory mismatch")
    return manifest


def set_current(root: Path, target: Path):
    link = root / ".current.new"
    link.unlink(missing_ok=True)
    link.symlink_to(target.relative_to(root))
    os.replace(link, root / "current")


def install(root: Path, payload: Path, tenants: list[str], port: int, no_start: bool):
    manifest = verify_payload(payload)
    version = manifest["release"]
    if not NAME.fullmatch(version):
        raise ValueError("Invalid package release identifier")
    for name in ("releases", "data", "logs", "run", "backups"):
        (root / name).mkdir(exist_ok=True, mode=0o700)
    config_path = root / "config.json"
    if not config_path.exists():
        write_json(config_path, new_config(tenants, port))
    config = read_json(config_path)
    validate_config(config)
    target = root / "releases" / version
    previous = release(root) if (root / "current").exists() else None
    if target.exists():
        if read_json(target / "manifest.json") != manifest:
            raise RuntimeError("Release ID already exists with different content")
        verify_payload(target)
    else:
        staging = Path(tempfile.mkdtemp(prefix=version + ".staging-", dir=root / "releases"))
        shutil.copytree(payload, staging, dirs_exist_ok=True)
        verify_payload(staging)
        os.replace(staging, target)
    stop(root)
    if previous and previous != target:
        snapshot = root / "backups" / f"{int(time.time())}-{previous.name}"
        snapshot.mkdir(mode=0o700)
        shutil.copytree(root / "data", snapshot / "data")
        shutil.copy2(config_path, snapshot / "config.json")
        write_json(root / "previous.json", {"release": previous.name, "snapshot": snapshot.name})
    set_current(root, target)
    launcher = root / "myaivan"
    launcher.write_text('#!/bin/sh\nset -eu\nROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec "$ROOT/current/runtime/bin/python3" -B -I "$ROOT/current/runtime.py" --prefix "$ROOT" "$@"\n')
    launcher.chmod(0o700)
    if not no_start:
        try:
            start(root)
        except Exception:
            if previous and previous != target:
                set_current(root, previous)
                failed_data = snapshot / "failed-upgrade-data"
                os.replace(root / "data", failed_data)
                shutil.copytree(snapshot / "data", root / "data")
                shutil.copy2(snapshot / "config.json", config_path)
                start(root)
            raise
    return {"installed": version, "prefix": str(root), "started": not no_start, "web_url": f"http://127.0.0.1:{config['ports']['web']}", "credentials_file": str(config_path), "data_retained": True, "workflow_acceptance": "not_measured_by_installation", "pending_configuration": ["verified HTTPS ingress for public browser access"], "optional_capabilities": {"model": "disabled_deterministic_human_review_guidance", "non_English_translation": "requires_verified_models_or_provider"}}


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    install_parser = commands.add_parser("install")
    install_parser.add_argument("--payload", type=Path, required=True)
    install_parser.add_argument("--tenant", action="append", default=[])
    install_parser.add_argument("--web-port", type=int, default=0)
    install_parser.add_argument("--no-start", action="store_true")
    for command in ("start", "stop", "restart", "health", "status", "supervise", "recover", "rollback", "uninstall", "verify", "serve", "service-install", "service-uninstall"):
        commands.add_parser(command)
    setup_parser = commands.add_parser("setup", help="Configure existing endpoints without editing files")
    setup_parser.add_argument("--origin")
    setup_parser.add_argument("--host-profile", choices=("isolated", "ctyun", "sin", "other"))
    setup_parser.add_argument("--web-port", type=int)
    setup_parser.add_argument("--model-url")
    setup_parser.add_argument("--model-name")
    setup_parser.add_argument("--language-url")
    setup_parser.add_argument("--language-model-dir", type=Path)
    setup_parser.add_argument("--database-url")
    setup_parser.add_argument("--restart", action="store_true")
    configure_parser = commands.add_parser("configure")
    configure_parser.add_argument("--file", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.prefix.absolute()
    check_root(root, initialize=args.command == "install")
    if args.command in {"supervise", "serve"}:
        if args.command == "serve":
            if status(root)["running"]:
                raise RuntimeError("Services already have a supervisor")
            stop(root)
            rel = release(root)
            config = read_json(root / "config.json")
            validate_config(config)
            subprocess.run([python(rel), "-B", "-I", str(rel / "bootstrap.py"), str(root)], env=environment(root, rel, config), cwd=root, check=True)
        supervise(root)
        return 0
    if args.command in {"health", "status", "verify"}:
        result = health(root) if args.command == "health" else status(root) if args.command == "status" else {"verified": verify_payload(release(root))["release"]}
    else:
        with operation_lock(root):
            if args.command in {"service-install", "service-uninstall"}:
                service = load_service_module()
                if args.command == "service-install":
                    result = service.install(root, stop=stop, start=start, status=status, wait_healthy=wait_healthy, write_json=write_json)
                else:
                    result = service.uninstall(root, stop=stop)
            elif args.command == "install":
                result = install(root, args.payload.resolve(), args.tenant or ["local-tenant"], args.web_port, args.no_start)
            elif args.command in {"start", "recover", "restart"}:
                if args.command != "start":
                    stop(root)
                result = start(root)
            elif args.command == "stop":
                result = stop(root)
            elif args.command == "setup":
                existing = read_json(root / "config.json")
                updated = json.loads(json.dumps(existing))
                for name in ("origin", "host_profile"):
                    if getattr(args, name) is not None:
                        updated[name] = getattr(args, name)
                if args.web_port is not None:
                    updated["ports"]["web"] = args.web_port
                for name in ("url", "name"):
                    if getattr(args, "model_" + name) is not None:
                        updated["model"][name] = getattr(args, "model_" + name)
                if args.language_url is not None:
                    updated["language"]["url"] = args.language_url
                    if args.language_url:
                        updated["external"]["language"] = endpoint(args.language_url)
                    else:
                        updated["external"].pop("language", None)
                if args.language_model_dir is not None:
                    if not args.language_model_dir.is_absolute() or not args.language_model_dir.is_dir():
                        raise ValueError("Translation models require an existing absolute directory")
                    updated["language"]["model_dir"] = str(args.language_model_dir)
                if args.database_url is not None:
                    if args.database_url:
                        updated["external"]["database"] = endpoint(args.database_url)
                    else:
                        updated["external"].pop("database", None)
                validate_config(updated)
                was_running = status(root)["running"]
                if was_running and not args.restart:
                    raise RuntimeError("Use setup --restart to apply settings transactionally to a running instance")
                stop(root)
                write_json(root / "config.json", updated)
                try:
                    if args.restart:
                        start(root)
                except Exception:
                    write_json(root / "config.json", existing)
                    if was_running:
                        start(root)
                    raise
                result = {"configured": True, "restarted": args.restart, "public_origin": updated["origin"],
                          "internal_web_url": f"http://127.0.0.1:{updated['ports']['web']}", "workflow_acceptance": "not_measured_by_setup",
                          "remaining_verification": ["existing HTTPS ingress", "selected business-flow acceptance"]}
            elif args.command == "configure":
                if status(root)["running"]:
                    raise RuntimeError("Stop services before changing configuration")
                new = read_json(args.file)
                validate_config(new)
                write_json(root / "config.json", new)
                result = {"configured": True, "restart_required": True}
            elif args.command == "rollback":
                previous = read_json(root / "previous.json")
                target = root / "releases" / previous["release"]
                verify_payload(target)
                stop(root)
                current = release(root)
                set_current(root, target)
                try:
                    result = start(root)
                except Exception:
                    set_current(root, current)
                    start(root)
                    raise
                result["rolled_back_to"] = target.name
                result["data_retained"] = True
            elif args.command == "uninstall":
                if (root / "systemd.json").exists():
                    service = load_service_module()
                    service.uninstall(root, stop=stop)
                result = stop(root)
                # Removal is reversible: data, config, backups and released binaries remain.
                (root / "current").unlink(missing_ok=True)
                (root / "myaivan").unlink(missing_ok=True)
                result["uninstalled"] = True
                result["reinstall_with_original_package"] = True
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"MyAivan: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
