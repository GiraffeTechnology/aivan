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
import uuid

SERVICES = {
    "language": ("giraffe_language_skill.api.main:app", "/healthz"),
    "database": ("giraffe_db.api.main:app", "/healthz"),
    "gltg": ("gltg.api.main:app", "/health"),
    "gpm": ("aivan.gpm.server:app", "/api/gpm/healthz"),
    "web": ("aivan.api.main:app", "/healthz"),
    "abcdyi": ("api.main:app", "/health"),
}
NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
CONFIG_VERSION = 2


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


def load_deployment_module():
    spec = importlib.util.spec_from_file_location("myaivan_deployment_config", Path(__file__).with_name("deployment_config.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bind_available_port(requested: int, reserved: set[int], used: set[int]):
    """Reserve a real listener; occupied/reserved requests fall back safely."""
    preferred = requested if requested not in reserved and requested not in used else 0
    for _attempt in range(100):
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", preferred))
            selected = listener.getsockname()[1]
            if selected in reserved or selected in used:
                listener.close()
                preferred = 0
                continue
            listener.listen(128)
            return listener, selected
        except OSError:
            listener.close()
            if not preferred:
                raise
            preferred = 0
    raise RuntimeError("No free non-reserved service port could be allocated")


def publish_ports(root: Path, config: dict):
    write_json(root / "run/ports.json", {
        "version": 1,
        "public_origin": config["origin"],
        "services": {name: {"managed": name not in config["external"], "port": port,
                            "url": config["external"].get(name, f"http://127.0.0.1:{port}")}
                     for name, port in config["ports"].items()},
    })


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
    provider_id = "local-provider-" + secrets.token_hex(12)
    return {
        "version": CONFIG_VERSION,
        "private_data_provider_id": provider_id,
        "bundled_private_data_provider_id": provider_id,
        "host_profile": "isolated",
        "origin": "https://myaivan.com",
        "ports": ports,
        "tenants": {tenant: secrets.token_urlsafe(32) for tenant in tenants},
        "secrets": {name: secrets.token_urlsafe(48) for name in ("session", "database", "gltg", "abcdyi")},
        "fulfillment": {"port": ports["abcdyi"], "tenants": fulfillment_tenants(tenants)},
        "database_mode": "external",
        "database_config_file": "",
        "service_credentials_file": "",
        "reserved_ports": sorted(load_deployment_module().reserved_ports({})),
        "runtime_threads": 2,
        "channels": {"openclaw_url": "", "send_endpoint": "/messages/send", "email_enabled": False},
        "external": {},
        "language": {"url": "", "provider": "ctranslate2", "model": "", "model_dir": ""},
        "model": {"url": "", "name": ""},
    }


def fulfillment_tenants(tenants):
    return {tenant: {"tenant_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "myaivan:abcdyi:tenant:" + tenant)),
                     "operator_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "myaivan:abcdyi:operator:" + tenant))}
            for tenant in tenants}


def upgrade_config(config):
    config = json.loads(json.dumps(config))
    if config.get("version") == 1:
        validate_config(config)
        port = config.get("fulfillment", {}).get("port") or reserve_port()
        while port in config["ports"].values():
            port = reserve_port()
        provider_id = config.get("private_data_provider_id") or "local-provider-" + secrets.token_hex(12)
        config["private_data_provider_id"] = provider_id
        config.setdefault("bundled_private_data_provider_id", provider_id)
        config["version"] = CONFIG_VERSION
        config["ports"]["abcdyi"] = port
        config["secrets"].setdefault("abcdyi", secrets.token_urlsafe(48))
        config["fulfillment"] = {"port": port, "tenants": fulfillment_tenants(config["tenants"])}
    if "database_mode" not in config:
        config["database_mode"] = "isolated" if config.get("host_profile") == "isolated" else "external"
        config["database_config_file"] = ""
    return config


def config_for_release(config, target):
    if config.get("database_mode") == "external" and "database_config.py" not in read_json(target / "manifest.json").get("files", {}):
        raise RuntimeError("The previous release cannot preserve the configured external databases; rollback was not started")
    if ("deployment_config.py" not in read_json(target / "manifest.json").get("files", {})
            and (config.get("service_credentials_file") or config.get("channels", {}).get("email_enabled")
                 or config.get("reserved_ports"))):
        raise RuntimeError("The previous release cannot preserve this deployment profile; rollback was not started")
    if "abcdyi" in read_json(target / "manifest.json").get("components", {}):
        return upgrade_config(config)
    config = json.loads(json.dumps(config))
    config["version"] = 1
    config["ports"].pop("abcdyi", None)
    # Retain the dormant sixth-service identity/config and business DB so a
    # later upgrade restores the same tenant association without data loss.
    return config


def validate_config(config: dict):
    if config.get("version") not in {1, CONFIG_VERSION}:
        raise ValueError("Unsupported configuration version")
    if not config.get("tenants") or any(not NAME.fullmatch(k) or len(k) > 36 or not isinstance(v, str) or len(v) < 32 or not v.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in v) for k, v in config["tenants"].items()):
        raise ValueError("Tenant IDs and credentials are invalid")
    if len(set(config["tenants"].values())) != len(config["tenants"]):
        raise ValueError("Every tenant must have a distinct frontend credential")
    ports = config.get("ports", {})
    expected_services = set(SERVICES) - ({"abcdyi"} if config["version"] == 1 else set())
    if set(ports) != expected_services or any(type(p) is not int or p != 0 and not 1024 <= p <= 65535 for p in ports.values()):
        raise ValueError("Service ports must be zero for automatic allocation or unprivileged requests")
    if config.get("host_profile") not in {"isolated", "ctyun", "sin", "other"}:
        raise ValueError("Unknown host profile")
    for name in (("session", "database", "gltg") if config["version"] == 1 else ("session", "database", "gltg", "abcdyi")):
        value = config.get("secrets", {}).get(name, "")
        if not isinstance(value, str) or len(value) < 32 or not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Missing or invalid local service secret")
    if config["version"] == CONFIG_VERSION:
        if any(not isinstance(config.get(key), str) or not NAME.fullmatch(config[key])
               for key in ("private_data_provider_id", "bundled_private_data_provider_id")):
            raise ValueError("A stable logical private-data provider identity is required")
        fulfillment = config.get("fulfillment", {})
        if fulfillment.get("tenants") != fulfillment_tenants(config["tenants"]):
            raise ValueError("Fulfillment tenant identities must match the installation tenant map")
        if fulfillment.get("port") != ports["abcdyi"]:
            raise ValueError("Fulfillment port does not match the managed service")
    if config.get("database_mode", "external") not in {"isolated", "external"}:
        raise ValueError("Unknown database configuration mode")
    if config.get("database_config_file") and not Path(config["database_config_file"]).is_absolute():
        raise ValueError("Database configuration requires an absolute private file path")
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
    load_deployment_module().validate(config, endpoint=endpoint)


def load_database_module():
    spec = importlib.util.spec_from_file_location("myaivan_database_config", Path(__file__).with_name("database_config.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def environment(root: Path, rel: Path, config: dict) -> dict:
    targets = load_database_module().configured_targets(config, root)
    env = {"PATH": f"{rel}/runtime/bin:/usr/bin:/bin", "HOME": str(root), "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    env.update({name: str(config.get("runtime_threads", 2)) for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")})
    urls = {name: f"http://127.0.0.1:{port}" for name, port in config["ports"].items()}
    urls.update({key: value for key, value in config["external"].items() if key in SERVICES})
    library_dirs = [rel / "runtime/lib", *sorted((rel / "runtime/lib/python3.12/site-packages").glob("*.libs"))]
    env["LD_LIBRARY_PATH"] = ":".join(str(directory) for directory in library_dirs)
    env.update({
        "AIVAN_ENV": "production",
        "AIVAN_CANDIDATE_SHA": read_json(rel / "manifest.json")["components"]["aivan"]["revision"],
        "AIVAN_DB_URL": targets["aivan"]["url"],
        "MYAIVAN_DATABASE_MODE": config.get("database_mode", "external"),
        "MYAIVAN_DATABASE_SCHEMAS": json.dumps({name: value["schema"] for name, value in targets.items()}),
        "AIVAN_TENANT_API_KEYS": json.dumps(config["tenants"]),
        "AIVAN_UI_SESSION_SECRET": config["secrets"]["session"],
        "AIVAN_UI_ACTOR_ID": "installation-operator",
        "AIVAN_UI_ALLOWED_ROLES": "admin",
        "AIVAN_UI_DEFAULT_ROLE": "admin",
        "AIVAN_REQUIRE_HUMAN_APPROVAL": "true",
        "AIVAN_CORS_ORIGINS": config["origin"],
        "AIVAN_PORT": str(config["ports"]["web"]),
        "AIVAN_RESERVED_PORTS": ",".join(str(port) for port in sorted(load_deployment_module().reserved_ports(config))),
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
        "OPENCLAW_BASE_URL": config.get("channels", {}).get("openclaw_url", "") if config.get("channels", {}).get("email_enabled") else "",
        "OPENCLAW_SEND_ENDPOINT": config.get("channels", {}).get("send_endpoint", "/messages/send"),
        "OPENCLAW_MOCK_MODE": "false",
        "AIVAN_EMAIL_SEND_MODE": "openclaw" if config.get("channels", {}).get("email_enabled") else "disabled",
        "GIRAFFE_DB_DATABASE_URL": targets.get("database", {}).get("url", ""),
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
    if "abcdyi" in config["ports"]:
        mapping = config["fulfillment"]["tenants"]
        env.update({
            "DATABASE_URL": targets["abcdyi"]["url"],
            "SECRET_KEY": config["secrets"]["abcdyi"],
            "ABCDYI_PRIVATE_DATA_PROVIDER_ID": config["private_data_provider_id"],
            "ABCDYI_PRIVATE_DATA_TENANT_MAP": json.dumps({item["tenant_id"]: tenant for tenant, item in mapping.items()}),
            "MYAIVAN_FULFILLMENT_TENANTS": json.dumps(mapping),
            "MYAIVAN_FULFILLMENT_API_KEYS": json.dumps(config["tenants"]),
            "ABCDYI_LANGUAGE_SKILL_BASE_URL": config["language"]["url"] or urls["language"],
        })
    env.update(load_deployment_module().credential_environment(config))
    return env


def active_services(config: dict):
    return [name for name in SERVICES if name in config["ports"] and name not in config["external"]]


def health(root: Path) -> dict:
    config = read_json(root / "config.json")
    validate_config(config)
    spec = importlib.util.spec_from_file_location("myaivan_healthcheck", Path(__file__).with_name("healthcheck.py"))
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    report = checks.probe(config, SERVICES, load_deployment_module().credentials(config))
    return {"ok": status(root)["running"] and all(item["ok"] for item in report.values()), "services": report,
            "workflow_acceptance": "not_measured_by_health", "public_entry": {"origin": config["origin"], "status": "authorized_HTTPS_ingress_required_and_unverified"}, "optional_dependencies": {"language": "configured_requires_validation" if config["language"]["url"] or config["language"].get("model_dir") else "canonical_validator_bundled_translation_models_missing", "model": "configured" if config["model"]["url"] else "disabled_deterministic_human_review_guidance", "email": "configured_explicit_human_confirmation_required" if config.get("channels", {}).get("email_enabled") else "unconfigured_manual_copy_only"}}


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
    config = read_json(root / "config.json")
    validate_config(config)
    load_deployment_module().credentials(config, require_external=True)
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
        # Reserve every managed port before starting anything. Preserve existing owners.
        reserved = load_deployment_module().reserved_ports(config)
        used = set()
        for name in active_services(config):
            sock, selected = bind_available_port(config["ports"][name], reserved, used)
            sockets[name] = sock
            config["ports"][name] = selected
            used.add(selected)
            logs[name] = open(root / f"logs/{name}.log", "ab")
        if "abcdyi" in config["ports"]:
            config["fulfillment"]["port"] = config["ports"]["abcdyi"]
        write_json(root / "config.json", config)
        publish_ports(root, config)
        env = environment(root, rel, config)
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
                if name == "abcdyi":
                    command = [python(rel), "-B", "-I", str(rel / "abcdyi_service.py"), "serve", "--fd", str(sock.fileno())]
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
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("Package links and nonregular entries are not permitted")
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


def load_release_controller(target: Path):
    """Bind a verified controller and its helpers to one immutable release path."""
    target = target.resolve(strict=True)
    verify_payload(target)
    spec = importlib.util.spec_from_file_location("myaivan_release_runtime", target / "runtime.py")
    controller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller)
    return controller


def restart_restored_release(root: Path):
    """Use the original controller only for an unchanged legacy isolated store."""
    config = read_json(root / "config.json")
    if ("database_mode" not in config and config.get("host_profile") == "isolated"
            and not config.get("database_config_file")
            and not config.get("external", {}).get("aivan_database_url")
            and not config.get("external", {}).get("database")):
        previous = release(root)
        verify_payload(previous)
        # Do not rewrite the restored configuration to satisfy a newer SQL
        # contract, or invoke the CLI while holding the installation lock.
        spec = importlib.util.spec_from_file_location("myaivan_restored_runtime", previous / "runtime.py")
        controller = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(controller)
        return controller.start(root)
    return start(root)


def install(root: Path, payload: Path, tenants: list[str], port: int, no_start: bool, *, database_config_file=None, isolated_sqlite=False, profile_file=None, service_credentials_file=None):
    manifest = verify_payload(payload)
    version = manifest["release"]
    if not NAME.fullmatch(version):
        raise ValueError("Invalid package release identifier")
    for name in ("releases", "data", "logs", "run", "backups"):
        (root / name).mkdir(exist_ok=True, mode=0o700)
    config_path = root / "config.json"
    if not config_path.exists():
        initial = new_config(tenants, port)
        if database_config_file:
            initial["database_config_file"] = str(database_config_file.absolute())
        if isolated_sqlite:
            initial["database_mode"] = "isolated"
        write_json(config_path, initial)
    original_config = upgrade_config(read_json(config_path))
    config = json.loads(json.dumps(original_config))
    if profile_file:
        helpers = load_deployment_module()
        config = helpers.profile(config, helpers.private_json(profile_file.absolute()),
                                 endpoint=endpoint, tenant_identities=fulfillment_tenants)
    if service_credentials_file:
        config["service_credentials_file"] = str(service_credentials_file.absolute())
    if database_config_file:
        config.update(database_mode="external", database_config_file=str(database_config_file.absolute()))
    elif isolated_sqlite:
        config.update(database_mode="isolated", database_config_file="")
    validate_config(config)
    load_deployment_module().credentials(config, require_external=not no_start)
    if config.get("database_config_file"):
        load_database_module().configured_targets(config, root)
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
        if (root / "previous.json").exists():
            shutil.copy2(root / "previous.json", snapshot / "previous.json")
        write_json(root / "previous.json", {"release": previous.name, "snapshot": snapshot.name})
    write_json(config_path, config)
    publish_ports(root, config)
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
                if (snapshot / "previous.json").exists():
                    shutil.copy2(snapshot / "previous.json", root / "previous.json")
                else:
                    (root / "previous.json").unlink(missing_ok=True)
                publish_ports(root, read_json(config_path))
                if (config.get("database_mode") != "external" or
                        original_config.get("database_mode") == "external" and
                        original_config.get("database_config_file") == config.get("database_config_file")):
                    restart_restored_release(root)
            raise
    config = read_json(config_path)
    return {"installed": version, "prefix": str(root), "started": not no_start, "web_url": f"http://127.0.0.1:{config['ports']['web']}", "fulfillment_url": f"http://127.0.0.1:{config['ports']['abcdyi']}", "fulfillment_auth": "reuse tenant API credential at /api/installation/session", "credentials_file": str(config_path), "data_retained": True, "ports_file": str(root / "run/ports.json"), "workflow_acceptance": "not_measured_by_installation", "pending_configuration": (["authorized private SQL configuration and explicit schema migration"] if config.get("database_mode") == "external" and not config.get("database_config_file") else []) + ["verified HTTPS ingress for public browser access"], "optional_capabilities": {"model": "configured" if config["model"]["url"] else "disabled_deterministic_human_review_guidance", "non_English_translation": "configured_requires_verification" if config["language"]["url"] or config["language"].get("model_dir") else "requires_verified_models_or_provider"}}


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
    install_parser.add_argument("--profile-file", type=Path)
    install_parser.add_argument("--service-credentials-file", type=Path)
    install_db = install_parser.add_mutually_exclusive_group()
    install_db.add_argument("--database-config-file", type=Path)
    install_db.add_argument("--isolated-sqlite", action="store_true", help="Explicit disposable/local test profile only")
    for command in ("start", "stop", "restart", "health", "check", "status", "supervise", "recover", "rollback", "uninstall", "verify", "serve", "service-install", "service-uninstall"):
        commands.add_parser(command)
    setup_parser = commands.add_parser("setup", aliases=["prepare"], help="Prepare deployment values without source editing or database migration")
    setup_parser.add_argument("--profile-file", type=Path)
    setup_parser.add_argument("--service-credentials-file", type=Path)
    setup_parser.add_argument("--origin")
    setup_parser.add_argument("--host-profile", choices=("isolated", "ctyun", "sin", "other"))
    setup_parser.add_argument("--web-port", type=int)
    setup_parser.add_argument("--model-url")
    setup_parser.add_argument("--model-name")
    setup_parser.add_argument("--language-url")
    setup_parser.add_argument("--language-model-dir", type=Path)
    setup_parser.add_argument("--database-url")
    setup_parser.add_argument("--database-provider-id", help="Logical data-store identity; retain only when moving the same records")
    setup_parser.add_argument("--gltg-url")
    setup_parser.add_argument("--gpm-url")
    setup_parser.add_argument("--openclaw-url")
    email_group = setup_parser.add_mutually_exclusive_group()
    email_group.add_argument("--enable-email", action="store_true")
    email_group.add_argument("--disable-email", action="store_true")
    setup_parser.add_argument("--restart", action="store_true")
    setup_db = setup_parser.add_mutually_exclusive_group()
    setup_db.add_argument("--database-config-file", type=Path)
    setup_db.add_argument("--isolated-sqlite", action="store_true")
    for database_command in ("database-plan", "database-migrate"):
        database_parser = commands.add_parser(database_command)
        database_parser.add_argument("--plan-file", type=Path, required=True)
        database_parser.add_argument("--component", action="append", choices=("aivan", "abcdyi", "database"))
        if database_command == "database-migrate":
            database_parser.add_argument("--tenant-id", required=True)
            database_parser.add_argument("--authorization-reference", required=True)
            database_parser.add_argument("--backup-reference", required=True)
            database_parser.add_argument("--bootstrap-empty", action="store_true")
    buyer_parser = commands.add_parser("buyer-create", help="Create a separate buyer login with local hidden password entry")
    buyer_parser.add_argument("--tenant", required=True)
    buyer_parser.add_argument("--email", required=True)
    buyer_parser.add_argument("--full-name", required=True)
    configure_parser = commands.add_parser("configure")
    configure_parser.add_argument("--file", type=Path, required=True)
    for setup_command in ("database-configure", "service-configure"):
        operator_parser = commands.add_parser(setup_command, help="Enter existing credentials locally without source editing")
        operator_parser.add_argument("--file", type=Path, required=True)
        operator_parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    root = args.prefix.absolute()
    check_root(root, initialize=args.command == "install")
    if args.command in {"supervise", "serve"}:
        if args.command == "serve":
            config = read_json(root / "config.json")
            validate_config(config)
            load_deployment_module().credentials(config, require_external=True)
            if status(root)["running"]:
                raise RuntimeError("Services already have a supervisor")
            stop(root)
            rel = release(root)
            subprocess.run([python(rel), "-B", "-I", str(rel / "bootstrap.py"), str(root)], env=environment(root, rel, config), cwd=root, check=True)
        supervise(root)
        return 0
    if args.command in {"health", "check", "status", "verify"}:
        if args.command == "check":
            manifest = verify_payload(release(root))
            result = health(root)
            result["verified_release"] = manifest["release"]
            result["ports_file"] = str(root / "run/ports.json")
        else:
            result = health(root) if args.command == "health" else status(root) if args.command == "status" else {"verified": verify_payload(release(root))["release"]}
    else:
        with operation_lock(root):
            if args.command == "buyer-create":
                rel = release(root)
                verify_payload(rel)
                config = read_json(root / "config.json")
                process = subprocess.run([python(rel), "-B", "-I", str(rel / "abcdyi_service.py"), "buyer-create",
                    "--tenant", args.tenant, "--email", args.email, "--full-name", args.full_name],
                    env=environment(root, rel, config), cwd=root, stdout=subprocess.PIPE, text=True)
                if process.returncode:
                    raise RuntimeError("Buyer creation failed; no existing account or role is replaced")
                result = json.loads(process.stdout)
            elif args.command in {"database-configure", "service-configure"}:
                spec = importlib.util.spec_from_file_location("myaivan_operator_setup", Path(__file__).with_name("operator_setup.py"))
                operator = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(operator)
                config = read_json(root / "config.json")
                if args.command == "database-configure":
                    result = operator.configure_databases(config, args.file, validator=load_database_module().sql_target, replace=args.replace)
                else:
                    result = operator.configure_services(config, args.file, validator=load_deployment_module().header_secret, replace=args.replace)
            elif args.command in {"service-install", "service-uninstall"}:
                service = load_service_module()
                if args.command == "service-install":
                    result = service.install(root, stop=stop, start=start, status=status, wait_healthy=wait_healthy, write_json=write_json)
                else:
                    result = service.uninstall(root, stop=stop)
            elif args.command == "install":
                result = install(root, args.payload.resolve(), args.tenant or ["local-tenant"], args.web_port, args.no_start,
                                 database_config_file=args.database_config_file, isolated_sqlite=args.isolated_sqlite,
                                 profile_file=args.profile_file, service_credentials_file=args.service_credentials_file)
            elif args.command in {"start", "recover", "restart"}:
                if args.command != "start":
                    config = read_json(root / "config.json")
                    validate_config(config)
                    load_deployment_module().credentials(config, require_external=True)
                    stop(root)
                result = start(root)
            elif args.command == "stop":
                result = stop(root)
            elif args.command in {"setup", "prepare"}:
                existing = read_json(root / "config.json")
                updated = json.loads(json.dumps(existing))
                if args.profile_file:
                    helpers = load_deployment_module()
                    updated = helpers.profile(updated, helpers.private_json(args.profile_file.absolute()),
                                              endpoint=endpoint, tenant_identities=fulfillment_tenants)
                if args.service_credentials_file:
                    updated["service_credentials_file"] = str(args.service_credentials_file.absolute())
                for dependency in ("gltg", "gpm"):
                    url = getattr(args, dependency + "_url")
                    if url is not None:
                        if url:
                            updated["external"][dependency] = endpoint(url)
                        else:
                            updated["external"].pop(dependency, None)
                if args.openclaw_url is not None:
                    updated.setdefault("channels", {})["openclaw_url"] = endpoint(args.openclaw_url) if args.openclaw_url else ""
                if args.enable_email or args.disable_email:
                    updated.setdefault("channels", {})["email_enabled"] = args.enable_email
                if args.database_config_file:
                    updated.update(database_mode="external", database_config_file=str(args.database_config_file.absolute()))
                elif args.isolated_sqlite:
                    updated.update(database_mode="isolated", database_config_file="")
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
                        if args.database_url != existing["external"].get("database") and not args.database_provider_id:
                            raise ValueError("Specify --database-provider-id for the selected store; retain an existing identity only when moving the same records")
                        updated["external"]["database"] = endpoint(args.database_url)
                    else:
                        updated["external"].pop("database", None)
                        updated["private_data_provider_id"] = updated["bundled_private_data_provider_id"]
                if args.database_provider_id is not None:
                    if not updated["external"].get("database") and updated.get("database_mode") != "external":
                        raise ValueError("The isolated bundled store retains its installation-owned provider identity")
                    updated["private_data_provider_id"] = args.database_provider_id
                validate_config(updated)
                load_deployment_module().credentials(updated, require_external=args.restart)
                if args.restart or updated.get("database_config_file") or updated.get("database_mode") == "isolated":
                    load_database_module().configured_targets(updated, root)
                was_running = status(root)["running"]
                if was_running and not args.restart:
                    raise RuntimeError("Use setup --restart to apply settings transactionally to a running instance")
                stop(root)
                write_json(root / "config.json", updated)
                publish_ports(root, updated)
                try:
                    if args.restart:
                        start(root)
                except Exception:
                    write_json(root / "config.json", existing)
                    publish_ports(root, existing)
                    if (was_running and (updated.get("database_mode") != "external" or
                            existing.get("database_mode") == "external" and
                            existing.get("database_config_file") == updated.get("database_config_file"))):
                        start(root)
                    raise
                updated = read_json(root / "config.json")
                result = {"configured": True, "restarted": args.restart, "public_origin": updated["origin"],
                          "internal_web_url": f"http://127.0.0.1:{updated['ports']['web']}", "workflow_acceptance": "not_measured_by_setup",
                          "database_configuration_selected": bool(updated.get("database_config_file")) or updated.get("database_mode") == "isolated",
                          "remaining_verification": ["existing HTTPS ingress", "selected business-flow acceptance"]}
            elif args.command in {"database-plan", "database-migrate"}:
                if args.command == "database-migrate" and status(root)["running"]:
                    raise RuntimeError("Stop the managed services before an explicit database migration")
                rel = release(root)
                verify_payload(rel)
                config = read_json(root / "config.json")
                command = [python(rel), "-B", "-I", str(rel / "databases.py"),
                           "plan" if args.command == "database-plan" else "migrate", "--prefix", str(root),
                           "--plan-file", str(args.plan_file.absolute())]
                for component in args.component or []:
                    command += ["--component", component]
                if args.command == "database-migrate":
                    command += ["--tenant-id", args.tenant_id, "--authorization-reference", args.authorization_reference,
                                "--backup-reference", args.backup_reference]
                    if args.bootstrap_empty:
                        command.append("--bootstrap-empty")
                process = subprocess.run(command, env=environment(root, rel, config), cwd=root,
                                         capture_output=True, text=True)
                try:
                    result = json.loads(process.stdout)
                    if not isinstance(result, dict):
                        raise ValueError()
                except (ValueError, TypeError):
                    raise RuntimeError("Database operation did not produce a verified result; credentials and driver output are redacted") from None
                if process.returncode:
                    result["ok"] = False
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
                target_controller = load_release_controller(target)
                previous_config = read_json(root / "config.json")
                target_config = config_for_release(previous_config, target)
                # Enforce current credential requirements before stopping or
                # switching to an older controller with a weaker preflight.
                validate_config(target_config)
                load_deployment_module().credentials(target_config, require_external=True)
                stop(root)
                current = release(root)
                write_json(root / "config.json", target_config)
                set_current(root, target)
                try:
                    # Call in-process: another CLI would reacquire our lock.
                    result = target_controller.start(root)
                except Exception:
                    set_current(root, current)
                    write_json(root / "config.json", previous_config)
                    load_release_controller(current).start(root)
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
