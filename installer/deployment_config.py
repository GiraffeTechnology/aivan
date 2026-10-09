"""Operator-owned deployment values and credentials, kept outside releases."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import stat


def private_json(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("Private configuration requires an absolute path")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) & 0o077):
                raise ValueError("Private configuration must be an owner-only regular file")
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("Private configuration cannot be read safely") from None
    if not isinstance(value, dict):
        raise ValueError("Private configuration must contain an object")
    return value


def header_secret(value) -> bool:
    return isinstance(value, str) and bool(value) and value.isascii() and all(33 <= ord(c) < 127 for c in value)


def credentials(config: dict, *, require_external: bool = False) -> dict:
    """Read supplied credentials; require completeness only at a use boundary."""
    path = config.get("service_credentials_file", "")
    value = private_json(path) if path else {"version": 1, "services": {}}
    if set(value) != {"version", "services"} or type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unsupported service-credential file")
    services = value["services"]
    if not isinstance(services, dict) or set(services) - {"database", "gltg", "gpm", "openclaw"}:
        raise ValueError("Unsupported service-credential entry")
    for name, descriptor in services.items():
        if name != "openclaw" and not config.get("external", {}).get(name):
            raise ValueError("External credentials require the corresponding external service")
        allowed = {"tenant_keys"} if name == "gpm" else {"service_auth", "tenant_service_auth"} if name == "database" else {"api_key"} if name == "openclaw" else {"service_auth"}
        if not isinstance(descriptor, dict) or not descriptor or set(descriptor) - allowed:
            raise ValueError("Unsupported service-credential descriptor")
        for field, secret in descriptor.items():
            if field in {"tenant_keys", "tenant_service_auth"}:
                if (not isinstance(secret, dict) or set(secret) != set(config["tenants"])
                        or not all(header_secret(item) for item in secret.values())):
                    raise ValueError("External credentials must cover exactly the configured tenants")
            elif not header_secret(secret):
                raise ValueError("Service credentials must be nonblank safe header values")
    if require_external:
        missing = [name for name in ("database", "gltg", "gpm")
                   if config.get("external", {}).get(name) and name not in services]
        if missing:
            raise ValueError("External service credentials are required for: " + ", ".join(missing)
                             + ". Configure service_credentials_file before startup.")
    return services


def credential_environment(config: dict) -> dict[str, str]:
    supplied = credentials(config, require_external=True)
    result = {}
    if "database" in supplied:
        descriptor = supplied["database"]
        shared = descriptor.get("service_auth", "")
        mapping = descriptor.get("tenant_service_auth") or {tenant: shared for tenant in config["tenants"]}
        result.update({
            "GIRAFFE_DB_SERVICE_AUTH_SECRET": shared,
            "GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON": json.dumps(mapping),
            "GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET": shared,
            "GLTG_GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON": json.dumps(mapping),
        })
    if "gltg" in supplied:
        result["GLTG_SERVICE_AUTH_SECRET"] = supplied["gltg"]["service_auth"]
    if "gpm" in supplied:
        result["GPM_TENANT_API_KEYS"] = json.dumps(supplied["gpm"]["tenant_keys"])
    if "openclaw" in supplied:
        result["OPENCLAW_API_KEY"] = supplied["openclaw"]["api_key"]
    return result


def reserved_ports(config: dict) -> set[int]:
    result = set(config.get("reserved_ports", []))
    raw = os.environ.get("AIVAN_RESERVED_PORTS", "")
    for value in raw.split(","):
        if not value.strip():
            continue
        if not value.strip().isdigit() or not 1 <= int(value) <= 65535:
            raise ValueError("AIVAN_RESERVED_PORTS must be a comma-separated numeric list")
        result.add(int(value))
    return result


def profile(config: dict, value: dict, *, endpoint, tenant_identities) -> dict:
    """Merge deployment inputs while preserving installation-owned identities."""
    allowed = {"version", "origin", "host_profile", "reserved_ports", "requested_ports", "runtime_threads", "tenant_ids",
               "database_config_file", "service_credentials_file", "private_data_provider_id",
               "external", "language", "model", "channels"}
    if (not isinstance(value, dict) or set(value) - allowed
            or type(value.get("version")) is not int or value["version"] != 1):
        raise ValueError("Unsupported deployment profile; secrets belong in the credential file")
    result = copy.deepcopy(config)
    for name in ("origin", "host_profile", "reserved_ports", "runtime_threads", "database_config_file", "service_credentials_file", "private_data_provider_id"):
        if name in value:
            result[name] = value[name]
    if value.get("database_config_file"):
        result["database_mode"] = "external"
    if "tenant_ids" in value and value["tenant_ids"] != list(config["tenants"]):
        raise ValueError("Tenant changes require an explicitly reviewed installation configuration; a profile cannot silently remove or replace tenants")
    for group, fields in (("language", {"url", "provider", "model", "model_dir"}),
                          ("model", {"url", "name"}),
                          ("channels", {"openclaw_url", "send_endpoint", "email_enabled"})):
        if group in value:
            if not isinstance(value[group], dict) or set(value[group]) - fields:
                raise ValueError("Unsupported deployment-profile fields")
            result.setdefault(group, {}).update(value[group])
    if "external" in value:
        external = value["external"]
        if not isinstance(external, dict) or set(external) - {"database", "gltg", "gpm", "language"}:
            raise ValueError("Unsupported external service")
        for name, url in external.items():
            if url:
                result["external"][name] = endpoint(url)
            else:
                result["external"].pop(name, None)
        if result["external"].get("database") != config["external"].get("database"):
            if result["external"].get("database"):
                if not value.get("private_data_provider_id"):
                    raise ValueError("Select the external store's logical provider identity explicitly")
            else:
                result["private_data_provider_id"] = result["bundled_private_data_provider_id"]
    if "language" in value and "url" in value["language"]:
        if result["language"]["url"]:
            result["external"]["language"] = endpoint(result["language"]["url"])
        else:
            result["external"].pop("language", None)
    if "requested_ports" in value:
        ports = value["requested_ports"]
        if not isinstance(ports, dict) or set(ports) - set(result["ports"]):
            raise ValueError("Requested ports must name installed services")
        result["ports"].update(ports)
        result["fulfillment"]["port"] = result["ports"]["abcdyi"]
    result["fulfillment"]["tenants"] = tenant_identities(result["tenants"])
    return result


def validate(config: dict, *, endpoint) -> None:
    threads = config.get("runtime_threads", 2)
    if type(threads) is not int or not 1 <= threads <= 64:
        raise ValueError("Runtime thread count must be an integer between 1 and 64")
    reserved = config.get("reserved_ports", [])
    if not isinstance(reserved, list) or any(type(port) is not int or not 1 <= port <= 65535 for port in reserved):
        raise ValueError("Reserved ports must be numeric environment configuration")
    path = config.get("service_credentials_file", "")
    if path and (not isinstance(path, str) or not Path(path).is_absolute()):
        raise ValueError("Service credentials require an absolute private file path")
    channels = config.get("channels", {})
    if not isinstance(channels, dict) or set(channels) - {"openclaw_url", "send_endpoint", "email_enabled"}:
        raise ValueError("Unsupported channel settings")
    enabled = channels.get("email_enabled", False)
    if type(enabled) is not bool:
        raise ValueError("Email enablement must be explicit")
    url = channels.get("openclaw_url", "")
    if url:
        endpoint(url)
    if enabled and not url:
        raise ValueError("Configured email requires an existing OpenClaw gateway URL")
    send_path = channels.get("send_endpoint", "/messages/send")
    if (not isinstance(send_path, str) or not send_path.startswith("/") or send_path.startswith("//")
            or any(char in send_path for char in ("?", "#", "\\"))
            or any(ord(char) < 33 or ord(char) == 127 for char in send_path)):
        raise ValueError("OpenClaw send endpoint must be an absolute safe URL path")
