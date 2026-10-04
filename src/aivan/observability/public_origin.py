"""Validate and resolve the public browser origin for myAIVAN.

The origin can be configured explicitly or derived from ``AIVAN_PUBLIC_HOST``
and the automatically selected port. Its effective port must not be one of the
ports the environment reserves (``AIVAN_RESERVED_PORTS``).
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from aivan.utils.ports import reserved_ports

_SCHEME_DEFAULT_PORTS = {"http": 80, "https": 443}


def public_origin_issue(origin: str, reserved: frozenset[int] | None = None) -> str | None:
    """Return why ``origin`` is not an acceptable public origin, or ``None``."""

    value = origin.strip()
    if not value:
        return "public origin is not configured"
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return "public origin is not a valid URL"
    if parts.scheme not in _SCHEME_DEFAULT_PORTS or not parts.hostname:
        return "public origin must be an http or https origin with a host"
    if parts.username or parts.password or parts.path or parts.query or parts.fragment:
        return "public origin must be a bare origin without credentials or path"
    effective_port = _SCHEME_DEFAULT_PORTS[parts.scheme] if port is None else port
    if effective_port in (reserved_ports() if reserved is None else reserved):
        return f"public origin uses reserved port {effective_port}"
    if value != f"{parts.scheme}://{parts.netloc.lower()}":
        return "public origin must be lowercase and normalized"
    return None


def public_origin_valid(origin: str, reserved: frozenset[int] | None = None) -> bool:
    return public_origin_issue(origin, reserved) is None


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


def resolved_public_origin() -> str:
    """Return the public origin, deriving it from the auto-selected port if needed.

    ``AIVAN_PUBLIC_ORIGIN`` wins when set. Otherwise, when ``AIVAN_PUBLIC_HOST``
    is set, the origin is built from it and the port AIVAN actually bound
    (``AIVAN_PORT``), so no port has to be configured by hand.
    """

    explicit = os.environ.get("AIVAN_PUBLIC_ORIGIN", "").strip()
    if explicit:
        return explicit
    host = os.environ.get("AIVAN_PUBLIC_HOST", "").strip().lower()
    port = os.environ.get("AIVAN_PORT", "").strip()
    if not host or not port:
        return ""
    scheme = os.environ.get("AIVAN_PUBLIC_SCHEME", "").strip().lower() or "http"
    return f"{scheme}://{host}:{port}"
