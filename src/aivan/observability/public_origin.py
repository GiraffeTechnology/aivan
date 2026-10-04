"""Validate the operator-configured public browser origin for myAIVAN.

On CTYun hosts TCP 443 belongs to SSH, so an HTTPS web entry must carry an
explicit non-443 port (for example ``https://myaivan.com:8444``). A bare
``https://host`` origin implies port 443 and is rejected; ``http://host``
implies port 80 and is allowed. Port 8443 is also rejected because it is owned
by the existing mail service. Any other port may be used for HTTP or HTTPS.
"""

from __future__ import annotations

from urllib.parse import urlsplit

RESERVED_PUBLIC_PORTS = frozenset({443, 8443})
_DEFAULT_PORTS = {"http": 80, "https": 443}


def public_origin_issue(origin: str) -> str | None:
    """Return why ``origin`` is not an acceptable public origin, or ``None``."""

    value = origin.strip()
    if not value:
        return "AIVAN_PUBLIC_ORIGIN is not configured"
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return "AIVAN_PUBLIC_ORIGIN is not a valid URL"
    if parts.scheme not in _DEFAULT_PORTS or not parts.hostname:
        return "AIVAN_PUBLIC_ORIGIN must be an http or https origin with a host"
    if parts.username or parts.password or parts.path or parts.query or parts.fragment:
        return "AIVAN_PUBLIC_ORIGIN must be a bare origin without credentials or path"
    default_port = _DEFAULT_PORTS[parts.scheme]
    effective_port = default_port if port is None else port
    if effective_port in RESERVED_PUBLIC_PORTS:
        return f"AIVAN_PUBLIC_ORIGIN must not use reserved port {effective_port}"
    if port == default_port:
        # Browsers drop a scheme-default port from Origin, so it would never match.
        return "AIVAN_PUBLIC_ORIGIN must omit the scheme-default port"
    if value != f"{parts.scheme}://{parts.netloc.lower()}":
        return "AIVAN_PUBLIC_ORIGIN must be lowercase and normalized"
    return None


def public_origin_valid(origin: str) -> bool:
    return public_origin_issue(origin) is None
