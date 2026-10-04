"""Validate the operator-configured public browser origin for myAIVAN.

On CTYun hosts TCP 443 belongs to SSH. HTTP and HTTPS may use any other
unoccupied port, but the port is never implied: the origin must state it
explicitly, and an origin on port 443 is rejected.
"""

from __future__ import annotations

from urllib.parse import urlsplit

RESERVED_PUBLIC_PORT = 443
_SCHEME_DEFAULT_PORTS = {"http": 80, "https": 443}


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
    if parts.scheme not in _SCHEME_DEFAULT_PORTS or not parts.hostname:
        return "AIVAN_PUBLIC_ORIGIN must be an http or https origin with a host"
    if parts.username or parts.password or parts.path or parts.query or parts.fragment:
        return "AIVAN_PUBLIC_ORIGIN must be a bare origin without credentials or path"
    if port is None:
        return "AIVAN_PUBLIC_ORIGIN must state its port explicitly"
    if port == RESERVED_PUBLIC_PORT:
        return f"AIVAN_PUBLIC_ORIGIN must not use port {RESERVED_PUBLIC_PORT}"
    if value != f"{parts.scheme}://{parts.netloc.lower()}":
        return "AIVAN_PUBLIC_ORIGIN must be lowercase and normalized"
    return None


def public_origin_valid(origin: str) -> bool:
    return public_origin_issue(origin) is None


def browser_origin(origin: str) -> str:
    """Return ``origin`` as a browser sends it, without a scheme-default port."""

    parts = urlsplit(origin.strip())
    try:
        port = parts.port
    except ValueError:
        return origin.strip()
    if port is not None and port == _SCHEME_DEFAULT_PORTS.get(parts.scheme):
        return f"{parts.scheme}://{parts.hostname}"
    return origin.strip()
