"""Interactive local-only entry of existing operator-owned connection values."""
from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from urllib.parse import quote


def write_private(path: Path, value: dict, *, replace=False):
    path = path.absolute()
    if path.is_symlink():
        raise ValueError("Private configuration cannot be a symbolic link")
    if path.exists():
        info = path.stat()
        if not replace:
            raise ValueError("Configuration already exists; use --replace only for an approved replacement")
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Existing configuration must be an owner-only regular file")
    if not path.parent.is_dir():
        raise ValueError("Create the intended private configuration directory first")
    descriptor, temporary = tempfile.mkstemp(prefix=".myaivan-private-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            # No replacement race: linking an already completed private file is atomic.
            os.link(temporary, path, follow_symlinks=False)
    finally:
        Path(temporary).unlink(missing_ok=True)


def require_terminal():
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ValueError("Enter existing credentials directly in a private interactive terminal, or select an existing private file with prepare")


def mysql_descriptor(component: str, driver: str, *, input_value=input, secret_value=getpass.getpass):
    print(f"Existing MySQL connection for {component}. No server, account or database is created.")
    host = input_value("MySQL hostname or IP: ").strip()
    port = input_value("MySQL TCP port: ").strip()
    namespace = input_value("Existing database name: ").strip()
    username = input_value("Existing database username: ").strip()
    password = secret_value("Existing database password (hidden): ")
    if not host or not username or not namespace or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("A complete existing MySQL connection is required")
    if any(char in host for char in ("/", "@", "?", "#")) or any(ord(char) < 33 for char in host):
        raise ValueError("Invalid MySQL hostname")
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"
    return {"url": f"mysql+{driver}://{quote(username, safe='')}:{quote(password, safe='')}@{host}:{int(port)}/{quote(namespace, safe='')}"}


def configure_databases(config: dict, path: Path, *, validator, replace=False):
    require_terminal()
    names = [("aivan", "pymysql"), ("abcdyi", "aiomysql")]
    if not config.get("external", {}).get("database"):
        names.append(("database", "pymysql"))
    databases = {name: mysql_descriptor(name, driver) for name, driver in names}
    targets = [validator(name, item)["namespace"] for name, item in databases.items()]
    if len(set(targets)) != len(targets):
        raise ValueError("The applications require distinct existing database namespaces")
    write_private(path, {"version": 1, "databases": databases}, replace=replace)
    return {"configured": True, "file": str(path.absolute()), "database_targets": len(databases),
            "database_connections_tested": False, "next": "prepare --database-config-file FILE, then database-plan"}


def configure_services(config: dict, path: Path, *, validator, replace=False):
    require_terminal()
    services = {}
    for name in ("database", "gltg", "gpm"):
        if not config.get("external", {}).get(name):
            continue
        if name == "gpm":
            services[name] = {"tenant_keys": {tenant: getpass.getpass(f"Existing GPM API key for {tenant} (hidden): ") for tenant in config["tenants"]}}
        elif name == "database":
            services[name] = {"tenant_service_auth": {tenant: getpass.getpass(f"Existing private-provider service credential for {tenant} (hidden): ") for tenant in config["tenants"]}}
        else:
            services[name] = {"service_auth": getpass.getpass("Existing GLTG service credential (hidden): ")}
    if config.get("channels", {}).get("openclaw_url"):
        services["openclaw"] = {"api_key": getpass.getpass("Existing OpenClaw gateway API key (hidden): ")}
    if not services:
        raise ValueError("Select existing external endpoints with prepare before entering their credentials")
    values = [value for descriptor in services.values() for item in descriptor.values() for value in (item.values() if isinstance(item, dict) else [item])]
    if not all(validator(value) for value in values):
        raise ValueError("Every selected service requires a nonblank safe credential")
    write_private(path, {"version": 1, "services": services}, replace=replace)
    return {"configured": True, "file": str(path.absolute()), "services": sorted(services),
            "next": "prepare --service-credentials-file FILE"}
