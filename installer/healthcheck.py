"""Read-only installed-service probes with authenticated tenant readiness."""
from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class UnsafeAuthenticatedEndpoint(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url: str, headers: dict | None = None) -> dict:
    credential_headers = {"authorization", "proxy-authorization", "cookie",
                          "x-aivan-api-key", "x-api-key", "x-service-auth"}
    if any(name.lower() in credential_headers for name in (headers or {})):
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        loopback = host.lower() == "localhost"
        if not loopback:
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                pass
        if (parsed.scheme not in {"http", "https"} or not host
                or parsed.username or parsed.password or parsed.fragment
                or parsed.scheme == "http" and not loopback):
            raise UnsafeAuthenticatedEndpoint("Authenticated readiness requires HTTPS or a literal loopback endpoint")
    request = urllib.request.Request(url, headers=headers or {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=5) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Readiness response exceeded the configured bound")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Readiness response must be an object")
    return value


def probe(config: dict, services: dict, credential_values: dict) -> dict:
    report = {}
    for name, (_application, path) in services.items():
        if name not in config["ports"]:
            continue
        external = config["external"].get(name)
        url = external or f"http://127.0.0.1:{config['ports'][name]}"
        descriptor = credential_values.get(name, {})
        if (external and name in {"database", "gltg", "gpm"}
                and (not isinstance(descriptor, dict) or not descriptor)):
            report[name] = {"ok": False, "status": "credentials_required",
                            "message": "Configure service_credentials_file with credentials for the selected external "
                                       + name + " service before checking readiness."}
            continue
        try:
            tenant_status = None
            if name == "gpm":
                keys = descriptor.get("tenant_keys", {}) if external else config["tenants"]
                if (not isinstance(keys, dict) or set(keys) != set(config["tenants"])
                        or not keys or not all(isinstance(key, str) and key and key.isascii()
                                              and all(33 <= ord(char) < 127 for char in key)
                                              for key in keys.values())):
                    report[name] = {"ok": False, "status": "credentials_required",
                                    "message": "Configure service_credentials_file with gpm.tenant_keys covering exactly the configured tenants."}
                    continue
                tenant_status = {}
                for tenant, key in keys.items():
                    result = request_json(url + "/api/gpm/readiness", {
                        "X-AIVAN-Tenant-ID": tenant,
                        "X-AIVAN-API-Key": key,
                        "X-AIVAN-Actor-ID": "installation-readiness",
                        "X-AIVAN-Role": "admin",
                    })
                    tenant_status[tenant] = (result.get("status") == "ok" and result.get("tenant_id") == tenant
                                             and result.get("packet_persistence") == "durable")
            data = request_json(url + path)
            ok = data.get("status", "ok") in {"ok", "healthy", "ready"} and data.get("ok", True) is True
            if name == "gpm":
                ok = ok and bool(tenant_status) and all(tenant_status.values()) and data.get("packet_persistence") == "durable"
            if name == "gltg":
                ready = request_json(url + "/ready")
                ok = ok and ready.get("ready") is True and ready.get("giraffe_db") == "ok" and ready.get("persistence_enabled") is True
            report[name] = {"ok": bool(ok), "status": str(data.get("status", "ok"))}
            if tenant_status is not None:
                report[name]["tenants"] = tenant_status
                report[name]["packet_persistence"] = data.get("packet_persistence")
        except UnsafeAuthenticatedEndpoint:
            report[name] = {"ok": False, "status": "https_required",
                            "message": "Configure HTTPS for authenticated non-loopback readiness probes."}
        except (OSError, ValueError, urllib.error.URLError):
            report[name] = {"ok": False, "status": "readiness_failed"}
    return report
